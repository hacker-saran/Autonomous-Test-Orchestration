// Mirrors orchestrator/schemas.py's FlowStep/Flow and the exact
// live_events.emit(...) call sites in orchestrator/orchestrator.py.

export interface FlowStepView {
  action: "navigate" | "click" | "fill" | "select" | "assert_visible" | "assert_text" | "assert_url";
  target_description: string;
  value: string | null;
  expected_outcome: string | null;
}

export interface RunStartedEvent {
  type: "run_started";
  ts: number;
  url: string;
  has_prd: boolean;
  focus_hint: string | null;
}

export interface PhaseEvent {
  type: "phase";
  ts: number;
  phase: string;
  url?: string;
  iteration?: number;
  flow_count?: number;
  test_count?: number;
}

export interface PageCrawledEvent {
  type: "page_crawled";
  ts: number;
  url: string;
  title: string;
  forms: number;
  buttons: number;
  nav_links: number;
}

export interface CrawlDoneEvent {
  type: "crawl_done";
  ts: number;
  pages: number;
  partial: boolean;
  notes: string[];
}

export interface PlanProducedEvent {
  type: "plan_produced";
  ts: number;
  iteration: number;
  flow_count: number;
  categories: string[];
}

export interface CriticVerdictEvent {
  type: "critic_verdict";
  ts: number;
  iteration: number;
  decision: "proceed" | "re_plan" | "escalate";
  overall_score: number;
  gaps: string[];
  dimension_scores: Record<string, string>;
}

export interface TestGeneratedEvent {
  type: "test_generated";
  ts: number;
  flow_id: string;
  category: string;
  title: string;
  validation_status: "validated" | "unresolved";
  file_path: string;
  command: string;
  steps: FlowStepView[];
}

export interface TestExecutedEvent {
  type: "test_executed";
  ts: number;
  flow_id: string;
  status: "pass" | "fail" | "error";
  duration_ms: number;
  screenshot_url: string | null;
}

export interface HealerVerdictEvent {
  type: "healer_verdict";
  ts: number;
  flow_id: string;
  classification: "script_issue" | "app_defect" | "flaky_env" | "ambiguous";
  confidence: number;
  action_taken: "auto_repaired" | "reported" | "retried" | "escalated";
  rationale: string;
}

export interface EscalationEvent {
  type: "escalation";
  ts: number;
  stage: string;
  detail: string;
  flow_id?: string;
}

export interface RunFinishedEvent {
  type: "run_finished";
  ts: number;
  pass_count: number;
  fail_count: number;
  flows_planned: number;
  escalations: string[];
}

// Deliberately NOT `[key: string]: unknown` — an index signature makes every
// other union member structurally assignable to this one too, which defeats
// switch(ev.type) narrowing entirely. `data: Record<string, unknown>` keeps
// the catch-all real without that.
export interface UnknownEvent {
  type: string;
  ts: number;
  data: Record<string, unknown>;
}

export type PipelineEvent =
  | RunStartedEvent
  | PhaseEvent
  | PageCrawledEvent
  | CrawlDoneEvent
  | PlanProducedEvent
  | CriticVerdictEvent
  | TestGeneratedEvent
  | TestExecutedEvent
  | HealerVerdictEvent
  | EscalationEvent
  | RunFinishedEvent
  | UnknownEvent;

export const PHASES = [
  "EXPLORING",
  "PLANNING",
  "CRITIQUE",
  "GENERATING",
  "EXECUTING",
  "HEALING",
  "REPORTING",
] as const;
