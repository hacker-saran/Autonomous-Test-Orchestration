import { useRunState } from "../state/RunContext";
import { pathOf } from "../utils/format";

export function SiteSummaryPanel() {
  const { pages } = useRunState();
  const visible = pages.slice(-8).reverse();

  return (
    <div className="mb-3.5 rounded-lg border border-slate-200 bg-white p-3.25 px-3.75">
      <h2 className="m-0 mb-2 text-[10.5px] font-bold tracking-wide text-slate-400 uppercase">
        Site <span className="font-medium text-slate-400 normal-case">— forms · buttons · nav links</span>
      </h2>
      {pages.length === 0 ? (
        <span className="text-xs text-slate-400 italic">no data yet</span>
      ) : (
        <>
          {visible.map((p, i) => (
            <div key={i} className="flex items-baseline justify-between gap-2.5 border-t border-slate-200 py-1.5 first:border-t-0">
              <div className="min-w-0 flex-1 truncate font-mono text-[11.5px]" title={p.url}>
                {pathOf(p.url)}
              </div>
              <div
                className="shrink-0 text-[10.5px] text-slate-400"
                title={`${p.forms} form(s) · ${p.buttons} button(s) · ${p.nav_links} nav link(s)`}
              >
                {p.forms}f · {p.buttons}b · {p.nav_links}n
              </div>
            </div>
          ))}
          {pages.length > 8 ? (
            <div className="pt-2 text-[11px] text-slate-400">+ {pages.length - 8} more</div>
          ) : null}
        </>
      )}
    </div>
  );
}
