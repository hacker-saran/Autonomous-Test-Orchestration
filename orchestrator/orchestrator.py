"""TestOrchestrator: the state machine driving the whole pipeline.

EXPLORING -> PLANNING -> CRITIQUE -> (loop to PLANNING if re_plan, capped at
MAX_REPLAN_ITERATIONS) -> GENERATING -> EXECUTING -> HEALING -> REPORTING

Implemented as an explicit sequence of method calls, not a heavy framework.
Every phase transition and every critic/healer decision is logged via plain
`logging` — this log is what the demo narrates over.

Any `SchemaValidationError` raised by an agent (once agents actually call
`call_structured`) is caught here and recorded as an escalation in the final
report. It must never crash the pipeline.
"""
from __future__ import annotations

import logging
from pathlib import Path

from orchestrator import live_events
from orchestrator.agents.critic import Critic
from orchestrator.agents.executor import Executor
from orchestrator.agents.generator import Generator
from orchestrator.agents.healer import Healer
from orchestrator.agents.planner import Planner
from orchestrator.agents.reporter import Reporter
from orchestrator.config import get_settings
from orchestrator.crawl.crawler import SiteCrawler
from orchestrator.llm.client import SchemaValidationError
from orchestrator.schemas import CoverageVerdict, FinalReport, GeneratedTest, HealerVerdict, TestPlan

logger = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).resolve().parent / "reports"


