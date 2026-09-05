"""Coverage critic agent: scores a TestPlan against the six Flow.category
dimensions and decides whether to proceed, ask the Planner to re-plan, or
escalate.
"""
from __future__ import annotations

import json
import logging

from orchestrator.agents.planner import _summarize_site_model
from orchestrator.llm.client import call_structured
from orchestrator.schemas import CoverageVerdict, SiteModel, TestPlan

logger = logging.getLogger(__name__)

CATEGORIES = [
    "happy_path",
    "auth_session",
    "form_validation",
    "error_state",
    "destructive_action",
    "navigation",
]

_DIMENSION_WEIGHTS = {"covered": 1.0, "partial": 0.5, "missing": 0.0}
_PROCEED_THRESHOLD = 0.7

SYSTEM_PROMPT = """You are the Coverage Critic in an autonomous QA test-orchestration
pipeline. You are given the crawled SiteModel the Planner worked from and the
TestPlan it produced, and must score coverage across the same six categories
the Planner uses:
  - happy_path: a core successful user journey through the app
  - auth_session: logging in (and, if observed, logging out / session expiry)
  - form_validation: submitting a form with valid and with invalid input
  - error_state: triggering a 404, a failed submission, or a visible error message
  - destructive_action: an action whose label suggests delete/remove/cancel/deactivate
  - navigation: moving between pages via links/nav

For each dimension, set `dimension_scores[dim]` to exactly one of
"covered" / "partial" / "missing", and `justifications[dim]` to a short
sentence citing what the SiteModel actually contains (or doesn't) and what
the plan does (or doesn't) about it. Ground every judgment in the SiteModel
and TestPlan given — never invent pages, forms, or flows that aren't there.

Critical rule for dimensions the site doesn't support: if the SiteModel
offers nothing relevant to a dimension (e.g. no destructive-looking buttons
were found anywhere), that dimension is trivially "covered" — there is
nothing to miss, so do not penalize the plan for it. Only use "missing" when
the SiteModel shows something testable for that dimension (a form, a login
page, a delete-like button, ...) and the plan has no flow for it, and use
"partial" when a flow exists but is weak/incomplete for what the site offers.

Populate `gaps` with concrete, actionable feedback for the Planner's next
attempt — one item per real gap (e.g. "site has a contact form at /contact
but no form_validation flow tests invalid input on it"). Leave `gaps` empty
if there is nothing actionable to fix.

Do not set `overall_score` or `decision` — the caller computes those
deterministically from your dimension_scores; any value you put there is
ignored, so just pick reasonable placeholders.
"""


class Critic:
    def review(self, plan: TestPlan, site_model: SiteModel, max_iterations: int) -> CoverageVerdict:
        logger.info(
            "Critic: reviewing plan iteration=%d, flows=%d",
            plan.iteration, len(plan.flows),
        )

        user_prompt = f"{_summarize_site_model(site_model)}\n\n{_summarize_plan(plan)}"
        raw_verdict = call_structured(SYSTEM_PROMPT, user_prompt, CoverageVerdict)

        dimension_scores, justifications = _normalize_scores(raw_verdict)
        overall_score = _compute_overall_score(dimension_scores)
        decision = _decide(dimension_scores, plan.iteration, max_iterations)

        logger.info(
            "Critic: decision=%s overall_score=%.2f dimension_scores=%s",
            decision, overall_score, dimension_scores,
        )

        return CoverageVerdict(
            dimension_scores=dimension_scores,
            justifications=justifications,
            overall_score=overall_score,
            gaps=raw_verdict.gaps,
            decision=decision,
        )


def _summarize_plan(plan: TestPlan) -> str:
    lines = [f"TestPlan iteration: {plan.iteration}", f"total_flows: {len(plan.flows)}", "flows:"]
    for flow in plan.flows:
        steps_desc = "; ".join(f"{s.action}->{s.target_description!r}" for s in flow.steps)
        lines.append(
            f"- [{flow.category}/{flow.priority}, source={flow.source}] {flow.title}: {steps_desc}"
        )
    return "\n".join(lines)


def _normalize_scores(verdict: CoverageVerdict) -> tuple[dict[str, str], dict[str, str]]:
    """The model may omit a category or produce an unexpected key — fill in
    conservatively (missing => "missing") so downstream logic can always rely
    on all six categories being present.
    """
    dimension_scores = {}
    justifications = {}
    for category in CATEGORIES:
        dimension_scores[category] = verdict.dimension_scores.get(category, "missing")
        justifications[category] = verdict.justifications.get(
            category, "no justification provided by the model"
        )
    return dimension_scores, justifications


def _compute_overall_score(dimension_scores: dict[str, str]) -> float:
    weights = [_DIMENSION_WEIGHTS.get(score, 0.0) for score in dimension_scores.values()]
    return sum(weights) / len(weights) if weights else 0.0


def _decide(dimension_scores: dict[str, str], iteration: int, max_iterations: int) -> str:
    missing_count = sum(1 for score in dimension_scores.values() if score == "missing")
    overall_score = _compute_overall_score(dimension_scores)

    if missing_count == 0 and overall_score >= _PROCEED_THRESHOLD:
        return "proceed"
    if iteration < max_iterations:
        return "re_plan"
    return "escalate"
