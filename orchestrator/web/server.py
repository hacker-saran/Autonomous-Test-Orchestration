"""FastAPI server wrapping TestOrchestrator for the React dashboard.

This is a thin layer: it starts runs via RunManager (a background thread —
TestOrchestrator.run() is blocking, synchronous code) and streams
live_events records to WebSocket clients via ws_hub. Nothing here changes
TestOrchestrator/agents/schemas behavior; `python -m orchestrator run` and
the legacy dashboard/index.html keep working completely independently of
whether this server is running.
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from orchestrator import live_events
from orchestrator.config import get_settings
from orchestrator.orchestrator import REPORTS_DIR
from orchestrator.web.run_manager import RunAlreadyInProgress, RunRecord, run_manager
from orchestrator.web.ws_hub import hub

logger = logging.getLogger(__name__)

DASHBOARD_DIR = live_events.DASHBOARD_DIR
SCREENSHOTS_DIR = DASHBOARD_DIR / "screenshots"


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    hub.bind_loop(asyncio.get_running_loop())
    unsubscribe = live_events.subscribe(hub.publish_threadsafe)
    try:
        yield
    finally:
        unsubscribe()


app = FastAPI(title="Autonomous Test Orchestration API", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


class StartRunRequest(BaseModel):
    url: str
    prd_path: str | None = None
    focus_hint: str | None = None
    credentials: dict | None = None


class RunSummary(BaseModel):
    run_id: str
    url: str
    status: str
    started_at: float
    finished_at: float | None = None


def _summary(record: RunRecord) -> RunSummary:
    return RunSummary(
        run_id=record.run_id, url=record.url, status=record.status,
        started_at=record.started_at, finished_at=record.finished_at,
    )


@app.post("/api/runs", status_code=202)
def start_run(req: StartRunRequest) -> RunSummary:
    try:
        record = run_manager.start_run(
            url=req.url, prd_path=req.prd_path, focus_hint=req.focus_hint, credentials=req.credentials,
        )
    except RunAlreadyInProgress as exc:
        raise HTTPException(status_code=409, detail=f"Run {exc.run_id} already in progress") from exc
    return _summary(record)


@app.get("/api/runs")
def list_runs() -> list[RunSummary]:
    return [_summary(r) for r in run_manager.list_history()]


@app.get("/api/runs/current")
def get_current_run() -> RunSummary | None:
    record = run_manager.current()
    return _summary(record) if record is not None else None


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    record = run_manager.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {
        "run_id": record.run_id,
        "url": record.url,
        "status": record.status,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "report": record.report.model_dump() if record.report else None,
        "error": record.error,
    }


@app.get("/api/reports")
def list_reports() -> list[dict]:
    """Reads orchestrator/reports/*.json directly off disk — durable history
    that survives server restarts, independent of RunManager's in-memory
    (this-session-only) history."""
    if not REPORTS_DIR.exists():
        return []
    reports = []
    for json_path in sorted(REPORTS_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        reports.append({"timestamp": json_path.stem, "report": data})
    return reports


@app.get("/api/reports/{timestamp}.html")
def get_report_html(timestamp: str) -> FileResponse:
    html_path = REPORTS_DIR / f"{timestamp}.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="report not found")
    return FileResponse(html_path)


@app.websocket("/ws")
async def ws_events(websocket: WebSocket) -> None:
    await websocket.accept()
    queue = await hub.register()
    try:
        while True:
            record = await queue.get()
            await websocket.send_json(record)
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(queue)


# Screenshots live at dashboard/screenshots/{flow_id}.png — executor.py /
# generator.py already write there unchanged; just serve that directory.
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/screenshots", StaticFiles(directory=str(SCREENSHOTS_DIR)), name="screenshots")
