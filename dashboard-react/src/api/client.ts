import type { FinalReport } from "../types/report";

export interface RunSummary {
  run_id: string;
  url: string;
  status: string;
  started_at: number;
  finished_at: number | null;
}

export interface StartRunRequest {
  url: string;
  prd_path?: string | null;
  focus_hint?: string | null;
  credentials?: Record<string, string> | null;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* non-JSON error body, keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export function startRun(req: StartRunRequest): Promise<RunSummary> {
  return request<RunSummary>("/api/runs", { method: "POST", body: JSON.stringify(req) });
}

export function listRuns(): Promise<RunSummary[]> {
  return request<RunSummary[]>("/api/runs");
}

export function getCurrentRun(): Promise<RunSummary | null> {
  return request<RunSummary | null>("/api/runs/current");
}

export interface ReportListEntry {
  timestamp: string;
  report: FinalReport;
}

export function listReports(): Promise<ReportListEntry[]> {
  return request<ReportListEntry[]>("/api/reports");
}
