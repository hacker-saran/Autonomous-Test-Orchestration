import { useRunState } from "../state/RunContext";

export function HealerSummaryPanel() {
  const { healerVerdicts } = useRunState();

  return (
    <div className="mb-3.5 rounded-lg border border-slate-200 bg-white p-3.25 px-3.75">
      <h2 className="m-0 mb-2 text-[10.5px] font-bold tracking-wide text-slate-400 uppercase">Healer</h2>
      {healerVerdicts.length === 0 ? (
        <span className="text-xs text-slate-400 italic">no data yet</span>
      ) : (
        healerVerdicts.map((v, i) => (
          <div key={i} className="flex items-center justify-between gap-2.5 border-t border-slate-200 py-1.5 first:border-t-0">
            <span className="min-w-0 flex-1 truncate text-[12px] text-slate-500" title={v.flow_id}>
              {v.flow_id}
            </span>
            <span
              className={`shrink-0 rounded-full px-2.25 py-0.5 text-[11px] font-semibold ${
                v.action_taken === "auto_repaired"
                  ? "bg-green-bg text-green"
                  : v.action_taken === "reported"
                    ? "bg-red-bg text-red"
                    : "bg-amber-bg text-amber"
              }`}
            >
              {v.classification}
            </span>
          </div>
        ))
      )}
    </div>
  );
}
