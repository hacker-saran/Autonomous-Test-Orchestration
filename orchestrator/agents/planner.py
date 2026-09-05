"""Planner agent: synthesizes a TestPlan from the crawled SiteModel (+ optional
PRD text + focus hint) via a single structured LLM call.

Security note: this agent never receives raw credential values — only a
`has_credentials` flag. When it needs to represent a login step, it emits the
literal placeholders `{{username}}` / `{{password}}` as the FlowStep.value,
never real secrets. The Generator (see its TODO) is responsible for
substituting real values from the local credentials file at codegen time, and
downstream flows are expected to reuse a captured `storage_state` rather than
re-running login per flow — so a login FlowStep only needs to appear once, in
the dedicated `auth_session` flow.
"""
from __future__ import annotations

import json
import logging

from orchestrator.llm.client import call_structured
from orchestrator.schemas import Flow, FlowStep, PageInfo, SiteModel, TestPlan

logger = logging.getLogger(__name__)

CATEGORIES = [
    "happy_path",
    "auth_session",
    "form_validation",
    "error_state",
    "destructive_action",
    "navigation",
]

_MAX_ITEMS_PER_PAGE = 12

SYSTEM_PROMPT = """You are the Planner in an autonomous QA test-orchestration pipeline.

You are given a crawled model of a web application (pages, forms, nav links,
buttons) and must synthesize a `TestPlan`: a list of `Flow` objects, each a
realistic end-user scenario made of ordered `FlowStep`s.

Ground every flow in what the SiteModel actually shows — never invent pages,
forms, fields, or buttons that were not observed. If the site gives you too
little to work with for a category, it is fine to omit that category rather
than fabricate.

Every flow's `category` must be exactly one of these six (this is the same
taxonomy the Coverage Critic scores against, so use it precisely):
  - happy_path: a core successful user journey through the app
  - auth_session: logging in (and, if observed, logging out / session expiry)
  - form_validation: submitting a form with valid and with invalid input
  - error_state: triggering a 404, a failed submission, or a visible error message
  - destructive_action: an action whose label suggests delete/remove/cancel/deactivate
  - navigation: moving between pages via links/nav

Every `FlowStep.action` has a specific contract the Generator relies on to
resolve it against the live app — get these wrong and the step cannot be
resolved at all:
  - "navigate": `value` MUST be a real URL taken from the SiteModel (e.g. one
    of the crawled page URLs, or a link's href). Never put an element
    description in `value` for a navigate step, and never emit a navigate
    step just to reach a page the user would actually get to by clicking
    something — use "click" for that instead. The test always starts already
    loaded on `start_url`, so do not emit a navigate step to `start_url` as
    the first step of a flow unless a prior step in the same flow intentionally
    navigated away from it.
  - "click" / "fill" / "select" / "assert_visible": `target_description` is a
    plain-language description of the element (e.g. "Sign in button in login
    form"), resolved to a live selector later — never put a URL or a raw
    selector here.
  - "assert_text" / "assert_url": `value` is the expected text or URL to
    assert against.

Rules:
  1. If `has_credentials` is true and the site has a login-like form, emit
     exactly one `auth_session` flow that performs the login. If the login
     form is already on `start_url` (the common case), the flow's first step
     is the "fill" for the username field — do not prepend a "navigate" step
     to reach it. For the username/password `fill` steps, set `value` to the
     literal string `{{username}}` or `{{password}}` (never a real credential
     — you were not given real values, so never invent one that looks real
     either). Do not repeat login steps in other flows; assume other flows
     run in an already authenticated session when auth_session exists.
  2. For `destructive_action` flows, do NOT complete the destructive action for
     real. Stop at verifying the control and any confirmation UI exist/appear
     (e.g. assert a confirmation dialog is visible) — never assert the
     underlying resource was actually deleted.
  3. For `form_validation` / `error_state` flows, use clearly-fake but
     plausible test data (e.g. "test@example.com"), and for error_state use
     data designed to fail validation (e.g. an empty required field, a
     malformed email).
  4. If `prd_text` is given, add flows that cover its explicit requirements
     and set their `source` to "prd".
  5. If `focus_hint` is given, prioritize flows matching it (set `priority`
     higher, e.g. "critical") and set their `source` to "user_hint".
  6. If `feedback` (gaps from a previous Critic review) is given, this is a
     re-plan: your new plan must directly address every listed gap.
  7. Every other flow's `source` defaults to "crawl".
  8. Produce the whole plan in this one response — do not ask for more calls.
"""


