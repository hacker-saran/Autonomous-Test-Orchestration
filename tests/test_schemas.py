"""Round-trip validation tests for every Pydantic model in orchestrator/schemas.py.

Each test builds a minimal valid instance, dumps it to JSON, and re-validates
it from that JSON — catching schema drift (e.g. a renamed/typo'd field) early.
"""
from __future__ import annotations

from orchestrator.schemas import (
    ButtonInfo,
    CoverageVerdict,
    ExecutionResult,
    FinalReport,
    Flow,
    FlowStep,
    FormFieldInfo,
    FormInfo,
    GeneratedTest,
    HealerVerdict,
    LinkInfo,
    PageInfo,
    PRDGapAnalysis,
    PRDRequirement,
    SelectorSuggestion,
    SiteModel,
    TestPlan,
)


def _round_trip(model):
    dumped = model.model_dump_json()
    return type(model).model_validate_json(dumped)


def test_flow_step_round_trip():
    step = FlowStep(
        step_id="s1",
        action="click",
        target_description="Submit button",
        value=None,
        expected_outcome="Form submits",
    )
    assert _round_trip(step) == step


def test_flow_round_trip():
    flow = Flow(
        flow_id="f1",
        title="Login happy path",
        category="auth_session",
        priority="critical",
        preconditions=["user exists"],
        steps=[
            FlowStep(step_id="f1-1", action="navigate", target_description="/login", value="/login"),
            FlowStep(step_id="f1-2", action="fill", target_description="email field", value="a@b.com"),
        ],
        risk_tag="auth",
        source="crawl",
    )
    assert _round_trip(flow) == flow


def test_test_plan_round_trip():
    plan = TestPlan(
        flows=[
            Flow(
                flow_id="f1",
                title="Home page loads",
                category="navigation",
                priority="happy",
                steps=[FlowStep(step_id="f1-1", action="navigate", target_description="/")],
            )
        ],
        iteration=1,
    )
    assert _round_trip(plan) == plan


def test_coverage_verdict_round_trip():
    verdict = CoverageVerdict(
        dimension_scores={"happy_path": "covered", "auth_session": "missing"},
        justifications={"happy_path": "covered by flow-0", "auth_session": "no login flow present"},
        overall_score=0.5,
        gaps=["no auth_session flow"],
        decision="re_plan",
    )
    assert _round_trip(verdict) == verdict


def test_generated_test_round_trip():
    generated = GeneratedTest(
        flow_id="f1",
        file_path="generated_tests/test_f1.py",
        selector_map={"f1-1": "role=button[name='Submit']"},
        validation_status="validated",
    )
    assert _round_trip(generated) == generated


def test_selector_suggestion_round_trip():
    suggestion = SelectorSuggestion(
        match_by="nth_of_type",
        value="text:0",
        rationale="The first plain-text input, by position, matches 'First name'.",
    )
    assert _round_trip(suggestion) == suggestion


def test_prd_gap_analysis_round_trip():
    analysis = PRDGapAnalysis(
        requirements=[
            PRDRequirement(requirement="Users can log in", covering_flow_id="f0", status="covered"),
            PRDRequirement(requirement="Users can enable 2FA", covering_flow_id=None, status="not_covered"),
        ]
    )
    assert _round_trip(analysis) == analysis


def test_execution_result_round_trip():
    result = ExecutionResult(
        flow_id="f1",
        status="fail",
        duration_ms=1234,
        error_message="TimeoutError: locator not found",
        screenshot_path="reports/f1.png",
        console_errors=["Uncaught TypeError"],
        network_errors=["500 /api/login"],
    )
    assert _round_trip(result) == result


def test_healer_verdict_round_trip():
    verdict = HealerVerdict(
        flow_id="f1",
        classification="script_issue",
        confidence=0.9,
        evidence={"selector_matches": 0, "similar_element_found": True},
        action_taken="auto_repaired",
        rationale="Selector stale after DOM change; repaired to nearby role-based locator.",
        repair_diff="- text=Submit\n+ role=button[name='Submit']",
    )
    assert _round_trip(verdict) == verdict


def test_final_report_round_trip():
    report = FinalReport(
        flows_planned=3,
        flows_by_category={"navigation": 2, "auth_session": 1},
        pass_count=2,
        fail_count=1,
        healer_actions=[],
        coverage_gaps_remaining=["destructive_action not covered"],
        untested_flow_risk=["flow-2 never ran"],
        prd_gap_analysis=[{"requirement": "user can reset password", "status": "not covered"}],
        escalations=[],
    )
    assert _round_trip(report) == report


def test_site_model_round_trip():
    site = SiteModel(
        start_url="https://example.com",
        pages=[
            PageInfo(
                url="https://example.com",
                title="Home",
                accessibility_snapshot={"role": "WebArea", "name": "Home"},
                forms=[
                    FormInfo(
                        action="/login",
                        method="post",
                        fields=[FormFieldInfo(name="email", field_type="email", required=True)],
                    )
                ],
                nav_links=[LinkInfo(text="About", href="/about")],
                buttons=[ButtonInfo(text="Delete account", is_destructive=True)],
                structural_signature="abc123",
            )
        ],
        partial=False,
        notes=[],
    )
    assert _round_trip(site) == site
