import { useRunState } from "../state/RunContext";

const STATUS_LABEL: Record<string, string> = {
  connecting: "Connecting…",
  live: "Live",
  disconnected: "Disconnected",
};

export function Header({ onOpenReports }: { onOpenReports: () => void }) {
  const { connectionStatus } = useRunState();
  const isLive = connectionStatus === "live";

  return (
    <header className="flex h-14 items-center justify-between border-b border-slate-200 bg-white px-7">
      <div className="flex items-center gap-2.5">
        <div className="h-[22px] w-[22px] shrink-0 rounded-md bg-linear-to-br from-purple to-[#8b7bff]" />
        <h1 className="m-0 text-[14.5px] font-semibold tracking-tight">Autonomous Test Orchestration</h1>
      </div>
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onOpenReports}
          className="rounded-md px-2.5 py-1.5 text-[12.5px] font-medium text-slate-500 hover:bg-slate-100 hover:text-slate-700"
        >
          Reports
        </button>
        <span
          className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${
            isLive ? "bg-green-bg text-green" : "bg-slate-100 text-slate-500"
          }`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${isLive ? "bg-green" : "bg-slate-400"}`} />
          {STATUS_LABEL[connectionStatus]}
        </span>
      </div>
    </header>
  );
}
