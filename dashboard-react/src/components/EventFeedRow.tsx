import type { ReactNode } from "react";
import type { PipelineEvent } from "../types/events";
import { fmtTs, pathOf, trunc } from "../utils/format";
import { useRunDispatch, useRunState } from "../state/RunContext";

type Pill = "purple" | "green" | "amber" | "red" | "gray";

const PILL_CLASSES: Record<Pill, string> = {
  purple: "bg-purple-bg text-purple before:bg-purple",
  green: "bg-green-bg text-green before:bg-green",
  amber: "bg-amber-bg text-amber before:bg-amber",
  red: "bg-red-bg text-red before:bg-red",
  gray: "bg-slate-100 text-slate-600 before:bg-slate-400",
};

function Pill({ tone, children }: { tone: Pill; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.25 py-0.5 text-[11px] font-semibold whitespace-nowrap before:h-1.5 before:w-1.5 before:rounded-full before:content-[''] ${PILL_CLASSES[tone]}`}
    >
      {children}
    </span>
  );
}

function describe(ev: PipelineEvent): {
  pill: Pill;
  kind: string;
  headline: ReactNode;
  detail: ReactNode;
  isErr: boolean;
  flowId?: string;
} {
  // UnknownEvent.type is plain `string`, not a literal, so TS can't exclude
  // it from any single-literal switch case below on its own — narrow it out
  // explicitly first via its distinguishing shape (the only member with a
  // `data` field).
  if ("data" in ev) {
    return { pill: "gray", kind: ev.type, headline: "", detail: JSON.stringify(ev.data), isErr: false };
  }

  switch (ev.type) {
    case "run_started":
      return {
        pill: "purple",
        kind: "Run started",
        headline: <code className="rounded bg-slate-100 px-1.5 py-0.5">{ev.url}</code>,
        detail: ev.focus_hint ? `focus: ${ev.focus_hint}` : "",
        isErr: false,
      };
    case "phase": {
      let detail: ReactNode = "";
      if (ev.iteration !== undefined) detail = `iteration ${ev.iteration}`;
      else if (ev.flow_count !== undefined) detail = `${ev.flow_count} flow(s) to generate`;
      else if (ev.test_count !== undefined) detail = `${ev.test_count} test(s) to run`;
      else if (ev.url) detail = <code className="rounded bg-slate-100 px-1.5 py-0.5">{ev.url}</code>;
      return { pill: "gray", kind: ev.phase, headline: detail, detail: "", isErr: false };
    }
    case "page_crawled":
      return {
        pill: "gray",
        kind: "Page crawled",
        headline: <code className="rounded bg-slate-100 px-1.5 py-0.5">{pathOf(ev.url)}</code>,
        detail: `${ev.forms} form(s) · ${ev.buttons} button(s) · ${ev.nav_links} nav link(s)`,
        isErr: false,
      };
    case "crawl_done":
      return {
        pill: ev.partial ? "amber" : "green",
        kind: "Crawl complete",
        headline: `${ev.pages} page${ev.pages === 1 ? "" : "s"} discovered`,
        detail: ev.partial ? "Partial: " + trunc(ev.notes.join(" — "), 200) : "",
        isErr: ev.partial,
      };
    case "plan_produced":
      return {
        pill: "purple",
        kind: "Plan produced",
        headline: `${ev.flow_count} flow${ev.flow_count === 1 ? "" : "s"}`,
        detail: ev.categories.join(" · "),
        isErr: false,
      };
    case "critic_verdict":
      return {
        pill: ev.decision === "proceed" ? "green" : ev.decision === "re_plan" ? "amber" : "red",
        kind: "Critic verdict",
        headline: `${ev.decision} · ${(ev.overall_score * 100).toFixed(0)}% coverage`,
        detail: ev.gaps.length ? "Gaps: " + trunc(ev.gaps.join(" — "), 200) : "",
        isErr: false,
      };
    case "test_generated":
      return {
        pill: ev.validation_status === "validated" ? "green" : "amber",
        kind: "Test generated",
        headline: ev.title,
        detail: (
          <>
            <code className="rounded bg-slate-100 px-1.5 py-0.5">{ev.flow_id}</code> · {ev.category} ·{" "}
            {ev.validation_status} · click for details
          </>
        ),
        isErr: false,
        flowId: ev.flow_id,
      };
    case "test_executed": {
      const pass = ev.status === "pass";
      return {
        pill: pass ? "green" : "red",
        kind: pass ? "Test passed" : "Test failed",
        headline: <code className="rounded bg-slate-100 px-1.5 py-0.5">{ev.flow_id}</code>,
        detail: `${ev.duration_ms} ms · click for details`,
        isErr: !pass,
        flowId: ev.flow_id,
      };
    }
    case "healer_verdict":
      return {
        pill: ev.action_taken === "auto_repaired" ? "green" : ev.action_taken === "reported" ? "red" : "amber",
        kind: "Healer · " + ev.action_taken,
        headline: (
          <>
            <code className="rounded bg-slate-100 px-1.5 py-0.5">{ev.flow_id}</code> — {ev.classification} (
            {(ev.confidence * 100).toFixed(0)}%)
          </>
        ),
        detail: trunc(ev.rationale, 200),
        isErr: false,
      };
    case "escalation":
      return {
        pill: "red",
        kind: "Escalation · " + ev.stage,
        headline: trunc(ev.detail, 200),
        detail: "",
        isErr: true,
      };
    case "run_finished":
      return {
        pill: "purple",
        kind: "Run finished",
        headline: `${ev.pass_count} passed / ${ev.fail_count} failed · ${ev.flows_planned} flow(s) planned`,
        detail: ev.escalations.length ? "Escalations: " + trunc(ev.escalations.join(" — "), 240) : "",
        isErr: ev.escalations.length > 0,
      };
  }
}

export function EventFeedRow({ event }: { event: PipelineEvent }) {
  const { selectedFlowId } = useRunState();
  const dispatch = useRunDispatch();
  const { pill, kind, headline, detail, isErr, flowId } = describe(event);
  const clickable = Boolean(flowId);
  const selected = flowId !== undefined && flowId === selectedFlowId;

  return (
    <div
      className={`grid grid-cols-[108px_130px_1fr] items-start border-b border-slate-200 p-2.25 px-4 ${
        clickable ? "cursor-pointer" : ""
      } ${selected ? "bg-purple-bg shadow-[inset_3px_0_0_var(--color-purple)]" : "hover:bg-slate-50"}`}
      onClick={() => flowId && dispatch({ kind: "select_flow", flowId })}
    >
      <div className="pt-px font-mono text-[11px] text-slate-400">{fmtTs(event.ts)}</div>
      <div className="flex items-start">
        <Pill tone={pill}>{kind}</Pill>
      </div>
      <div>
        <div className="text-[12.5px] font-semibold">{headline}</div>
        {detail ? <div className={`mt-0.5 text-[11.5px] leading-relaxed ${isErr ? "text-red" : "text-slate-500"}`}>{detail}</div> : null}
      </div>
    </div>
  );
}
