import { useRunState } from "../state/RunContext";

function Kpi({ label, value, colorClass }: { label: string; value: string; colorClass?: string }) {
  return (
    <div className="bg-white p-3.5 px-4.5">
      <div className="text-[11px] font-semibold tracking-wide text-slate-400 uppercase">{label}</div>
      <div className={`mt-1 text-[22px] font-bold tracking-tight ${colorClass ?? ""}`}>{value}</div>
    </div>
  );
}

export function KpiRow() {
  const { currentPhase, pages, flowCount, criticVerdict, execResults } = useRunState();
  const results = Object.values(execResults);
  const passCount = results.filter((r) => r.status === "pass").length;
  const failCount = results.length - passCount;

  return (
    <div className="mx-7 mt-5 grid grid-cols-6 gap-px overflow-hidden rounded-lg border border-slate-200 bg-slate-200">
      <Kpi label="Phase" value={currentPhase ?? "—"} colorClass="text-purple" />
      <Kpi label="Pages crawled" value={String(pages.length)} />
      <Kpi label="Flows planned" value={String(flowCount)} />
      <Kpi label="Coverage score" value={criticVerdict ? `${(criticVerdict.overall_score * 100).toFixed(0)}%` : "—"} />
      <Kpi label="Passed" value={String(passCount)} colorClass="text-green" />
      <Kpi label="Failed" value={String(failCount)} colorClass="text-red" />
    </div>
  );
}
