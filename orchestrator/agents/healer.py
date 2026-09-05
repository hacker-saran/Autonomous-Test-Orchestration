"""Healer agent: on any non-passing ExecutionResult, gathers evidence and
classifies the failure so the orchestrator knows whether to auto-repair,
report, retry, or escalate.

TODO (team, live at the event):
  - Gather evidence: live selector match count for the failing step, a DOM
    diff against the page at generation time, the network response status
    for any related request, and repeatability on an immediate rerun.
  - Classify per this rubric:
      * 0 selector matches + a semantically similar element found elsewhere
        -> "script_issue": attempt one auto-repair (rewrite the selector in
        the generated test), then rerun once to confirm before reporting.
      * element present but value/text/network response is wrong
        -> "app_defect": never auto-fix, just report with evidence.
      * target region entirely gone with no semantic equivalent
        -> "ambiguous": escalate, don't guess.
      * same failure on rerun with no content/DOM difference and a timeout
        signature -> "flaky_env".
  - `action_taken` should follow the classification: "auto_repaired" only for
    a confirmed script_issue repair, "retried" for flaky_env, "reported" for
    app_defect, "escalated" for ambiguous (or anything confidence is low on).
  - When `action_taken == "auto_repaired"`, populate `repair_diff` with the
    actual selector/code change so the orchestrator can rerun the test.
"""
from __future__ import annotations

import logging

from orchestrator.schemas import ExecutionResult, GeneratedTest, HealerVerdict

logger = logging.getLogger(__name__)


class Healer:
    def heal(self, execution_result: ExecutionResult, generated_test: GeneratedTest | None) -> HealerVerdict | None:
        """Trivial pass-through: returns None for a passing result, otherwise
        always classifies as "ambiguous" and escalates without gathering any
        real evidence. See TODO above for the real classification rubric.
        """
        if execution_result.status == "pass":
            return None

        logger.info("Healer: trivial pass-through, flow=%s status=%s (always escalates)",
                    execution_result.flow_id, execution_result.status)

        return HealerVerdict(
            flow_id=execution_result.flow_id,
            classification="ambiguous",
            confidence=0.0,
            evidence={"note": "stub healer: no evidence gathered yet"},
            action_taken="escalated",
            rationale="Stub healer always escalates without classifying; real rubric is a TODO.",
            repair_diff=None,
        )
