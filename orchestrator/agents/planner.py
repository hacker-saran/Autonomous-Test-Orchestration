"""Planner agent: synthesizes a TestPlan from the crawled SiteModel (+ optional
PRD text + focus hint).

Uses a single `call_structured()` call to SARVAM_MODEL_PRIMARY, forcing the
`TestPlan` tool schema. The prompt includes the site model, PRD text (if any),
focus hint (if any), and the critic's `gaps` feedback on re-plan iterations.
"""
from __future__ import annotations

import logging

from orchestrator.agents._prompt_utils import serialize_site_model
from orchestrator.llm.client import call_structured
from orchestrator.schemas import SiteModel, TestPlan

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are an autonomous test planner for a web application. Given a crawled
model of a website, you produce a comprehensive TestPlan that a downstream
agent will turn into executable Playwright tests.

You MUST synthesize flows across these SIX categories (the same taxonomy a
coverage critic scores against):
1. happy_path — the core user journey(s) of the app
2. auth_session — login, logout, session persistence, protected routes
3. form_validation — required fields, input patterns, invalid submissions
4. error_state — 404s, API failures, empty states, server errors
5. destructive_action — delete/remove/cancel flows, ideally with confirmation
6. navigation — key pages reachable via nav links

Each flow's `category` MUST be one of those six values.
Each flow's `priority` MUST be one of: critical, happy, edge, error.
Each step's `action` MUST be one of: navigate, click, fill, select,
assert_visible, assert_text, assert_url.

Rules:
- Produce ONE TestPlan for the whole site — do not call per flow.
- Use `target_description` as a SEMANTIC description of the element (e.g.
  "email input field", "Submit button", "Delete account link") — a later
  agent resolves it to a live selector.
- Use `value` for fill/select steps (the data to enter).
- Use `expected_outcome` to state what should happen after the step.
- If a PRD is provided, derive flows from it and tag their `source` as "prd".
- If a focus hint is provided, derive flows from it and tag their `source` as "user_hint".
- Otherwise tag flows as "crawl".
- Weight PRD- and focus-derived flows as higher priority.
- If the critic provided `feedback` (gaps), address those gaps in this iteration.
- Do NOT invent pages or elements that are not present in the site model.
- If the site model is empty or has no pages, return an empty flows list.
"""


class Planner:
    def plan(
        self,
        site_model: SiteModel,
        prd_text: str | None = None,
        focus_hint: str | None = None,
        feedback: list[str] | None = None,
        iteration: int = 0,
    ) -> TestPlan:
        """Synthesize a TestPlan via a single structured LLM call."""
        logger.info(
            "Planner: calling LLM, iteration=%d, pages=%d, prd=%s, focus=%s, feedback=%s",
            iteration, len(site_model.pages), bool(prd_text), bool(focus_hint), feedback or [],
        )

        user_prompt = self._build_user_prompt(site_model, prd_text, focus_hint, feedback, iteration)
        plan = call_structured(_SYSTEM_PROMPT, user_prompt, TestPlan)
        plan.iteration = iteration

        logger.info(
            "Planner: produced %d flows (categories=%s)",
            len(plan.flows),
            {c: sum(1 for f in plan.flows if f.category == c) for c in
             ["happy_path", "auth_session", "form_validation", "error_state", "destructive_action", "navigation"]},
        )
        return plan

    @staticmethod
    def _build_user_prompt(
        site_model: SiteModel,
        prd_text: str | None,
        focus_hint: str | None,
        feedback: list[str] | None,
        iteration: int,
    ) -> str:
        parts = ["SITE MODEL (crawled from the live app):", serialize_site_model(site_model)]

        if prd_text:
            parts.append("\nPRD (product requirements — derive flows from these and tag source='prd'):")
            parts.append(prd_text)

        if focus_hint:
            parts.append("\nFOCUS HINT (user's testing focus — derive flows from these and tag source='user_hint'):")
            parts.append(focus_hint)

        if feedback:
            parts.append("\nCRITIC FEEDBACK (gaps from the previous plan — address these in this iteration):")
            for gap in feedback:
                parts.append(f"- {gap}")

        parts.append(f"\nPLANNING ITERATION: {iteration}")
        parts.append(
            "\nProduce a TestPlan covering the site across the six categories "
            "(happy_path, auth_session, form_validation, error_state, destructive_action, navigation)."
        )
        return "\n".join(parts)