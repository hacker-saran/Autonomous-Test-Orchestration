"""Coverage critic agent: scores a TestPlan against the six Flow.category
dimensions and decides whether to proceed, ask the Planner to re-plan, or
escalate.

Uses a single `call_structured()` call to SARVAM_MODEL_PRIMARY, forcing the
`CoverageVerdict` tool schema. The decision (proceed / re_plan / escalate) is
computed deterministically from the LLM's dimension scores so the re-plan loop
is bounded and predictable.
"""
from __future__ import annotations

import logging

from orchestrator.agents._prompt_utils import serialize_plan, serialize_site_model
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

# A dimension is "covered" if the plan has at least one flow of that category.
# The LLM decides partial vs missing based on the site model evidence.
_PARTIAL_WEIGHT = 0.5
_COVERED_WEIGHT = 1.0

_SYSTEM_PROMPT = """\
You are a coverage critic for an autonomous test-planning system. You review
a TestPlan against the crawled site model and score how well the plan covers
the application across SIX dimensions:

1. happy_path — does the plan cover the core user journey(s)?
2. auth_session — does the plan exercise login/logout/session behavior?
3. form_validation — does the plan test required fields, patterns, invalid input?
4. error_state — does the plan test 404s, API failures, empty states, server errors?
5. destructive_action — does the plan test delete/remove/cancel flows (with confirmation)?
6. navigation — does the plan verify key pages are reachable?

For each dimension, score it as:
- "covered" — the plan has a flow that meaningfully exercises this dimension
- "partial" — the plan touches it but misses important aspects
- "missing" — the plan has no flow for this dimension

For each dimension, provide a `justifications[dim]` string citing what the
site model actually contains (e.g. "site has a login form but no flow
exercises it" for auth_session=missing).

Compute `overall_score` (0-1) as a weighted average:
- covered = 1.0, partial = 0.5, missing = 0.0

Provide `gaps` as targeted, actionable feedback the Planner can act on
(e.g. "add a flow that fills the login form and submits it"). Only include
gaps for dimensions scored "partial" or "missing". If everything is covered,
leave gaps empty.

Do NOT invent site features that are not in the site model. Base every
justification on what the site model actually shows.
"""


class Critic:
    def review(self, plan: TestPlan, site_model: SiteModel, max_iterations: int) -> CoverageVerdict:
        """Score the plan via a single structured LLM call, then compute the
        decision deterministically from the dimension scores."""
        logger.info(
            "Critic: calling LLM, iteration=%d, flows=%d, max_iterations=%d",
            plan.iteration, len(plan.flows), max_iterations,
        )

        user_prompt = self._build_user_prompt(plan, site_model)
        verdict = call_structured(_SYSTEM_PROMPT, user_prompt, CoverageVerdict)

        # Deterministic decision from the LLM's dimension scores.
        verdict.overall_score = self._compute_overall_score(verdict)
        verdict.decision = self._decide(verdict, plan.iteration, max_iterations)

        logger.info(
            "Critic: decision=%s overall_score=%.2f gaps=%d",
            verdict.decision, verdict.overall_score, len(verdict.gaps),
        )
        return verdict

    @staticmethod
    def _build_user_prompt(plan: TestPlan, site_model: SiteModel) -> str:
        return (
            "SITE MODEL (crawled from the live app):\n"
            f"{serialize_site_model(site_model)}\n\n"
            "TEST PLAN (to be scored):\n"
            f"{serialize_plan(plan)}\n\n"
            "Score each of the six dimensions (happy_path, auth_session, "
            "form_validation, error_state, destructive_action, navigation) as "
            "covered/partial/missing with a justification citing the site model. "
            "Provide gaps for any partial/missing dimension."
        )

    @staticmethod
    def _compute_overall_score(verdict: CoverageVerdict) -> float:
        """Weighted average: covered=1.0, partial=0.5, missing=0.0."""
        weights = {
            "covered": _COVERED_WEIGHT,
            "partial": _PARTIAL_WEIGHT,
            "missing": 0.0,
        }
        scores = [weights.get(v, 0.0) for v in verdict.dimension_scores.values()]
        if not scores:
            return 0.0
        return round(sum(scores) / len(scores), 2)

    @staticmethod
    def _decide(verdict: CoverageVerdict, iteration: int, max_iterations: int) -> str:
        """Deterministic decision rubric.

        - proceed: no dimension is "missing" or "partial" (all covered)
        - re_plan: gaps exist (missing/partial) AND iteration < max_iterations
        - escalate: gaps exist AND iteration >= max_iterations (bounded)
        """
        missing = [d for d, s in verdict.dimension_scores.items() if s == "missing"]
        partial = [d for d, s in verdict.dimension_scores.items() if s == "partial"]

        # No gaps at all -> proceed.
        if not missing and not partial:
            return "proceed"

        # Gaps exist but no re-plan budget left -> escalate.
        if iteration >= max_iterations:
            return "escalate"

        # Gaps exist and we still have iterations -> re_plan.
        return "re_plan"
