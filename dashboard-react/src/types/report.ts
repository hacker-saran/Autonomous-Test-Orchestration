// Mirrors orchestrator/schemas.py's FinalReport / HealerVerdict.

export interface HealerVerdict {
  flow_id: string;
  classification: "script_issue" | "app_defect" | "flaky_env" | "ambiguous";
  confidence: number;
  evidence: Record<string, unknown>;
  action_taken: "auto_repaired" | "reported" | "retried" | "escalated";
  rationale: string;
  repair_diff: string | null;
}

export interface FinalReport {
  flows_planned: number;
  flows_by_category: Record<string, number>;
  pass_count: number;
  fail_count: number;
  healer_actions: HealerVerdict[];
  coverage_gaps_remaining: string[];
  untested_flow_risk: string[];
  prd_gap_analysis: Record<string, unknown>[] | null;
  escalations: string[];
}
