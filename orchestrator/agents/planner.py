"""Planner agent: synthesizes a TestPlan from the crawled SiteModel (+ optional
PRD text + focus hint).

TODO (team, live at the event):
  - Replace the pass-through below with a single `call_structured()` call to
    SARVAM_MODEL_PRIMARY, forcing the `TestPlan` tool schema
    (see orchestrator/llm/client.py).
  - Prompt with: site_model (pages/forms/nav_links/buttons), prd_text (if
    any), focus_hint (if any), and `feedback` (the critic's `gaps` list on a
    re-plan iteration).
  - Synthesize flows against the SAME six `Flow.category` values the Critic
    scores against, so planning and scoring share one taxonomy.
  - One call for the whole plan, not one call per flow.
  - Weight `focus_hint` and PRD-derived flows higher when present; tag their
    `source` as "user_hint" / "prd" respectively instead of "crawl".
"""
from __future__ import annotations

import logging

from orchestrator.schemas import Flow, FlowStep, SiteModel, TestPlan

logger = logging.getLogger(__name__)


class Planner:
    def plan(
        self,
        site_model: SiteModel,
        prd_text: str | None = None,
        focus_hint: str | None = None,
        feedback: list[str] | None = None,
        iteration: int = 0,
    ) -> TestPlan:
        """Trivial pass-through: emits one `navigation` flow per crawled page
        so the pipeline runs end to end immediately. Ignores prd_text,
        focus_hint, and feedback entirely — see TODO above.
        """
        logger.info(
            "Planner: trivial pass-through plan, iteration=%d, pages=%d, feedback=%s",
            iteration, len(site_model.pages), feedback or [],
        )

        flows: list[Flow] = []
        for i, page in enumerate(site_model.pages):
            flows.append(
                Flow(
                    flow_id=f"flow-{i}",
                    title=f"Visit {page.title or page.url}",
                    category="navigation",
                    priority="happy",
                    steps=[
                        FlowStep(
                            step_id=f"flow-{i}-step-1",
                            action="navigate",
                            target_description=page.url,
                            value=page.url,
                            expected_outcome=f"Page loads: {page.title or page.url}",
                        ),
                        FlowStep(
                            step_id=f"flow-{i}-step-2",
                            action="assert_visible",
                            target_description="main page content",
                        ),
                    ],
                    source="crawl",
                )
            )

        return TestPlan(flows=flows, iteration=iteration)
