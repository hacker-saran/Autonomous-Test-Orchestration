import type {
  CriticVerdictEvent,
  FlowStepView,
  HealerVerdictEvent,
  PipelineEvent,
  TestExecutedEvent,
} from "../types/events";
import type { ConnectionStatus } from "../hooks/useEventSocket";

export interface FlowMeta {
  title: string;
  category: string;
  steps: FlowStepView[];
  file_path: string;
  command: string;
  validation_status: string;
}

export interface RunState {
  connectionStatus: ConnectionStatus;
  currentPhase: string | null;
  isRunActive: boolean;
  events: PipelineEvent[];
  pages: Extract<PipelineEvent, { type: "page_crawled" }>[];
  flowCategories: string[];
  flowCount: number;
  flowMeta: Record<string, FlowMeta>;
  criticVerdict: CriticVerdictEvent | null;
  execResults: Record<string, TestExecutedEvent>;
  healerVerdicts: HealerVerdictEvent[];
  selectedFlowId: string | null;
}

export const initialRunState: RunState = {
  connectionStatus: "connecting",
  currentPhase: null,
  isRunActive: false,
  events: [],
  pages: [],
  flowCategories: [],
  flowCount: 0,
  flowMeta: {},
  criticVerdict: null,
  execResults: {},
  healerVerdicts: [],
  selectedFlowId: null,
};

export type Action =
  | { kind: "ws_status"; status: ConnectionStatus }
  | { kind: "event"; event: PipelineEvent }
  | { kind: "select_flow"; flowId: string }
  | { kind: "set_run_active"; active: boolean };

export function runReducer(state: RunState, action: Action): RunState {
  if (action.kind === "ws_status") {
    return { ...state, connectionStatus: action.status };
  }
  if (action.kind === "select_flow") {
    return { ...state, selectedFlowId: action.flowId };
  }
  if (action.kind === "set_run_active") {
    return { ...state, isRunActive: action.active };
  }

  const ev = action.event;
  const events = [...state.events, ev];

  // UnknownEvent.type is plain `string`, not a literal, so it can't be
  // excluded from a single-literal switch case below purely by discriminant
  // narrowing — exclude it explicitly first via its distinguishing shape.
  if ("data" in ev) {
    return { ...state, events };
  }

  switch (ev.type) {
    case "run_started":
      return {
        ...initialRunState,
        connectionStatus: state.connectionStatus,
        isRunActive: true,
        events,
      };

    case "phase":
      return { ...state, events, currentPhase: ev.phase };

    case "page_crawled":
      return { ...state, events, pages: [...state.pages, ev] };

    case "crawl_done":
      return { ...state, events };

    case "plan_produced":
      return {
        ...state,
        events,
        flowCategories: ev.categories,
        flowCount: ev.flow_count,
      };

    case "critic_verdict":
      return { ...state, events, criticVerdict: ev };

    case "test_generated":
      return {
        ...state,
        events,
        flowMeta: {
          ...state.flowMeta,
          [ev.flow_id]: {
            title: ev.title,
            category: ev.category,
            steps: ev.steps,
            file_path: ev.file_path,
            command: ev.command,
            validation_status: ev.validation_status,
          },
        },
      };

    case "test_executed":
      return {
        ...state,
        events,
        execResults: { ...state.execResults, [ev.flow_id]: ev },
      };

    case "healer_verdict":
      return { ...state, events, healerVerdicts: [...state.healerVerdicts, ev] };

    case "escalation":
      return { ...state, events };

    case "run_finished":
      return { ...state, events, isRunActive: false };

    default:
      return { ...state, events };
  }
}
