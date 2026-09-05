"""Every Pydantic data contract for the pipeline, in one place.

These are the messages agents pass between each other. No dicts-as-schemas —
every agent boundary below is a validated Pydantic model.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
# Crawl output (SiteCrawler -> Planner)
# --------------------------------------------------------------------------


class FormFieldInfo(BaseModel):
    name: str | None = None
    field_type: str
    required: bool = False
    pattern: str | None = None
    label: str | None = None


class FormInfo(BaseModel):
    action: str | None = None
    method: str | None = None
    fields: list[FormFieldInfo] = Field(default_factory=list)


class LinkInfo(BaseModel):
    text: str
    href: str


class ButtonInfo(BaseModel):
    text: str
    is_destructive: bool = False


class PageInfo(BaseModel):
    url: str
    title: str
    accessibility_snapshot: dict[str, Any] | None = None
    forms: list[FormInfo] = Field(default_factory=list)
    nav_links: list[LinkInfo] = Field(default_factory=list)
    buttons: list[ButtonInfo] = Field(default_factory=list)
    structural_signature: str | None = None


class SiteModel(BaseModel):
    start_url: str
    pages: list[PageInfo] = Field(default_factory=list)
    partial: bool = False
    notes: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Planning (Planner <-> Critic)
# --------------------------------------------------------------------------


class FlowStep(BaseModel):
    step_id: str
    action: Literal["navigate", "click", "fill", "select", "assert_visible", "assert_text", "assert_url"]
    target_description: str  # semantic description, resolved to a live selector by the Generator
    value: str | None = None
    expected_outcome: str | None = None


class Flow(BaseModel):
    flow_id: str
    title: str
    category: Literal[
        "happy_path", "auth_session", "form_validation", "error_state", "destructive_action", "navigation"
    ]
    priority: Literal["critical", "happy", "edge", "error"]
    preconditions: list[str] = Field(default_factory=list)
    steps: list[FlowStep]
    risk_tag: str | None = None
    source: Literal["crawl", "prd", "user_hint"] = "crawl"


class TestPlan(BaseModel):
    flows: list[Flow]
    iteration: int = 0


class CoverageVerdict(BaseModel):
    dimension_scores: dict[str, Literal["covered", "partial", "missing"]]
    justifications: dict[str, str]
    overall_score: float  # 0-1
    gaps: list[str] = Field(default_factory=list)  # targeted feedback fed back to the Planner on re-plan
    decision: Literal["proceed", "re_plan", "escalate"]


# --------------------------------------------------------------------------
# Generation / Execution (Generator -> Executor -> Healer)
# --------------------------------------------------------------------------


class GeneratedTest(BaseModel):
    flow_id: str
    file_path: str
    selector_map: dict[str, str]  # step_id -> resolved Playwright selector
    validation_status: Literal["validated", "unresolved"]


class SelectorSuggestion(BaseModel):
    """Feedback-retry tool call: given a step whose target_description didn't
    resolve to exactly one live element, and a snapshot of what's actually on
    the page, suggest a better description to retry resolution with.
    """
    suggested_description: str
    rationale: str


class ExecutionResult(BaseModel):
    flow_id: str
    status: Literal["pass", "fail", "error"]
    duration_ms: int
    error_message: str | None = None
    screenshot_path: str | None = None
    console_errors: list[str] = Field(default_factory=list)
    network_errors: list[str] = Field(default_factory=list)


class HealerVerdict(BaseModel):
    flow_id: str
    classification: Literal["script_issue", "app_defect", "flaky_env", "ambiguous"]
    confidence: float
    evidence: dict[str, Any]
    action_taken: Literal["auto_repaired", "reported", "retried", "escalated"]
    rationale: str
    repair_diff: str | None = None


# --------------------------------------------------------------------------
# Final report (Reporter)
# --------------------------------------------------------------------------


class PRDRequirement(BaseModel):
    requirement: str
    covering_flow_id: str | None = None
    status: Literal["covered", "not_covered"]


class PRDGapAnalysis(BaseModel):
    requirements: list[PRDRequirement]


class FinalReport(BaseModel):
    flows_planned: int
    flows_by_category: dict[str, int]
    pass_count: int
    fail_count: int
    healer_actions: list[HealerVerdict] = Field(default_factory=list)
    coverage_gaps_remaining: list[str] = Field(default_factory=list)
    untested_flow_risk: list[str] = Field(default_factory=list)
    prd_gap_analysis: list[dict] | None = None
    escalations: list[str] = Field(default_factory=list)
