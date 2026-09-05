import { PHASES } from "../types/events";
import { useRunState } from "../state/RunContext";

export function PhaseStepper() {
  const { currentPhase } = useRunState();
  const activeIdx = currentPhase ? PHASES.indexOf(currentPhase as (typeof PHASES)[number]) : -1;

  return (
    <div className="px-7 pt-4.5 pb-1">
      <div className="flex items-center">
        {PHASES.map((phase, i) => {
          const done = activeIdx > i;
          const active = activeIdx === i;
          return (
            <div key={phase} className={`flex items-center ${i < PHASES.length - 1 ? "flex-1" : ""}`}>
              <div
                className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 text-[9.5px] font-bold transition-colors ${
                  done
                    ? "border-green bg-green text-white"
                    : active
                      ? "border-purple bg-purple text-white shadow-[0_0_0_4px_var(--color-purple-bg)]"
                      : "border-slate-300 bg-white text-slate-400"
                }`}
              >
                {i + 1}
              </div>
              <div
                className={`ml-1.75 text-[10.5px] font-semibold tracking-wide whitespace-nowrap uppercase transition-colors ${
                  active ? "text-purple" : done ? "text-slate-600" : "text-slate-400"
                }`}
              >
                {phase}
              </div>
              {i < PHASES.length - 1 && (
                <div className={`mx-2.5 h-px flex-1 transition-colors ${done ? "bg-green" : "bg-slate-300"}`} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
