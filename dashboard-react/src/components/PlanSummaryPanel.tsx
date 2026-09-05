import { useRunState } from "../state/RunContext";

export function PlanSummaryPanel() {
  const { flowCategories, criticVerdict } = useRunState();

  return (
    <div className="mb-3.5 rounded-lg border border-slate-200 bg-white p-3.25 px-3.75">
      <h2 className="m-0 mb-2 text-[10.5px] font-bold tracking-wide text-slate-400 uppercase">Plan &amp; Coverage</h2>
      {!flowCategories.length && !criticVerdict ? (
        <span className="text-xs text-slate-400 italic">no data yet</span>
      ) : (
        <>
          {flowCategories.length ? (
            <>
              <div className="py-1.5 text-[12px] text-slate-500">categories</div>
              <div className="text-[11.5px] text-slate-500">{flowCategories.join(", ")}</div>
            </>
          ) : null}
          {criticVerdict ? (
            <div
              className={`flex items-center justify-between border-slate-200 py-1.5 ${
                flowCategories.length ? "mt-2 border-t" : ""
              }`}
            >
              <span className="text-[12px] text-slate-500">critic decision</span>
              <span
                className={`rounded-full px-2.25 py-0.5 text-[11px] font-semibold ${
                  criticVerdict.decision === "proceed"
                    ? "bg-green-bg text-green"
                    : criticVerdict.decision === "re_plan"
                      ? "bg-amber-bg text-amber"
                      : "bg-red-bg text-red"
                }`}
              >
                {criticVerdict.decision}
              </span>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
