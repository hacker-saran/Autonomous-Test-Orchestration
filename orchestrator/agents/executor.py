"""Executor agent: runs the generated pytest-playwright suite and captures an
ExecutionResult per flow.

TODO (team, live at the event):
  - Run the whole suite in one pytest-playwright invocation (not one
    subprocess per flow) using `--screenshot=only-on-failure` and a
    conftest.py fixture that records console/network errors per test via
    `page.on("console", ...)` / `page.on("response", ...)`.
  - Parse a machine-readable report (e.g. `pytest --json-report`) instead of
    return-code-only, to get accurate per-test duration/error/screenshot
    paths keyed by flow_id.
  - Populate `screenshot_path`, `console_errors`, `network_errors` below —
    they are currently always empty/None.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import time

from orchestrator.schemas import ExecutionResult, GeneratedTest

logger = logging.getLogger(__name__)


class Executor:
    def run(self, generated_tests: list[GeneratedTest]) -> list[ExecutionResult]:
        """Trivial pass-through: runs each generated test file as its own
        `pytest` subprocess and maps the return code to pass/fail/error. No
        screenshots or console/network capture yet. See TODO above.
        """
        results: list[ExecutionResult] = []
        for gt in generated_tests:
            start = time.monotonic()
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "pytest", gt.file_path, "-q"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                duration_ms = int((time.monotonic() - start) * 1000)
                status = "pass" if proc.returncode == 0 else "fail"
                error_message = None if status == "pass" else (proc.stdout + proc.stderr)[-2000:]
            except subprocess.TimeoutExpired as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                status = "error"
                error_message = f"Test timed out: {exc}"

            results.append(
                ExecutionResult(
                    flow_id=gt.flow_id,
                    status=status,
                    duration_ms=duration_ms,
                    error_message=error_message,
                    screenshot_path=None,
                    console_errors=[],
                    network_errors=[],
                )
            )
            logger.info("Executor: flow=%s status=%s duration_ms=%d", gt.flow_id, status, duration_ms)

        return results
