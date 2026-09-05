"""Reporter agent: joins plan/execution/healer output into a FinalReport and
writes it to disk (JSON + Markdown summary + an HTML pipeline graph).

`coverage_gaps_remaining` is intentionally left `[]` by `build_report` — the
orchestrator overwrites it with the last CoverageVerdict.gaps after this
call, since the critic's verdict isn't itself part of this agent's inputs.

TODO (team, live at the event):
  - `prd_gap_analysis` maps requirements to whichever flow's title/category
    plausibly covers them — it doesn't check the flow actually *passed*, so
    a requirement can show "covered" by a flow that failed. Consider cross-
    referencing execution_results for a sharper signal.
"""
from __future__ import annotations

import html
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.llm.client import SchemaValidationError, call_structured
from orchestrator.schemas import (
    ExecutionResult, FinalReport, HealerVerdict, PRDGapAnalysis, SiteModel, TestPlan,
)

logger = logging.getLogger(__name__)

_PRD_SYSTEM_PROMPT = """You are analyzing a Product Requirements Document (PRD)
against the test flows that were actually planned, to identify coverage gaps.

Extract every atomic, testable requirement statement from the PRD text — one
requirement per distinct capability or behavior described; split compound
sentences into separate requirements rather than merging them.

For each requirement, decide whether any of the given planned flows
plausibly exercises it, based only on that flow's title/category — ground
every judgment in the flows actually given, never assume coverage that isn't
evident. If one does, set `covering_flow_id` to that flow's flow_id and
`status` to "covered". If none does, leave `covering_flow_id` null and set
`status` to "not_covered".
"""

_STATUS_COLORS = {
    "pass": "#2ecc71",
    "fail": "#e74c3c",
    "error": "#f39c12",
    "no_test": "#94a3b8",
}


class Reporter:
    def build_report(
        self,
        plan: TestPlan,
        execution_results: list[ExecutionResult],
        healer_verdicts: list[HealerVerdict],
        site_model: SiteModel,
        prd_text: str | None = None,
    ) -> FinalReport:
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

        untested_flow_risk = _compute_untested_flow_risk(plan, execution_results)
        prd_gap_analysis = _build_prd_gap_analysis(prd_text, plan) if prd_text else None

        logger.info(
            "Reporter: flows_planned=%d pass=%d fail=%d untested_flow_risk=%d prd_requirements=%s",
            len(plan.flows), pass_count, fail_count, len(untested_flow_risk),
            len(prd_gap_analysis) if prd_gap_analysis else 0,
        )

        return FinalReport(
            flows_planned=len(plan.flows),
            flows_by_category=flows_by_category,
            pass_count=pass_count,
            fail_count=fail_count,
            healer_actions=healer_verdicts,
            coverage_gaps_remaining=[],
            untested_flow_risk=untested_flow_risk,
            prd_gap_analysis=prd_gap_analysis,
            escalations=escalations,
        )

    def write(
        self,
        report: FinalReport,
        reports_dir: Path,
        plan: TestPlan | None = None,
        execution_results: list[ExecutionResult] | None = None,
        site_model: SiteModel | None = None,
    ) -> tuple[Path, Path, Path | None]:
        """Writes the report as JSON, a short Markdown summary, and — when the
        pipeline objects needed to draw it are supplied — an HTML pipeline
        graph (crawled pages -> planned flows, colored by execution status)
        with the detailed log sections beneath it.
        """
        reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        json_path = reports_dir / f"{timestamp}.json"
        json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

        md_path = reports_dir / f"{timestamp}.md"
        md_path.write_text(self._to_markdown(report), encoding="utf-8")

        html_path = None
        if plan is not None and execution_results is not None and site_model is not None:
            html_path = reports_dir / f"{timestamp}.html"
            html_path.write_text(
                self._to_html(report, plan, execution_results, site_model), encoding="utf-8"
            )

        return json_path, md_path, html_path

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

    def _to_html(
        self,
        report: FinalReport,
        plan: TestPlan,
        execution_results: list[ExecutionResult],
        site_model: SiteModel,
    ) -> str:
        graph_svg = _build_pipeline_graph_svg(plan, execution_results, report.healer_actions, site_model)
        legend_items = "".join(
            f'<span class="legend-item"><span class="swatch" style="background:{color}"></span>{status}</span>'
            for status, color in _STATUS_COLORS.items()
        )
        healer_rows = "".join(
            f"<tr><td>{html.escape(v.flow_id)}</td><td>{html.escape(v.classification)}</td>"
            f"<td>{html.escape(v.action_taken)}</td><td>{v.confidence:.2f}</td>"
            f"<td>{html.escape(v.rationale)}</td></tr>"
            for v in report.healer_actions
        ) or '<tr><td colspan="5">none</td></tr>'

        return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Test Orchestration Pipeline Report</title>
