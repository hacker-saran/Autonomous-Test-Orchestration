"""Owns the single in-flight pipeline run (if any) plus a bounded, in-memory,
this-server-session history of past runs.

Single-run-at-a-time is deliberate, not a simplification to fix later:
generated_tests/*.py, generated_tests/.auth/state.json, and
dashboard/screenshots/{flow_id}.png are all fixed, unnamespaced paths shared
across the whole process — two concurrent runs would silently clobber each
other's generated files and screenshots. A second start_run() while one is
already running raises RunAlreadyInProgress (the server maps this to HTTP 409)
instead of allowing that corruption.

TestOrchestrator.run() itself is synchronous/blocking (Playwright's sync API,
subprocess pytest calls) and must never run on FastAPI's asyncio event loop
thread — it's launched on a plain named daemon thread instead of
run_in_executor's default pool, so it's trivially inspectable/nameable and
isn't limited by the executor's worker cap.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Literal

from orchestrator.orchestrator import TestOrchestrator
from orchestrator.schemas import FinalReport

logger = logging.getLogger(__name__)

RunStatus = Literal["running", "completed", "failed"]


@dataclass
class RunRecord:
    run_id: str
    url: str
    started_at: float
    status: RunStatus = "running"
    finished_at: float | None = None
    report: FinalReport | None = None
    error: str | None = None


class RunAlreadyInProgress(Exception):
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        super().__init__(f"Run {run_id} is already in progress")


class RunManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: RunRecord | None = None
        self._history: dict[str, RunRecord] = {}

    def start_run(
        self,
        url: str,
        prd_path: str | None = None,
        focus_hint: str | None = None,
        credentials: dict | None = None,
    ) -> RunRecord:
        with self._lock:
            if self._current is not None and self._current.status == "running":
                raise RunAlreadyInProgress(self._current.run_id)
            record = RunRecord(run_id=str(uuid.uuid4()), url=url, started_at=time.time())
            self._current = record
            self._history[record.run_id] = record

        def _worker() -> None:
            try:
                orchestrator = TestOrchestrator()
                report = orchestrator.run(
                    url=url, prd_path=prd_path, focus_hint=focus_hint, credentials=credentials,
                )
                record.report = report
                record.status = "completed"
            except Exception as exc:  # noqa: BLE001 - a failed run must not crash the thread silently
                logger.exception("Run %s failed", record.run_id)
                record.error = str(exc)
                record.status = "failed"
            finally:
                record.finished_at = time.time()

        threading.Thread(target=_worker, name=f"orchestrator-run-{record.run_id}", daemon=True).start()
        return record

    def current(self) -> RunRecord | None:
        return self._current

    def get(self, run_id: str) -> RunRecord | None:
        return self._history.get(run_id)

    def list_history(self) -> list[RunRecord]:
        return sorted(self._history.values(), key=lambda r: r.started_at, reverse=True)


run_manager = RunManager()
