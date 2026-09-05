import { useEffect, useState } from "react";
import { listReports, type ReportListEntry } from "../api/client";

function formatTimestamp(ts: string): string {
  // Reporter writes UTC timestamps shaped like "20260905T103421Z".
  const match = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/.exec(ts);
  if (!match) return ts;
  const [, y, mo, d, h, mi, s] = match;
  const iso = `${y}-${mo}-${d}T${h}:${mi}:${s}Z`;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? ts : date.toLocaleString();
}

function ReportRow({ entry }: { entry: ReportListEntry }) {
  const [expanded, setExpanded] = useState(false);
  const { report } = entry;
  const hasIssues =
    report.escalations.length > 0 || report.coverage_gaps_remaining.length > 0 || report.fail_count > 0;

  return (
    <div className="border-b border-slate-200 last:border-b-0">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between gap-3 px-1 py-3 text-left"
      >
        <div className="min-w-0">
          <div className="text-[12.5px] font-semibold">{formatTimestamp(entry.timestamp)}</div>
          <div className="mt-0.5 text-[11px] text-slate-400">{report.flows_planned} flow(s) planned</div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="rounded-full bg-green-bg px-2.25 py-0.5 text-[11px] font-semibold text-green">
            {report.pass_count} passed
          </span>
          {report.fail_count > 0 ? (
            <span className="rounded-full bg-red-bg px-2.25 py-0.5 text-[11px] font-semibold text-red">
              {report.fail_count} failed
            </span>
          ) : null}
          <a
            href={`/api/reports/${entry.timestamp}.html`}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="text-[11.5px] font-medium text-purple whitespace-nowrap"
          >
            Open full report ↗
          </a>
        </div>
      </button>

      {expanded ? (
        <div className="space-y-2.5 px-1 pb-3.5 text-[12px]">
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(report.flows_by_category).map(([category, count]) => (
              <span key={category} className="rounded-full bg-slate-100 px-2.25 py-0.5 text-[11px] text-slate-600">
                {category}: {count}
              </span>
            ))}
          </div>

          {report.healer_actions.length > 0 ? (
            <div>
              <div className="mb-1 text-[10.5px] font-bold tracking-wide text-slate-400 uppercase">
                Healer actions
              </div>
              {report.healer_actions.map((a, i) => (
                <div key={i} className="py-1 text-[11.5px] text-slate-500">
                  <code className="rounded bg-slate-100 px-1.5 py-0.5">{a.flow_id}</code> — {a.classification} →{" "}
                  {a.action_taken}
                </div>
              ))}
            </div>
          ) : null}

          {report.coverage_gaps_remaining.length > 0 ? (
            <div>
              <div className="mb-1 text-[10.5px] font-bold tracking-wide text-slate-400 uppercase">
                Coverage gaps remaining
              </div>
              <ul className="list-disc space-y-0.5 pl-4 text-[11.5px] text-slate-500">
                {report.coverage_gaps_remaining.map((g, i) => (
                  <li key={i}>{g}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {report.escalations.length > 0 ? (
            <div>
              <div className="mb-1 text-[10.5px] font-bold tracking-wide text-slate-400 uppercase">Escalations</div>
              <ul className="list-disc space-y-0.5 pl-4 text-[11.5px] text-red">
                {report.escalations.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {!hasIssues ? <div className="text-[11.5px] text-slate-400 italic">No gaps or escalations.</div> : null}
        </div>
      ) : null}
    </div>
  );
}

export function ReportsModal({ onClose }: { onClose: () => void }) {
  const [reports, setReports] = useState<ReportListEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listReports()
      .then(setReports)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load reports."));
  }, []);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-10 flex items-start justify-center bg-black/30 pt-20" onClick={onClose}>
      <div
        className="max-h-[75vh] w-full max-w-2xl overflow-y-auto rounded-lg border border-slate-200 bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="m-0 text-[13px] font-bold tracking-wide text-slate-600 uppercase">Past Runs</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-md px-2 py-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            ✕
          </button>
        </div>

        {error ? (
          <div className="text-[12px] text-red">{error}</div>
        ) : reports === null ? (
          <div className="text-[12px] text-slate-400 italic">Loading…</div>
        ) : reports.length === 0 ? (
          <div className="text-[12px] text-slate-400 italic">No completed runs yet.</div>
        ) : (
          reports.map((entry) => <ReportRow key={entry.timestamp} entry={entry} />)
        )}
      </div>
    </div>
  );
}
