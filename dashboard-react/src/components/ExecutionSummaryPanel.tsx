import { useRunState } from "../state/RunContext";

export function ExecutionSummaryPanel() {
  const { execResults, flowMeta } = useRunState();
  const entries = Object.entries(execResults);
  const pass = entries.filter(([, r]) => r.status === "pass").length;
  const fail = entries.length - pass;
  const visible = entries.slice(-8).reverse();

  return (
    <div className="mb-3.5 rounded-lg border border-slate-200 bg-white p-3.25 px-3.75">
      <h2 className="m-0 mb-2 text-[10.5px] font-bold tracking-wide text-slate-400 uppercase">Execution</h2>
      {entries.length === 0 ? (
        <span className="text-xs text-slate-400 italic">no data yet</span>
      ) : (
        <>
          <div className="flex items-center justify-between py-1.5">
            <span className="text-[12px] text-slate-500">passed</span>
            <span className="font-mono text-[11.5px] font-semibold text-green">{pass}</span>
          </div>
          <div className="flex items-center justify-between border-t border-slate-200 py-1.5">
            <span className="text-[12px] text-slate-500">failed</span>
            <span className="font-mono text-[11.5px] font-semibold text-red">{fail}</span>
          </div>
          <div className="mt-2">
            {visible.map(([flowId, r]) => {
              const meta = flowMeta[flowId];
              return (
                <div key={flowId} className="flex items-center justify-between gap-2.5 py-1.5">
                  <div className="min-w-0 flex-1 truncate" title={meta?.title ?? flowId}>
                    {meta?.title ?? flowId}
                  </div>
                  <span
                    className={`shrink-0 rounded-full px-2.25 py-0.5 text-[11px] font-semibold ${
                      r.status === "pass" ? "bg-green-bg text-green" : "bg-red-bg text-red"
                    }`}
                  >
                    {r.status}
                  </span>
                </div>
              );
            })}
          </div>
          {entries.length > 8 ? (
            <div className="pt-2 text-[11px] text-slate-400">+ {entries.length - 8} more</div>
          ) : null}
        </>
      )}
    </div>
  );
}
