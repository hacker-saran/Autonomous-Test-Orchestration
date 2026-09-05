"""Healer agent: on any non-passing ExecutionResult, gathers evidence and
classifies the failure so the orchestrator knows whether to repair, report,
retry, or escalate.

Auto-repair (script_issue only, per the classification rubric below): reuses
Generator's LLM-feedback re-resolution (see agents/generator.py) by simply
regenerating the whole flow — the now-improved resolution may succeed where
the original heuristic-only pass didn't — then reruns once to confirm before
ever claiming "auto_repaired". If the rerun doesn't pass, the attempt is
reported, not claimed as a fix.

TODO (team, live at the event):
  - Repair regenerates the whole flow rather than surgically patching just
    the failing line. Simpler and safer (never touches steps that were
    already fine) at the cost of redoing resolution work that didn't need
    fixing.
  - Evidence gathering here is deterministic (validation_status, network/
    console errors already captured by Executor, one rerun for repeatability)
    — it does not re-query the live page for a fresh selector match count or
    a DOM diff against generation time. Consider adding that for a sharper
    script_issue vs. app_defect signal when the evidence below is ambiguous.
"""
from __future__ import annotations

import difflib
import json
import logging
from pathlib import Path

from orchestrator.agents.executor import Executor
from orchestrator.agents.generator import GENERATED_TESTS_DIR, Generator
from orchestrator.llm.client import call_structured
from orchestrator.schemas import ExecutionResult, Flow, GeneratedTest, HealerVerdict

logger = logging.getLogger(__name__)

_ACTION_BY_CLASSIFICATION = {
    "script_issue": "reported",  # overridden to "auto_repaired" if a repair attempt is confirmed
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

Still fill every field the schema requires (including `action_taken` and
`repair_diff`) since the tool call is forced, but expect your `action_taken`
and `repair_diff` to be overridden by the caller based on whether an actual
repair attempt is confirmed — focus your effort on `classification`,
`confidence`, and a `rationale` that cites the specific evidence you used.
"""


class Healer:
    def __init__(self) -> None:
        self._executor = Executor()
        self._generator = Generator()

    def heal(
        self,
        execution_result: ExecutionResult,
        generated_test: GeneratedTest | None,
        flow: Flow | None = None,
        credentials: dict | None = None,
        start_url: str | None = None,
    ) -> HealerVerdict | None:
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

        action_taken = _ACTION_BY_CLASSIFICATION.get(verdict.classification, "escalated")
        repair_diff = None

        if verdict.classification == "script_issue" and flow is not None:
            repair = self._attempt_repair(flow, credentials, start_url)
            if repair is not None:
                action_taken = "auto_repaired"
                repair_diff = repair
                evidence["repair_confirmed"] = True
            else:
                evidence["repair_confirmed"] = False

        # Deterministic override: the model's classification/confidence/
        # rationale are trusted, but flow_id/action_taken/evidence/repair_diff
        # are ours to guarantee — the model has no repair capability to
        # legitimately claim, and evidence should be exactly what we gathered,
        # not a re-summarized (and possibly altered) echo of it.
        return verdict.model_copy(
            update={
                "flow_id": execution_result.flow_id,
                "action_taken": action_taken,
                "evidence": evidence,
                "repair_diff": repair_diff,
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

    def _attempt_repair(self, flow: Flow, credentials: dict | None, start_url: str | None = None) -> str | None:
        """Regenerates the flow (benefiting from Generator's LLM-feedback
        retry, which may resolve steps the original pass missed) and reruns
        once. Returns a unified diff only if the rerun actually passes —
        never claims a repair that wasn't confirmed.
        """
        file_path = self._file_path_for(flow)
        old_content = file_path.read_text(encoding="utf-8") if file_path.exists() else ""

        try:
            new_gt = self._generator.generate(flow, credentials=credentials, start_url=start_url)
        except Exception as exc:  # noqa: BLE001 - a failed repair attempt is not a crash
            logger.warning("Healer: repair regeneration failed for flow %s: %s", flow.flow_id, exc)
            return None

        new_content = Path(new_gt.file_path).read_text(encoding="utf-8") if Path(new_gt.file_path).exists() else ""
        if new_content == old_content:
            logger.info("Healer: repair regeneration for flow %s produced no change", flow.flow_id)
            return None

        rerun_results = self._executor.run([new_gt])
        rerun_result = rerun_results[0] if rerun_results else None
        if rerun_result is None or rerun_result.status != "pass":
            logger.info(
                "Healer: repair regeneration for flow %s changed the file but rerun still %s",
                flow.flow_id, rerun_result.status if rerun_result else "produced no result",
            )
            return None

        logger.info("Healer: repair confirmed for flow %s (rerun passed)", flow.flow_id)
        return "\n".join(
            difflib.unified_diff(
                old_content.splitlines(), new_content.splitlines(),
                fromfile="before", tofile="after", lineterm="",
            )
        )

    @staticmethod
    def _file_path_for(flow: Flow) -> Path:
        return GENERATED_TESTS_DIR / f"test_{flow.flow_id}.py"


def _truncate(text: str | None, max_len: int = 1500) -> str | None:
    if text is None:
        return None
    return text if len(text) <= max_len else text[:max_len] + "…"
