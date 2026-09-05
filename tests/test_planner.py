"""Unit tests for the Planner agent with a mocked call_structured."""
from __future__ import annotations

from unittest.mock import patch

from orchestrator.agents.planner import Planner
from orchestrator.schemas import Flow, FlowStep, SiteModel, TestPlan


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


def test_planner_calls_structured_and_returns_plan():
    """Planner should call call_structured with TestPlan and return the result."""
    site_model = _make_site_model()
    expected_plan = _make_plan()

    with patch("orchestrator.agents.planner.call_structured", return_value=expected_plan) as mock_call:
        planner = Planner()
        result = planner.plan(site_model, prd_text=None, focus_hint=None, feedback=None, iteration=0)

    assert result == expected_plan
    assert result.iteration == 0
    mock_call.assert_called_once()
    # The response_model must be TestPlan (3rd positional arg)
    assert mock_call.call_args.args[2] is TestPlan


def test_planner_sets_iteration():
    """Planner should stamp the iteration onto the returned plan."""
    site_model = _make_site_model()
    plan = _make_plan()
    plan.iteration = 99  # simulate LLM returning wrong iteration

    with patch("orchestrator.agents.planner.call_structured", return_value=plan):
        result = Planner().plan(site_model, iteration=3)

    assert result.iteration == 3


def test_planner_prompt_includes_feedback_and_focus():
    """The user prompt should include critic feedback and focus hint."""
    site_model = _make_site_model()
    plan = _make_plan()

    with patch("orchestrator.agents.planner.call_structured", return_value=plan) as mock_call:
        Planner().plan(
            site_model,
            prd_text="Users can reset their password.",
            focus_hint="Test the checkout flow",
            feedback=["no auth_session flow", "no destructive_action flow"],
            iteration=1,
        )

    user_prompt = mock_call.call_args.args[1]
    assert "Users can reset their password." in user_prompt
    assert "Test the checkout flow" in user_prompt
    assert "no auth_session flow" in user_prompt
    assert "no destructive_action flow" in user_prompt
    assert "PLANNING ITERATION: 1" in user_prompt


def test_planner_prompt_serializes_site_model():
    """The user prompt should contain the site model's key details."""
    site_model = _make_site_model()
    plan = _make_plan()

    with patch("orchestrator.agents.planner.call_structured", return_value=plan) as mock_call:
        Planner().plan(site_model)

    user_prompt = mock_call.call_args.args[1]
    assert "https://example.com" in user_prompt
    assert "Home" in user_prompt
    assert "Login" in user_prompt
    assert "Email" in user_prompt