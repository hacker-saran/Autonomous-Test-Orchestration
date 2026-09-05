"""Unit tests for the Critic agent with a mocked call_structured."""
from __future__ import annotations

from unittest.mock import patch

from orchestrator.agents.critic import Critic
from orchestrator.schemas import CoverageVerdict, Flow, FlowStep, SiteModel, TestPlan


def _make_site_model() -> SiteModel:
    return SiteModel(
        start_url="https://example.com",
        pages=[
            {
                "url": "https://example.com",
                "title": "Home",
                "forms": [
                    {
                        "action": "/login",
                        "method": "post",
                        "fields": [
                            {"name": "email", "field_type": "email", "required": True, "label": "Email"},
                            {"name": "password", "field_type": "password", "required": True, "label": "Password"},
                        ],
                    }
                ],
                "buttons": [{"text": "Login", "is_destructive": False}],
                "nav_links": [{"text": "About", "href": "/about"}],
            }
        ],
        partial=False,
        notes=[],
    )


def _make_plan() -> TestPlan:
    return TestPlan(
        flows=[
            Flow(
                flow_id="flow-0",
                title="Login happy path",
                category="auth_session",
                priority="critical",
                steps=[
                    FlowStep(step_id="flow-0-step-1", action="navigate", target_description="/login", value="/login"),
                    FlowStep(step_id="flow-0-step-2", action="fill", target_description="email field", value="a@b.com"),
                    FlowStep(step_id="flow-0-step-3", action="fill", target_description="password field", value="secret"),
                    FlowStep(step_id="flow-0-step-4", action="click", target_description="Login button"),
                ],
                source="crawl",
            )
        ],
        iteration=0,
    )


def _make_verdict(
    dimension_scores: dict[str, str],
    gaps: list[str] | None = None,
    decision: str = "proceed",
    overall_score: float = 1.0,
) -> CoverageVerdict:
    return CoverageVerdict(
        dimension_scores=dimension_scores,
        justifications={d: f"justification for {d}" for d in dimension_scores},
        overall_score=overall_score,
        gaps=gaps or [],
        decision=decision,
    )


def test_critic_calls_structured_and_returns_verdict():
    """Critic should call call_structured with CoverageVerdict and return the result."""
    site_model = _make_site_model()
    plan = _make_plan()
    all_covered = {c: "covered" for c in
                   ["happy_path", "auth_session", "form_validation", "error_state", "destructive_action", "navigation"]}
    expected = _make_verdict(all_covered)

    with patch("orchestrator.agents.critic.call_structured", return_value=expected) as mock_call:
        result = Critic().review(plan, site_model, max_iterations=2)

    assert result == expected
    mock_call.assert_called_once()
    # The response_model must be CoverageVerdict (3rd positional arg)
    assert mock_call.call_args.args[2] is CoverageVerdict


def test_critic_computes_overall_score():
    """Critic should recompute overall_score from dimension scores."""
    site_model = _make_site_model()
    plan = _make_plan()
    verdict = _make_verdict(
        {
            "happy_path": "covered",
            "auth_session": "covered",
            "form_validation": "partial",
            "error_state": "missing",
            "destructive_action": "missing",
            "navigation": "covered",
        },
        overall_score=0.99,  # LLM's value should be overwritten
    )

    with patch("orchestrator.agents.critic.call_structured", return_value=verdict):
        result = Critic().review(plan, site_model, max_iterations=2)

    # covered=1.0, covered=1.0, partial=0.5, missing=0.0, missing=0.0, covered=1.0
    # = (1+1+0.5+0+0+1)/6 = 3.5/6 = 0.5833 -> 0.58
    assert result.overall_score == 0.58


def test_critic_decides_proceed_when_fully_covered():
    """All covered + high score -> proceed."""
    site_model = _make_site_model()
    plan = _make_plan()
    all_covered = {c: "covered" for c in
                   ["happy_path", "auth_session", "form_validation", "error_state", "destructive_action", "navigation"]}
    verdict = _make_verdict(all_covered)

    with patch("orchestrator.agents.critic.call_structured", return_value=verdict):
        result = Critic().review(plan, site_model, max_iterations=2)

    assert result.decision == "proceed"


def test_critic_decides_replan_when_gaps_exist():
    """Missing dimensions + iterations left -> re_plan."""
    site_model = _make_site_model()
    plan = _make_plan()
    verdict = _make_verdict(
        {
            "happy_path": "covered",
            "auth_session": "covered",
            "form_validation": "covered",
            "error_state": "missing",
            "destructive_action": "missing",
            "navigation": "covered",
        },
        gaps=["no error_state flow", "no destructive_action flow"],
    )

    with patch("orchestrator.agents.critic.call_structured", return_value=verdict):
        result = Critic().review(plan, site_model, max_iterations=2)

    assert result.decision == "re_plan"


def test_critic_escalates_when_iterations_exhausted():
    """Missing dimensions + no iterations left -> escalate."""
    site_model = _make_site_model()
    plan = _make_plan()
    plan.iteration = 2
    verdict = _make_verdict(
        {
            "happy_path": "covered",
            "auth_session": "covered",
            "form_validation": "covered",
            "error_state": "missing",
            "destructive_action": "missing",
            "navigation": "covered",
        },
        gaps=["no error_state flow", "no destructive_action flow"],
    )

    with patch("orchestrator.agents.critic.call_structured", return_value=verdict):
        result = Critic().review(plan, site_model, max_iterations=2)

    assert result.decision == "escalate"


def test_critic_escalates_when_partial_and_iterations_exhausted():
    """Partial dimensions + no iterations left -> escalate."""
    site_model = _make_site_model()
    plan = _make_plan()
    plan.iteration = 2
    verdict = _make_verdict(
        {
            "happy_path": "covered",
            "auth_session": "covered",
            "form_validation": "partial",
            "error_state": "partial",
            "destructive_action": "partial",
            "navigation": "covered",
        },
        gaps=["form_validation needs more coverage"],
    )

    with patch("orchestrator.agents.critic.call_structured", return_value=verdict):
        result = Critic().review(plan, site_model, max_iterations=2)

    assert result.decision == "escalate"


def test_critic_prompt_includes_plan_and_site():
    """The user prompt should contain both the plan and site model details."""
    site_model = _make_site_model()
    plan = _make_plan()

    with patch("orchestrator.agents.critic.call_structured", return_value=_make_verdict({})) as mock_call:
        Critic().review(plan, site_model, max_iterations=2)

    user_prompt = mock_call.call_args.args[1]
    assert "Login happy path" in user_prompt
    assert "https://example.com" in user_prompt
    assert "auth_session" in user_prompt