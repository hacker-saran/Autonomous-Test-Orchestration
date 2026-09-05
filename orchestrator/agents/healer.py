"""Healer agent: on any non-passing ExecutionResult, gathers evidence and
classifies the failure so the orchestrator knows whether to report, retry,
or escalate.

TODO (team, live at the event):
  - Real auto-repair is not implemented: a `script_issue` classification is
    reported with evidence, not fixed. Building it means re-invoking
    Generator's live selector resolution for just the failing step (with the
    failure as feedback) and rewriting that line in the generated file, then
    rerunning to confirm — only then should `action_taken` become
    "auto_repaired" and `repair_diff` be populated. Until then this Healer
    always maps script_issue -> "reported", never "auto_repaired".
  - Evidence gathering here is deterministic (validation_status, network/
    console errors already captured by Executor, one rerun for repeatability)
    — it does not re-query the live page for a fresh selector match count or
    a DOM diff against generation time. Consider adding that for a sharper
    script_issue vs. app_defect signal when the evidence below is ambiguous.
"""
from __future__ import annotations

import json
import logging

from orchestrator.agents.executor import Executor
from orchestrator.llm.client import call_structured
from orchestrator.schemas import ExecutionResult, GeneratedTest, HealerVerdict

logger = logging.getLogger(__name__)

_ACTION_BY_CLASSIFICATION = {
    "script_issue": "reported",
    "app_defect": "reported",
    "ambiguous": "escalated",
    "flaky_env": "retried",
}

SYSTEM_PROMPT = """You are the Healer in an autonomous QA test-orchestration pipeline.
A generated test just failed or errored. Classify WHY, using exactly this
rubric, based only on the evidence given — never guess beyond it:

- script_issue: the test's own steps/selectors are likely stale, not the app.
  Typical evidence: `generated_test_validation_status` is "unresolved" (a
  selector never resolved even at generation time), or the failure message
  indicates a locator/selector was not found, with no corroborating
  network_errors suggesting a backend problem.
- app_defect: the selectors were fine (`generated_test_validation_status` is
  "validated") but the application itself returned a wrong value, wrong
  response, or a visible error. Typical evidence: a network_errors entry with
  a 4xx/5xx status or a request still pending when the test ended, tied to
  this flow, or an assertion mismatch between expected and actual content.
- ambiguous: there is not enough evidence to confidently pick script_issue or
  app_defect (e.g. validated selectors, no network errors, unclear failure).
  Escalate rather than guess.
- flaky_env: `same_error_on_rerun` is false (the rerun behaved differently —
  e.g. it passed) — the original failure was likely a timing/environment
  fluke, not a real defect. Only pick this when the rerun's outcome actually
  differs from the original.

Important: there is no automatic selector-repair capability in this pipeline
yet. Still fill every field the schema requires (including `action_taken` and
`repair_diff`) since the tool call is forced, but expect your `action_taken`
and `repair_diff` to be overridden by the caller — focus your effort on
`classification`, `confidence`, and a `rationale` that cites the specific
evidence you used.
"""


class Healer:
    def __init__(self) -> None:
        self._executor = Executor()

    def heal(self, execution_result: ExecutionResult, generated_test: GeneratedTest | None) -> HealerVerdict | None:
        if execution_result.status == "pass":
            return None

        rerun_result = self._rerun(generated_test)
        same_error_on_rerun = (
            rerun_result is not None
            and rerun_result.status == execution_result.status
            and (rerun_result.error_message or "") == (execution_result.error_message or "")
        )

        evidence = {
            "original_status": execution_result.status,
            "original_error_message": _truncate(execution_result.error_message),
            "generated_test_validation_status": generated_test.validation_status if generated_test else "unknown",
            "console_errors": execution_result.console_errors,
            "network_errors": execution_result.network_errors,
            "rerun_status": rerun_result.status if rerun_result else None,
            "rerun_error_message": _truncate(rerun_result.error_message) if rerun_result else None,
            "same_error_on_rerun": same_error_on_rerun,
        }

        logger.info(
            "Healer: classifying flow=%s (validation_status=%s, rerun_status=%s, same_error_on_rerun=%s)",
            execution_result.flow_id, evidence["generated_test_validation_status"],
            evidence["rerun_status"], same_error_on_rerun,
        )

        verdict = call_structured(SYSTEM_PROMPT, json.dumps(evidence, indent=2), HealerVerdict)

        # Deterministic override: the model's classification/confidence/
        # rationale are trusted, but flow_id/action_taken/evidence/repair_diff
        # are ours to guarantee — the model has no repair capability to
        # legitimately claim, and evidence should be exactly what we gathered,
        # not a re-summarized (and possibly altered) echo of it.
        return verdict.model_copy(
            update={
                "flow_id": execution_result.flow_id,
                "action_taken": _ACTION_BY_CLASSIFICATION.get(verdict.classification, "escalated"),
                "evidence": evidence,
                "repair_diff": None,
            }
        )

    def _rerun(self, generated_test: GeneratedTest | None) -> ExecutionResult | None:
        if generated_test is None:
            return None
        try:
            results = self._executor.run([generated_test])
        except Exception as exc:  # noqa: BLE001 - a failed rerun attempt is evidence, not a crash
            logger.warning("Healer: rerun failed for flow %s: %s", generated_test.flow_id, exc)
            return None
        return results[0] if results else None


def _truncate(text: str | None, max_len: int = 1500) -> str | None:
    if text is None:
        return None
    return text if len(text) <= max_len else text[:max_len] + "…"
