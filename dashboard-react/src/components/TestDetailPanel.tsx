import { useRunState } from "../state/RunContext";

export function TestDetailPanel() {
  const { selectedFlowId, flowMeta, execResults } = useRunState();

  const meta = selectedFlowId ? flowMeta[selectedFlowId] : undefined;
  const result = selectedFlowId ? execResults[selectedFlowId] : undefined;

  return (
    <div className="mb-3.5 rounded-lg border border-slate-200 bg-white p-3.25 px-3.75">
      <h2 className="m-0 mb-2 text-[10.5px] font-bold tracking-wide text-slate-400 uppercase">Test Detail</h2>

      {!selectedFlowId || !meta ? (
        <span className="text-xs text-slate-400 italic">
          {selectedFlowId
            ? "No data for this test."
            : 'Click a "Test generated" or "Test passed/failed" row to see its steps, command, and screenshot.'}
        </span>
      ) : (
        <>
          <div className="flex items-start justify-between gap-2">
            <div className="text-[13px] font-semibold">{meta.title}</div>
            {result ? (
              <span
                className={`rounded-full px-2.25 py-0.5 text-[11px] font-semibold ${
                  result.status === "pass" ? "bg-green-bg text-green" : "bg-red-bg text-red"
                }`}
              >
                {result.status}
              </span>
            ) : (
              <span className="rounded-full bg-amber-bg px-2.25 py-0.5 text-[11px] font-semibold text-amber">
                generated
              </span>
            )}
          </div>
          <div className="my-1 text-[10.5px] text-slate-400">
            <code className="rounded bg-slate-100 px-1.5 py-0.5">{selectedFlowId}</code> · {meta.category}
            {result ? ` · ${result.duration_ms} ms` : ""}
          </div>

          <div className="mt-3 mb-1.5 text-[10.5px] font-bold tracking-wide text-slate-400 uppercase">Test case</div>
          {meta.steps.length === 0 ? (
            <span className="text-xs text-slate-400 italic">No steps recorded.</span>
          ) : (
            <ol className="m-0 flex flex-col gap-2.25 pl-4.5 text-xs">
              {meta.steps.map((s, i) => (
                <li key={i}>
                  <span className="mr-1.5 rounded-full bg-slate-100 px-2.25 py-0.5 text-[9.5px] font-semibold text-slate-600 uppercase">
                    {s.action}
                  </span>
                  {s.target_description}
                  {s.value ? (
                    <div className="mt-0.5 text-[11px] text-slate-500">
                      value: <code className="rounded bg-slate-100 px-1.5 py-0.5">{s.value}</code>
                    </div>
                  ) : null}
                  {s.expected_outcome ? (
                    <div className="mt-0.5 text-[11px] text-slate-500">expect: {s.expected_outcome}</div>
                  ) : null}
                </li>
              ))}
            </ol>
          )}

          <div className="mt-3 mb-1.5 text-[10.5px] font-bold tracking-wide text-slate-400 uppercase">Command</div>
          <code className="block rounded-md bg-slate-100 p-2 px-2.5 font-mono text-[11px] break-all whitespace-pre-wrap text-slate-500">
            {meta.command || "n/a"}
          </code>

          <div className="mt-3 mb-1.5 text-[10.5px] font-bold tracking-wide text-slate-400 uppercase">Screenshot</div>
          {result?.screenshot_url ? (
            <img
              className="block w-full rounded-md border border-slate-200"
              // screenshot_url from the backend is a bare relative path
              // ("screenshots/{flow_id}.png"); root it so it hits the
              // /screenshots proxy (dev) / mount (prod) instead of resolving
              // relative to the current React route.
              src={`/${result.screenshot_url}?t=${encodeURIComponent(result.ts)}`}
              alt={`Screenshot for ${selectedFlowId}`}
            />
          ) : (
            <span className="text-xs text-slate-400 italic">
              {result ? "No screenshot captured for this run." : "Not executed yet."}
            </span>
          )}
        </>
      )}
    </div>
  );
}