class TestOrchestrator:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.crawler = SiteCrawler()
        self.planner = Planner()
        self.critic = Critic()
        self.generator = Generator()
        self.executor = Executor()
        self.healer = Healer()
        self.reporter = Reporter()

    def run(
        self,
        url: str,
        prd_path: str | None = None,
        focus_hint: str | None = None,
        credentials: dict | None = None,
    ) -> FinalReport:
        escalations: list[str] = []
        prd_text = Path(prd_path).read_text(encoding="utf-8") if prd_path else None

        live_events.reset()
        live_events.emit("run_started", url=url, has_prd=prd_text is not None, focus_hint=focus_hint)

        logger.info("PHASE=EXPLORING url=%s", url)
        live_events.emit("phase", phase="EXPLORING", url=url)
        site_model = self.crawler.crawl(
            url,
            credentials=credentials,
            max_depth=self.settings.crawl_max_depth,
            max_pages=self.settings.crawl_max_pages,
            timeout_s=self.settings.crawl_timeout_s,
            on_page=lambda page_info: live_events.emit(
                "page_crawled", url=page_info.url, title=page_info.title,
                forms=len(page_info.forms), buttons=len(page_info.buttons), nav_links=len(page_info.nav_links),
            ),
        )
        live_events.emit("crawl_done", pages=len(site_model.pages), partial=site_model.partial, notes=site_model.notes)
        if site_model.partial:
            escalations.append(f"Crawl returned partial results: {'; '.join(site_model.notes)}")

        plan, verdict = self._plan_and_critique(
            site_model, prd_text, focus_hint, credentials is not None, escalations
        )

        logger.info("PHASE=GENERATING flow_count=%d", len(plan.flows))
        live_events.emit("phase", phase="GENERATING", flow_count=len(plan.flows))
        generated_tests = self._generate(plan, credentials, escalations)

        logger.info("PHASE=EXECUTING test_count=%d", len(generated_tests))
        live_events.emit("phase", phase="EXECUTING", test_count=len(generated_tests))
        execution_results = self.executor.run(
            generated_tests, plan=plan, credentials=credentials,
            on_result=lambda result: live_events.emit(
                "test_executed", flow_id=result.flow_id, status=result.status, duration_ms=result.duration_ms,
                screenshot_url=f"screenshots/{result.flow_id}.png" if result.screenshot_path else None,
            ),
        )

        logger.info("PHASE=HEALING")
        live_events.emit("phase", phase="HEALING")
        healer_verdicts, execution_results = self._heal(
            generated_tests, execution_results, plan, credentials, escalations
        )

        logger.info("PHASE=REPORTING")
        live_events.emit("phase", phase="REPORTING")
        report = self._report(plan, execution_results, healer_verdicts, site_model, prd_text, verdict, escalations)

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        json_path, md_path, html_path = self.reporter.write(
            report, REPORTS_DIR, plan=plan, execution_results=execution_results, site_model=site_model
        )
        logger.info("Report written to %s, %s, and %s", json_path, md_path, html_path)
        live_events.emit(
            "run_finished", pass_count=report.pass_count, fail_count=report.fail_count,
            flows_planned=report.flows_planned, escalations=report.escalations,
        )

        return report

    def _plan_and_critique(
        self,
        site_model,
        prd_text: str | None,
        focus_hint: str | None,
        has_credentials: bool,
        escalations: list[str],
    ) -> tuple[TestPlan, CoverageVerdict | None]:
        iteration = 0
        feedback: list[str] = []
        plan = TestPlan(flows=[], iteration=0)
        verdict: CoverageVerdict | None = None

        while True:
            logger.info("PHASE=PLANNING iteration=%d", iteration)
            live_events.emit("phase", phase="PLANNING", iteration=iteration)
            try:
                plan = self.planner.plan(
                    site_model, prd_text, focus_hint,
                    feedback=feedback, iteration=iteration, has_credentials=has_credentials,
                )
            except SchemaValidationError as exc:
                logger.error("Planner escalation: %s", exc)
                escalations.append(f"Planner failed to produce a valid plan: {exc}")
                live_events.emit("escalation", stage="planner", detail=str(exc))
                break

            live_events.emit(
                "plan_produced", iteration=iteration, flow_count=len(plan.flows),
                categories=sorted({f.category for f in plan.flows}),
            )

            logger.info("PHASE=CRITIQUE iteration=%d", iteration)
            live_events.emit("phase", phase="CRITIQUE", iteration=iteration)
            try:
                verdict = self.critic.review(plan, site_model, max_iterations=self.settings.max_replan_iterations)
            except SchemaValidationError as exc:
                logger.error("Critic escalation: %s", exc)
                escalations.append(f"Critic failed to produce a valid verdict: {exc}")
                live_events.emit("escalation", stage="critic", detail=str(exc))
                break

            logger.info("Critic decision=%s overall_score=%.2f", verdict.decision, verdict.overall_score)
            live_events.emit(
                "critic_verdict", iteration=iteration, decision=verdict.decision,
                overall_score=verdict.overall_score, gaps=verdict.gaps,
                dimension_scores=verdict.dimension_scores,
            )

            if verdict.decision == "proceed":
                break
            if verdict.decision == "escalate" or iteration >= self.settings.max_replan_iterations:
                escalations.append(
                    f"Coverage critic escalated after {iteration} re-plan iteration(s): {verdict.gaps}"
                )
                break

            feedback = verdict.gaps
            iteration += 1

        return plan, verdict

    def _generate(
        self, plan: TestPlan, credentials: dict | None, escalations: list[str]
    ) -> list[GeneratedTest]:
        # auth_session first: it's the only flow that captures storage_state,
        # which every other flow's live resolution then reuses to see
        # authenticated-only pages/elements.
        ordered_flows = sorted(plan.flows, key=lambda f: 0 if f.category == "auth_session" else 1)

        generated_tests: list[GeneratedTest] = []
        for flow in ordered_flows:
            try:
                gt = self.generator.generate(flow, credentials=credentials)
                generated_tests.append(gt)
                live_events.emit(
                    "test_generated", flow_id=gt.flow_id, category=flow.category,
                    title=flow.title, validation_status=gt.validation_status,
                    file_path=gt.file_path, command=f"pytest {gt.file_path} -q",
                    steps=[
                        {
                            "action": s.action, "target_description": s.target_description,
                            "value": s.value, "expected_outcome": s.expected_outcome,
                        }
                        for s in flow.steps
                    ],
                )
            except SchemaValidationError as exc:
                logger.error("Generator escalation for flow %s: %s", flow.flow_id, exc)
                escalations.append(f"Generator failed for flow {flow.flow_id}: {exc}")
                live_events.emit("escalation", stage="generator", flow_id=flow.flow_id, detail=str(exc))
        return generated_tests

    def _heal(self, generated_tests, execution_results, plan, credentials, escalations: list[str]):
        gt_by_flow = {gt.flow_id: gt for gt in generated_tests}
        healer_verdicts: list[HealerVerdict] = []
        results_by_flow = {r.flow_id: r for r in execution_results}

        for result in list(execution_results):
            if result.status == "pass":
                continue
            try:
                verdict = self.healer.heal(result, gt_by_flow.get(result.flow_id))
            except SchemaValidationError as exc:
                logger.error("Healer escalation for flow %s: %s", result.flow_id, exc)
                escalations.append(f"Healer failed for flow {result.flow_id}: {exc}")
                live_events.emit("escalation", stage="healer", flow_id=result.flow_id, detail=str(exc))
                continue

            if verdict is None:
                continue
            healer_verdicts.append(verdict)
            logger.info(
                "Healer flow=%s classification=%s action=%s",
                verdict.flow_id, verdict.classification, verdict.action_taken,
            )
            live_events.emit(
                "healer_verdict", flow_id=verdict.flow_id, classification=verdict.classification,
                confidence=verdict.confidence, action_taken=verdict.action_taken, rationale=verdict.rationale,
            )

            if verdict.action_taken == "auto_repaired":
                gt = gt_by_flow.get(result.flow_id)
                if gt is not None:
                    logger.info("PHASE=HEALING rerun flow=%s", verdict.flow_id)
                    rerun = self.executor.run([gt], plan=plan, credentials=credentials)
                    if rerun:
                        results_by_flow[verdict.flow_id] = rerun[0]

        return healer_verdicts, list(results_by_flow.values())

    def _report(
        self,
        plan: TestPlan,
        execution_results,
        healer_verdicts,
        site_model,
        prd_text: str | None,
        verdict: CoverageVerdict | None,
        escalations: list[str],
    ) -> FinalReport:
        try:
            report = self.reporter.build_report(
                plan, execution_results, healer_verdicts, site_model, prd_text=prd_text
            )
        except SchemaValidationError as exc:
            logger.error("Reporter escalation: %s", exc)
            escalations.append(f"Reporter failed to build final report: {exc}")
            report = FinalReport(
                flows_planned=len(plan.flows),
                flows_by_category={},
                pass_count=0,
                fail_count=0,
                healer_actions=healer_verdicts,
                coverage_gaps_remaining=[],
                untested_flow_risk=[],
                escalations=[],
            )

        if verdict is not None:
            report.coverage_gaps_remaining = verdict.gaps
        report.escalations = list(dict.fromkeys(report.escalations + escalations))

        return report
