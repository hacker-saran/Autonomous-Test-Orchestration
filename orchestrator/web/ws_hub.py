"""Bridges live_events.emit() (called on the orchestrator's plain worker
thread — Playwright's sync API and subprocess pytest calls are not asyncio)
to any number of connected WebSocket clients running on FastAPI's asyncio
event loop.

publish_threadsafe() is safe to call from ANY thread. It uses
loop.call_soon_threadsafe rather than asyncio.run_coroutine_threadsafe:
dispatch is a plain synchronous callable (put_nowait on already-created
queues, nothing to await), so the lighter "run this callable soon" primitive
is enough — scheduling a coroutine would be unnecessary overhead here.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class WebSocketHub:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._clients: set[asyncio.Queue] = set()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish_threadsafe(self, record: dict[str, Any]) -> None:
        """No-op if the server isn't up yet (no loop bound) or no clients are
        connected — mirrors live_events.emit()'s own "never break the
        pipeline" contract.
        """
        loop = self._loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(self._dispatch, record)
        except RuntimeError:
            pass  # loop closed/shutting down

    def _dispatch(self, record: dict[str, Any]) -> None:
        for q in list(self._clients):
            try:
                q.put_nowait(record)
            except asyncio.QueueFull:
                logger.warning("WS client queue full, dropping event %s", record.get("type"))

    async def register(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._clients.add(q)
        return q

    def unregister(self, q: asyncio.Queue) -> None:
        self._clients.discard(q)


hub = WebSocketHub()
