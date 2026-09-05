"""Live-event emitter for the dashboard.

Appends one JSON line per pipeline event to dashboard/events.jsonl, which
dashboard/index.html polls (plain `fetch`, no server code) to render a live
view of a run in progress. No new dependency: `python -m http.server` run
from inside dashboard/ is enough to serve both files over the same origin.

Also supports in-process subscribers (see `subscribe()`) — used by
orchestrator/web/server.py to push events to WebSocket clients in real time,
in addition to (not instead of) the file above. The file-based path and the
legacy dashboard keep working completely independently of whether anything
is subscribed.

Never lets a dashboard write failure, or a subscriber callback failure,
break the actual pipeline run.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = REPO_ROOT / "dashboard"
EVENTS_PATH = DASHBOARD_DIR / "events.jsonl"

_subscribers: list[Callable[[dict], None]] = []


def subscribe(callback: Callable[[dict], None]) -> Callable[[], None]:
    """Registers a callback invoked with every emitted event record (a plain
    dict). The callback may be called from whatever thread emit() runs on —
    it must not assume it's on any particular thread/event loop. Returns an
    unsubscribe function.
    """
    _subscribers.append(callback)

    def _unsubscribe() -> None:
        try:
            _subscribers.remove(callback)
        except ValueError:
            pass

    return _unsubscribe


def reset() -> None:
    """Clears the events file at the start of a run, so the dashboard shows
    only the run in progress instead of appending under a previous one."""
    try:
        DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
        EVENTS_PATH.write_text("", encoding="utf-8")
    except OSError:
        pass


def emit(event_type: str, **fields: Any) -> None:
    record = {"ts": time.time(), "type": event_type, **fields}
    try:
        with open(EVENTS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except OSError:
        pass
    for callback in list(_subscribers):
        try:
            callback(record)
        except Exception:  # noqa: BLE001 - a subscriber must never break the pipeline
            pass
