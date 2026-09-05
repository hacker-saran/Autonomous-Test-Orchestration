"""Shared prompt-serialization helpers for agents.

Both the Planner and the Critic need to serialize the crawled SiteModel (and
the Critic also needs the TestPlan) into a compact, LLM-friendly text form.
Keeping these here avoids duplicating the logic across agents.
"""
from __future__ import annotations

from orchestrator.schemas import SiteModel, TestPlan

_MAX_SITE_MODEL_CHARS = 12_000
_MAX_PLAN_CHARS = 8_000


def serialize_site_model(site_model: SiteModel, max_chars: int = _MAX_SITE_MODEL_CHARS) -> str:
    """Render a SiteModel as compact text for an LLM prompt."""
    lines = [f"Start URL: {site_model.start_url}"]
    if site_model.partial:
        lines.append(f"NOTE: Crawl was partial: {'; '.join(site_model.notes)}")

    for i, page in enumerate(site_model.pages):
        lines.append(f"\n--- Page {i + 1} ---")
        lines.append(f"URL: {page.url}")
        lines.append(f"Title: {page.title}")

        if page.forms:
            for j, form in enumerate(page.forms):
                fields = ", ".join(
                    f"{f.label or f.name or 'unnamed'}(type={f.field_type}, required={f.required})"
                    for f in form.fields
                )
                lines.append(f"Form {j + 1}: action={form.action}, method={form.method}, fields=[{fields}]")

        if page.buttons:
            buttons = ", ".join(
                f"{b.text}{' [DESTRUCTIVE]' if b.is_destructive else ''}" for b in page.buttons
            )
            lines.append(f"Buttons: {buttons}")

        if page.nav_links:
            links = ", ".join(f"{l.text} -> {l.href}" for l in page.nav_links[:10])
            lines.append(f"Nav links: {links}")

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated]"
    return text


def serialize_plan(plan: TestPlan, max_chars: int = _MAX_PLAN_CHARS) -> str:
    """Render a TestPlan as compact text for an LLM prompt."""
    lines = [f"TestPlan (iteration {plan.iteration}):"]
    for flow in plan.flows:
        lines.append(f"\nFlow {flow.flow_id}: {flow.title}")
        lines.append(f"  Category: {flow.category}, Priority: {flow.priority}, Source: {flow.source}")
        if flow.preconditions:
            lines.append(f"  Preconditions: {', '.join(flow.preconditions)}")
        if flow.risk_tag:
            lines.append(f"  Risk: {flow.risk_tag}")
        for step in flow.steps:
            value = f", value={step.value!r}" if step.value else ""
            expected = f", expect={step.expected_outcome!r}" if step.expected_outcome else ""
            lines.append(f"  - {step.step_id}: {step.action} {step.target_description!r}{value}{expected}")

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated]"
    return text