<style>
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; margin: 0; padding: 24px;
          background: #f8fafc; color: #1e293b; }}
  h1 {{ font-size: 20px; margin-bottom: 4px; }}
  h2 {{ font-size: 15px; margin-top: 28px; border-bottom: 1px solid #d0d7e2; padding-bottom: 4px; }}
  .summary {{ display: flex; gap: 20px; margin: 12px 0 20px; flex-wrap: wrap; }}
  .stat {{ background: #fff; border: 1px solid #d0d7e2; border-radius: 8px; padding: 10px 16px; }}
  .stat .value {{ font-size: 20px; font-weight: 600; }}
  .stat .label {{ font-size: 11px; color: #64748b; }}
  .legend {{ margin: 8px 0 16px; font-size: 12px; }}
  .legend-item {{ margin-right: 16px; }}
  .swatch {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; }}
  .graph-wrap {{ background: #fff; border: 1px solid #d0d7e2; border-radius: 8px; padding: 12px; overflow-x: auto; }}
  ul {{ margin: 4px 0; padding-left: 20px; font-size: 13px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
  th, td {{ border: 1px solid #d0d7e2; padding: 6px 8px; text-align: left; vertical-align: top; }}
  th {{ background: #eef2f7; }}
</style>
</head>
<body>
<h1>Test Orchestration Pipeline Report</h1>
<div class="summary">
  <div class="stat"><div class="value">{report.flows_planned}</div><div class="label">flows planned</div></div>
  <div class="stat"><div class="value">{report.pass_count}</div><div class="label">passed</div></div>
  <div class="stat"><div class="value">{report.fail_count}</div><div class="label">failed</div></div>
  <div class="stat"><div class="value">{len(site_model.pages)}</div><div class="label">pages crawled</div></div>
</div>

<h2>Pipeline graph — crawled pages &rarr; planned flows</h2>
<div class="legend">{legend_items}</div>
<div class="graph-wrap">{graph_svg}</div>

<h2>Healer actions</h2>
<table>
<thead><tr><th>flow_id</th><th>classification</th><th>action</th><th>confidence</th><th>rationale</th></tr></thead>
<tbody>{healer_rows}</tbody>
</table>

<h2>Coverage gaps remaining</h2>
<ul>{_list_html(report.coverage_gaps_remaining)}</ul>

<h2>Untested flow risk</h2>
<ul>{_list_html(report.untested_flow_risk)}</ul>

<h2>Escalations</h2>
<ul>{_list_html(report.escalations)}</ul>
</body>
</html>
"""


def _list_html(items: list[str]) -> str:
    if not items:
        return "<li>none</li>"
    return "".join(f"<li>{html.escape(str(item))}</li>" for item in items)


def _compute_untested_flow_risk(plan: TestPlan, execution_results: list[ExecutionResult]) -> list[str]:
    status_by_flow = {r.flow_id: r.status for r in execution_results}
    risks = []
    for flow in plan.flows:
        status = status_by_flow.get(flow.flow_id)
        if status is None:
            risks.append(
                f"{flow.flow_id} [{flow.category}] {flow.title!r}: no execution result "
                f"(Generator likely failed for this flow)"
            )
        elif status != "pass":
            risks.append(f"{flow.flow_id} [{flow.category}] {flow.title!r}: did not pass (status={status})")
    return risks


def _build_prd_gap_analysis(prd_text: str, plan: TestPlan) -> list[dict]:
    flows_desc = "\n".join(f"- {flow.flow_id} [{flow.category}]: {flow.title}" for flow in plan.flows)
    user_prompt = f"PRD text:\n{prd_text}\n\nPlanned flows:\n{flows_desc}"
    try:
        analysis = call_structured(_PRD_SYSTEM_PROMPT, user_prompt, PRDGapAnalysis)
    except SchemaValidationError as exc:
        logger.warning("Reporter: PRD gap analysis failed: %s", exc)
        return [{"error": f"PRD gap analysis failed: {exc}"}]
    return [r.model_dump() for r in analysis.requirements]


def _wrap(text: str, max_len: int) -> str:
    text = str(text)
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _build_pipeline_graph_svg(
    plan: TestPlan,
    execution_results: list[ExecutionResult],
    healer_verdicts: list[HealerVerdict],
    site_model: SiteModel,
) -> str:
    """A simple bipartite node-link diagram: crawled pages on the left, planned
    flows on the right (colored by execution status), connected by an edge
    when a flow's first `navigate` step targets that page. Pure SVG, no JS/CDN
    dependency, so it renders offline in any browser.
    """
    pages = site_model.pages
    flows = plan.flows
    healer_by_flow = {v.flow_id: v for v in healer_verdicts}
    status_by_flow = {r.flow_id: r.status for r in execution_results}

    row_h = 46
    top_margin = 20
    node_w, node_h = 280, 32
    left_x, right_x = 20, 680
    width = 980
    height = top_margin + max(len(pages), len(flows), 1) * row_h + 20

    def node_y(i: int) -> int:
        return top_margin + i * row_h

    page_index_by_url = {page.url: i for i, page in enumerate(pages)}
    edges: list[tuple[int, int]] = []
    for fi, flow in enumerate(flows):
        nav_step = next((s for s in flow.steps if s.action == "navigate" and s.value), None)
        if nav_step and nav_step.value in page_index_by_url:
            edges.append((page_index_by_url[nav_step.value], fi))

    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" xmlns="http://www.w3.org/2000/svg" '
        f'font-family="Segoe UI, system-ui, sans-serif" font-size="12">'
    ]

    for pi, fi in edges:
        x1, y1 = left_x + node_w, node_y(pi) + node_h / 2
        x2, y2 = right_x, node_y(fi) + node_h / 2
        mid_x = (x1 + x2) / 2
        parts.append(
            f'<path d="M {x1} {y1} C {mid_x} {y1}, {mid_x} {y2}, {x2} {y2}" '
            f'stroke="#b0b6c0" stroke-width="1.5" fill="none"/>'
        )

    for i, page in enumerate(pages):
        y = node_y(i)
        label = _wrap(page.title or page.url, 36)
        parts.append(
            f'<rect x="{left_x}" y="{y}" width="{node_w}" height="{node_h}" rx="6" '
            f'fill="#eef2f7" stroke="#94a3b8"><title>{html.escape(page.url)}</title></rect>'
            f'<text x="{left_x + 10}" y="{y + node_h / 2 + 4}" fill="#1e293b">{html.escape(label)}</text>'
        )

    for i, flow in enumerate(flows):
        y = node_y(i)
        status = status_by_flow.get(flow.flow_id, "no_test")
        color = _STATUS_COLORS.get(status, "#94a3b8")
        label = _wrap(f"[{flow.category}] {flow.title}", 40)
        tooltip_lines = [
            f"flow_id={flow.flow_id}", f"priority={flow.priority}",
            f"source={flow.source}", f"status={status}",
        ]
        verdict = healer_by_flow.get(flow.flow_id)
        if verdict:
            tooltip_lines.append(f"healer={verdict.classification}->{verdict.action_taken}")
        tooltip = "\n".join(tooltip_lines)
        parts.append(
            f'<rect x="{right_x}" y="{y}" width="{node_w}" height="{node_h}" rx="6" '
            f'fill="{color}" fill-opacity="0.18" stroke="{color}" stroke-width="2">'
            f'<title>{html.escape(tooltip)}</title></rect>'
            f'<text x="{right_x + 10}" y="{y + node_h / 2 + 4}" fill="#1e293b">{html.escape(label)}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)
