import { useEffect, useRef } from "react";
import { useRunState } from "../state/RunContext";
import { EventFeedRow } from "./EventFeedRow";

export function EventFeed() {
  const { events } = useRunState();
  const feedRef = useRef<HTMLDivElement>(null);
  const wasNearBottom = useRef(true);

  useEffect(() => {
    const el = feedRef.current;
    if (el && wasNearBottom.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [events.length]);

  function handleScroll() {
    const el = feedRef.current;
    if (!el) return;
    wasNearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  }

  return (
    <div className="flex h-full flex-col rounded-lg border border-slate-200 bg-white">
      <div className="sticky top-0 z-1 grid grid-cols-[108px_130px_1fr] border-b border-slate-200 bg-white p-2.25 px-4 text-[10.5px] font-bold tracking-wide text-slate-400 uppercase">
        <span>Time</span>
        <span>Event</span>
        <span>Details</span>
      </div>
      {events.length === 0 ? (
        <div className="p-15 px-5 text-center text-[12.5px] text-slate-400">
          Waiting for a run to start
          <br />
          <code className="rounded bg-slate-100 px-1.5 py-0.5">Use the "New Run" form to begin</code>
        </div>
      ) : (
        <div ref={feedRef} className="flex-1 overflow-y-auto" onScroll={handleScroll}>
          {events.map((ev, i) => (
            <EventFeedRow key={i} event={ev} />
          ))}
        </div>
      )}
    </div>
  );
}
