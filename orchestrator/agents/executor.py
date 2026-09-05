"""Executor agent: runs the generated pytest-playwright suite and captures an
ExecutionResult per flow.

Auth contract (coordinated with Generator — see its module docstring): each
generated test is run as its own pytest subprocess, so per-flow env vars
control everything below without touching the generated file's code:
  - `ORCH_TEST_USERNAME` / `ORCH_TEST_PASSWORD`, read by the auth_session
    flow's `os.environ[...]` fill steps (set from the credentials file, never
    written to disk as a literal secret).
  - `ORCH_STORAGE_STATE_PATH`, read by the auto-generated `conftest.py` in
    generated_tests/ to inject the captured login session — set for every
    flow *except* the auth_session flow itself, which must start logged out.
  - `ORCH_DIAGNOSTICS_PATH`, where that same conftest.py's autouse fixture
    writes console errors and network errors (4xx/5xx responses, failed
    requests, and requests still pending when the test ends) as JSON, which
    Executor reads back here into `console_errors`/`network_errors`.

Screenshot capture: `--screenshot=only-on-failure --output=<per-flow dir>`
are pytest-playwright's own CLI flags (confirmed against the real plugin,
not guessed) — pytest-playwright sanitizes the test's nodeid into the actual
filename, so rather than reproduce that algorithm, each flow gets its own
`--output` directory and Executor just globs it for `test-failed-*.png`.

TODO (team, live at the event):
  - Parse a machine-readable report (e.g. `pytest --json-report`) instead of
    return-code-only, to get accurate per-test duration/error paths keyed by
    flow_id.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time

from orchestrator.agents.generator import DIAGNOSTICS_DIR, GENERATED_TESTS_DIR, STORAGE_STATE_PATH
from orchestrator.schemas import ExecutionResult, GeneratedTest, TestPlan

logger = logging.getLogger(__name__)

SCREENSHOTS_DIR = GENERATED_TESTS_DIR / ".artifacts"


class Executor:
    def run(
        self,
        generated_tests: list[GeneratedTest],
        plan: TestPlan | None = None,
        credentials: dict | None = None,
    ) -> list[ExecutionResult]:
        """Runs each generated test file as its own `pytest` subprocess and
        maps the return code to pass/fail/error, reading back the
        console/network diagnostics the conftest.py fixture captured and any
        on-failure screenshot pytest-playwright produced.
        """
        auth_flow_ids = {f.flow_id for f in plan.flows if f.category == "auth_session"} if plan else set()
        DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

        results: list[ExecutionResult] = []
        for gt in generated_tests:
            env = os.environ.copy()
            if credentials:
                env["ORCH_TEST_USERNAME"] = credentials.get("username") or credentials.get("email") or ""
                env["ORCH_TEST_PASSWORD"] = credentials.get("password") or ""
            if STORAGE_STATE_PATH.exists() and gt.flow_id not in auth_flow_ids:
                env["ORCH_STORAGE_STATE_PATH"] = str(STORAGE_STATE_PATH)

            diagnostics_path = DIAGNOSTICS_DIR / f"{gt.flow_id}.json"
            diagnostics_path.unlink(missing_ok=True)  # clear a stale result from a prior run
            env["ORCH_DIAGNOSTICS_PATH"] = str(diagnostics_path)

            screenshot_dir = SCREENSHOTS_DIR / gt.flow_id
            _clear_dir(screenshot_dir)

            start = time.monotonic()
            try:
                proc = subprocess.run(
                    [
                        sys.executable, "-m", "pytest", gt.file_path, "-q",
                        "--screenshot=only-on-failure", f"--output={screenshot_dir}",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    env=env,
                )
                duration_ms = int((time.monotonic() - start) * 1000)
                status = "pass" if proc.returncode == 0 else "fail"
                error_message = None if status == "pass" else (proc.stdout + proc.stderr)[-2000:]
            except subprocess.TimeoutExpired as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                status = "error"
                error_message = f"Test timed out: {exc}"

            console_errors, network_errors = _read_diagnostics(diagnostics_path)
            screenshot_path = _find_screenshot(screenshot_dir)

            results.append(
                ExecutionResult(
                    flow_id=gt.flow_id,
                    status=status,
                    duration_ms=duration_ms,
                    error_message=error_message,
                    screenshot_path=screenshot_path,
                    console_errors=console_errors,
                    network_errors=network_errors,
                )
            )
            logger.info(
                "Executor: flow=%s status=%s duration_ms=%d console_errors=%d network_errors=%d screenshot=%s",
                gt.flow_id, status, duration_ms, len(console_errors), len(network_errors), screenshot_path,
            )

        return results


def _clear_dir(path) -> None:
    if not path.exists():
        return
    for child in path.rglob("*"):
        if child.is_file():
            child.unlink(missing_ok=True)


def _find_screenshot(screenshot_dir) -> str | None:
    matches = sorted(screenshot_dir.glob("**/test-failed-*.png"))
    return str(matches[0]) if matches else None


def _read_diagnostics(diagnostics_path) -> tuple[list[str], list[str]]:
    # Killed subprocess (timeout) or a crash before fixture teardown means no
    # file was ever written — that's fine, just means nothing to report.
    if not diagnostics_path.exists():
        return [], []
    try:
        data = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [], []
    return data.get("console_errors", []), data.get("network_errors", [])
