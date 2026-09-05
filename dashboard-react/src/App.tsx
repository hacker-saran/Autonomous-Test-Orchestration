import { useCallback } from "react";
import { Header } from "./components/Header";
import { KpiRow } from "./components/KpiRow";
import { PhaseStepper } from "./components/PhaseStepper";
import { EventFeed } from "./components/EventFeed";
import { TestDetailPanel } from "./components/TestDetailPanel";
import { SiteSummaryPanel } from "./components/SiteSummaryPanel";
import { PlanSummaryPanel } from "./components/PlanSummaryPanel";
import { ExecutionSummaryPanel } from "./components/ExecutionSummaryPanel";
import { HealerSummaryPanel } from "./components/HealerSummaryPanel";
import { NewRunForm } from "./components/NewRunForm";
import { useEventSocket, type ConnectionStatus } from "./hooks/useEventSocket";
import { useRunDispatch } from "./state/RunContext";
import type { PipelineEvent } from "./types/events";

const WS_URL = `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws`;

function Dashboard() {
  const dispatch = useRunDispatch();

  const onEvent = useCallback((event: PipelineEvent) => dispatch({ kind: "event", event }), [dispatch]);
  const onStatus = useCallback(
    (status: ConnectionStatus) => dispatch({ kind: "ws_status", status }),
    [dispatch],
  );
  useEventSocket(WS_URL, onEvent, onStatus);

  return (
    <>
      <Header />
      <KpiRow />
      <PhaseStepper />
      <main className="grid h-[calc(100vh-165px)] grid-cols-[1fr_440px] gap-4 px-7 pt-4 pb-6">
        <div className="min-h-0">
          <EventFeed />
        </div>
        <div className="min-h-0 overflow-y-auto">
          <NewRunForm />
          <TestDetailPanel />
          <SiteSummaryPanel />
          <PlanSummaryPanel />
          <ExecutionSummaryPanel />
          <HealerSummaryPanel />
        </div>
      </main>
    </>
  );
}

export default function App() {
  return <Dashboard />;
}
