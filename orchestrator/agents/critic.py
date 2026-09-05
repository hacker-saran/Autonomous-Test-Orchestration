"""Coverage critic agent: scores a TestPlan against the six Flow.category
dimensions and decides whether to proceed, ask the Planner to re-plan, or
escalate.

TODO (team, live at the event):
  - Replace the pass-through below with a `call_structured()` call to
    LLM_MODEL_PRIMARY, forcing the `CoverageVerdict` tool schema.
  - Score each of the six dimensions (happy_path, auth_session,
    form_validation, error_state, destructive_action, navigation) as
    covered/partial/missing, with a `justifications[dim]` string citing what
    the `SiteModel` actually contains (e.g. "site has a login form but no
    flow exercises it" for auth_session=missing).
  - Compute `overall_score` (0-1) from the dimension scores.
  - Decision rubric: `proceed` if coverage is acceptable; `re_plan` with
    targeted `gaps` feedback if it's fixable and `iteration < max_iterations`;
    `escalate` if `iteration >= max_iterations` (bounded — never loop
    forever) or the gaps aren't fixable by re-planning alone.
"""
from __future__ import annotations

import logging

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


class Critic:
    def review(self, plan: TestPlan, site_model: SiteModel, max_iterations: int) -> CoverageVerdict:
        """Trivial pass-through: always returns decision="proceed" so the
        pipeline runs end to end immediately. See TODO above for the real
        scoring rubric.
        """
        logger.info(
            "Critic: trivial pass-through review, iteration=%d, flows=%d (always proceeds)",
            plan.iteration, len(plan.flows),
        )

        return CoverageVerdict(
            dimension_scores={category: "partial" for category in CATEGORIES},
            justifications={category: "stub critic: not yet scored against SiteModel" for category in CATEGORIES},
            overall_score=1.0,
            gaps=[],
            decision="proceed",
        )
