import { useEffect, useRef } from "react";
import type { PipelineEvent } from "../types/events";

export type ConnectionStatus = "connecting" | "live" | "disconnected";

const KNOWN_TYPES = new Set([
  "run_started",
  "phase",
  "page_crawled",
  "crawl_done",
  "plan_produced",
  "critic_verdict",
  "test_generated",
  "test_executed",
  "healer_verdict",
  "escalation",
  "run_finished",
]);

/** The server sends every event as a flat JSON object ({type, ts, ...fields}).
 * Known types pass through as-is (matching their PipelineEvent shape); an
 * unrecognized type is reshaped into UnknownEvent's {type, ts, data} form so
 * the reducer's switch can still narrow on `type` without an index signature
 * poisoning the whole union (see types/events.ts). */
function parseEvent(raw: string): PipelineEvent {
  const obj = JSON.parse(raw) as { type: string; ts: number; [key: string]: unknown };
  if (KNOWN_TYPES.has(obj.type)) {
    // Trusted boundary cast: the server is the source of truth for this
    // shape once `type` is a recognized literal; a plain `as` can't bridge
    // an indexed object type to the discriminated union, hence the
    // `unknown` stopover.
    return obj as unknown as PipelineEvent;
  }
  const { type, ts, ...data } = obj;
  return { type, ts, data };
}

/** Connects to the orchestrator's event WebSocket and pushes each frame to
 * onEvent as it arrives (no polling delay), reconnecting with exponential
 * backoff (capped at 15s) if the connection drops. */
export function useEventSocket(
  url: string,
  onEvent: (event: PipelineEvent) => void,
  onStatus: (status: ConnectionStatus) => void,
) {
  const onEventRef = useRef(onEvent);
  const onStatusRef = useRef(onStatus);
  onEventRef.current = onEvent;
  onStatusRef.current = onStatus;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let closedByCleanup = false;
    let retryDelayMs = 1000;

    function connect() {
      onStatusRef.current("connecting");
      ws = new WebSocket(url);

      ws.onopen = () => {
        retryDelayMs = 1000;
        onStatusRef.current("live");
      };
      ws.onmessage = (ev) => {
        try {
          onEventRef.current(parseEvent(ev.data));
        } catch {
          /* skip a malformed frame */
        }
      };
      ws.onclose = () => {
        onStatusRef.current("disconnected");
        if (closedByCleanup) return;
        retryTimer = setTimeout(connect, retryDelayMs);
        retryDelayMs = Math.min(retryDelayMs * 2, 15000);
      };
      ws.onerror = () => ws?.close();
    }

    connect();
    return () => {
      closedByCleanup = true;
      if (retryTimer) clearTimeout(retryTimer);
      ws?.close();
    };
  }, [url]);
}
