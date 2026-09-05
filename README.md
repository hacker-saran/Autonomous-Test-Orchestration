# Autonomous Test Orchestration Agent

Bessemer Tech Catalyst hackathon project (AI/ML track). Given a web app URL, generates and
executes a Playwright test suite plus a test quality report, with no manual scripting in
between: `Planner → Coverage critic → Generator → Executor → Healer → Reporter`.

## Architecture

<!-- TODO: drop an architecture diagram image here, e.g. ![architecture](docs/architecture.png) -->

One-line description: the six-agent pipeline, the state machine driving it
(`orchestrator/orchestrator.py`), and how the Pydantic schemas in `orchestrator/schemas.py`
flow between agents.

## Setup

One-line description: Python version, installing dependencies, `playwright install`, and
configuring `.env` from `.env.example` (LLM provider API key/base URL — Sarvam by
default, model names, crawl limits).

## Running the pipeline

One-line description: the `python -m orchestrator run --url <url> [--prd ...] [--focus ...]
[--credentials-file ...]` CLI invocation and what each flag does.

## Design decisions & trade-offs

One-line description: notable choices made during the hackathon and why (e.g. why Sarvam,
why a single `call_structured` wrapper, why a linear state machine over a heavier framework).

## Known limitations

One-line description: what's stubbed vs. real right now, and what would need to change to
go from hackathon demo to production.
