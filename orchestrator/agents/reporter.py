"""Reporter agent: joins plan/execution/healer output into a FinalReport and
writes it to disk.

TODO (team, live at the event):
  - Join everything by `flow_id`: for each planned flow, resolve its final
    pass/fail status (after any healer-triggered rerun) and roll that up into
    `flows_by_category` / `pass_count` / `fail_count`.
  - `untested_flow_risk`: flows the Planner/Critic flagged as important
    (e.g. high `risk_tag`, or dimensions scored "missing"/"partial" by the
    Critic) that never got a passing execution — surface these explicitly so
    a human sees what's still unverified.
  - `coverage_gaps_remaining`: carry forward the last CoverageVerdict.gaps
    that were never resolved by a re-plan.
  - If a PRD was provided, add `prd_gap_analysis`: extract atomic requirement
    statements from `prd_text` (likely another `call_structured` call) and
    map each one to a covering flow_id or "not covered".
  - Consider using `call_structured` for a narrative rollup, but keep the
    numeric fields on FinalReport computed deterministically from the other
    agents' output, not invented by an LLM.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.schemas import ExecutionResult, FinalReport, HealerVerdict, SiteModel, TestPlan

logger = logging.getLogger(__name__)


class Reporter:
    def build_report(
        self,
        plan: TestPlan,
        execution_results: list[ExecutionResult],
        healer_verdicts: list[HealerVerdict],
        site_model: SiteModel,
        prd_text: str | None = None,
    ) -> FinalReport:
        """Trivial pass-through: deterministic tallies only, no PRD gap
        analysis and no untested-flow-risk detection yet. See TODO above.
        """
        flows_by_category: dict[str, int] = {}
        for flow in plan.flows:
            flows_by_category[flow.category] = flows_by_category.get(flow.category, 0) + 1

        pass_count = sum(1 for r in execution_results if r.status == "pass")
        fail_count = sum(1 for r in execution_results if r.status != "pass")
        escalations = [
            f"flow={v.flow_id} classification={v.classification}: {v.rationale}"
            for v in healer_verdicts
            if v.action_taken == "escalated"
        ]

        prd_gap_analysis = None
        if prd_text:
            prd_gap_analysis = [{"note": "stub reporter: PRD gap analysis not implemented yet"}]

        logger.info(
            "Reporter: trivial pass-through report, flows_planned=%d pass=%d fail=%d",
            len(plan.flows), pass_count, fail_count,
        )

        return FinalReport(
            flows_planned=len(plan.flows),
            flows_by_category=flows_by_category,
            pass_count=pass_count,
            fail_count=fail_count,
            healer_actions=healer_verdicts,
            coverage_gaps_remaining=[],
            untested_flow_risk=[],
            prd_gap_analysis=prd_gap_analysis,
            escalations=escalations,
        )

    def write(self, report: FinalReport, reports_dir: Path) -> tuple[Path, Path]:
        """Writes the report as JSON plus a short markdown summary next to it."""
        reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        json_path = reports_dir / f"{timestamp}.json"
        json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

        md_path = reports_dir / f"{timestamp}.md"
        md_path.write_text(self._to_markdown(report), encoding="utf-8")

        return json_path, md_path

    @staticmethod
    def _to_markdown(report: FinalReport) -> str:
        lines = [
            "# Test Orchestration Report",
            "",
            f"- Flows planned: {report.flows_planned}",
            f"- Pass / Fail: {report.pass_count} / {report.fail_count}",
            f"- Flows by category: {json.dumps(report.flows_by_category)}",
            "",
            "## Healer actions",
        ]
        if report.healer_actions:
            for verdict in report.healer_actions:
                lines.append(
                    f"- `{verdict.flow_id}`: {verdict.classification} -> {verdict.action_taken} "
                    f"(confidence={verdict.confidence:.2f}) — {verdict.rationale}"
                )
        else:
            lines.append("- none")

        lines += ["", "## Coverage gaps remaining"]
        lines += [f"- {gap}" for gap in report.coverage_gaps_remaining] or ["- none"]

        lines += ["", "## Untested flow risk"]
        lines += [f"- {risk}" for risk in report.untested_flow_risk] or ["- none"]

        lines += ["", "## Escalations"]
        lines += [f"- {escalation}" for escalation in report.escalations] or ["- none"]

        return "\n".join(lines) + "\n"