def _summarize_page(page: PageInfo) -> str:
    forms_desc = []
    for form in page.forms[:_MAX_ITEMS_PER_PAGE]:
        fields = ", ".join(f"{f.name or '(unnamed)'}:{f.field_type}{'*' if f.required else ''}" for f in form.fields)
        forms_desc.append(f"form(action={form.action or '?'}, method={form.method or '?'}, fields=[{fields}])")

    nav_texts = [l.text for l in page.nav_links[:_MAX_ITEMS_PER_PAGE]]
    button_texts = [f"{b.text}{' [destructive]' if b.is_destructive else ''}" for b in page.buttons[:_MAX_ITEMS_PER_PAGE]]

    lines = [f"- {page.url} (title={page.title!r})"]
    if forms_desc:
        lines.append(f"  forms: {'; '.join(forms_desc)}")
    if nav_texts:
        lines.append(f"  nav_links: {', '.join(nav_texts)}")
    if button_texts:
        lines.append(f"  buttons: {', '.join(button_texts)}")
    return "\n".join(lines)


def _summarize_site_model(site_model: SiteModel) -> str:
    parts = [f"start_url: {site_model.start_url}", f"pages_crawled: {len(site_model.pages)}"]
    if site_model.partial:
        parts.append(f"partial_crawl: true, notes: {site_model.notes}")
    parts.append("pages:")
    parts.extend(_summarize_page(page) for page in site_model.pages)
    return "\n".join(parts)


def _build_user_prompt(
    site_model: SiteModel,
    prd_text: str | None,
    focus_hint: str | None,
    feedback: list[str],
    has_credentials: bool,
    iteration: int,
) -> str:
    payload = {
        "iteration": iteration,
        "has_credentials": has_credentials,
        "focus_hint": focus_hint,
        "feedback_from_previous_critique": feedback or None,
        "prd_text": prd_text,
    }
    return (
        f"{_summarize_site_model(site_model)}\n\n"
        f"Other inputs (JSON):\n{json.dumps(payload, indent=2)}"
    )


class Planner:
    def plan(
        self,
        site_model: SiteModel,
        prd_text: str | None = None,
        focus_hint: str | None = None,
        feedback: list[str] | None = None,
        iteration: int = 0,
        has_credentials: bool = False,
    ) -> TestPlan:
        logger.info(
            "Planner: synthesizing plan, iteration=%d, pages=%d, has_credentials=%s, feedback=%s",
            iteration, len(site_model.pages), has_credentials, feedback or [],
        )

        user_prompt = _build_user_prompt(site_model, prd_text, focus_hint, feedback or [], has_credentials, iteration)
        plan = call_structured(SYSTEM_PROMPT, user_prompt, TestPlan)

        normalized_flows = _normalize_flow_ids(plan.flows)
        logger.info(
            "Planner: got %d flows (categories=%s)",
            len(normalized_flows), sorted({f.category for f in normalized_flows}),
        )
        return TestPlan(flows=normalized_flows, iteration=iteration)


def _normalize_flow_ids(flows: list[Flow]) -> list[Flow]:
    """The model may not produce unique/sequential ids — re-number
    deterministically so downstream Generator/Executor filenames and
    selector_map keys never collide.
    """
    normalized: list[Flow] = []
    for i, flow in enumerate(flows):
        flow_id = f"flow-{i}"
        steps = [
            step.model_copy(update={"step_id": f"{flow_id}-step-{j}"})
            for j, step in enumerate(flow.steps)
        ]
        normalized.append(flow.model_copy(update={"flow_id": flow_id, "steps": steps}))
    return normalized
