// Message shapes from the gateway and responder (analyzer/schemas.py is the source of truth).
// Everything is optional: the dashboard must render whatever arrives.

export const SERVICES = ["frontend", "api-service", "redis"] as const;
export type Service = (typeof SERVICES)[number];

export interface Alert {
  name: string;
  service?: string | null;
  status?: string;
  severity?: string | null;
  category?: string | null;
  startsAt?: string | null;
  value?: number | null;
  threshold?: number | null;
}

export interface MLAnomaly {
  service: string;
  score?: number | null;
  top_features?: string[];
}

export interface ServiceContext {
  up?: number | null;
  cpu?: number | null;
  mem?: number | null;
  p95?: number | null;
  err?: number | null;
  rps?: number | null;
  upstream_p95?: number | null;
  ops?: number | null;
  mem_bytes?: number | null;
  clients?: number | null;
  container?: { status?: string | null; restart_count?: number | null; started_at?: string | null } | null;
  trend?: Record<string, (number | null)[]>;
}

export interface IncidentMsg {
  type: "incident";
  incident_id: string;
  status: string; // open | updated | reanalyze | resolved
  timestamp?: string;
  opened_at?: string;
  resolved_at?: string | null;
  sources?: string[];
  services?: string[];
  alerts?: Alert[];
  ml_anomalies?: MLAnomaly[];
  topology?: Record<string, string[]>;
  context?: Record<string, ServiceContext | null>;
  history?: { attempt?: number; previous_actions?: unknown[] };
  channel?: string;
}

export interface Action {
  type: string;
  target?: string | null;
}

export interface PlanMsg {
  type: "response_plan";
  incident_id: string;
  root_cause_service?: string | null;
  incident_type?: string;
  severity?: string;
  probable_cause?: string;
  evidence?: string[];
  confidence?: number;
  recommended_action?: Action;
  fallback_action?: Action | null;
  explanation?: string;
  source?: "llm" | "runbook";
  model?: string | null;
  runbook?: string | null;
  fallback_reason?: string | null;
  attempt?: number;
  latency_ms?: number;
  created_at?: string;
  received_at?: string;
  channel?: string;
}

export interface ActionMsg {
  type: "action";
  incident_id: string;
  status: string; // executed | failed | verified | unresolved | escalated | pending_approval | approved | rejected | skipped | dry_run
  action?: Action | null;
  attempt?: number;
  plan_source?: string | null;
  reason?: string | null;
  detail?: string | null;
  at?: string;
  received_at?: string;
  approval_id?: string;
  open_to_verified_s?: number;
  channel?: string;
}

export type StepMsg = PlanMsg | ActionMsg;
export type TimelineMsg = IncidentMsg | StepMsg | ({ type: "alert" } & Record<string, unknown>);

export interface Approval {
  approval_id: string;
  plan: PlanMsg;
  action: Action;
  reason?: string;
  created_at?: string;
}

export interface HistoryRow {
  incident_id: string;
  first_at: string;
  last_at: string;
  status: string | null;
}

// /api/metrics
export type MetricName = "up" | "cpu" | "mem" | "p95" | "err" | "rps" | "upstream_p95" | "ops" | "mem_bytes" | "clients";
export interface ServiceMetrics {
  current: Partial<Record<MetricName, number | null>>;
  series: Partial<Record<MetricName, [number, number | null][]>>; // [unix seconds, value]
}
export interface MetricsResponse {
  ok: boolean;
  error?: string;
  services: Record<string, ServiceMetrics>;
}

// /api/stats
export interface IncidentSummary {
  incident_id: string;
  opened_at: string | null;
  status: string | null;
  services: string[];
  root_cause: string | null;
  incident_type: string | null;
  source: string | null;
  action: string | null;
  outcome: string; // verified | escalated | failed | pending_approval | rejected | in_progress | no_action
  attempts: number;
  plan_latency_ms: number | null;
  time_to_plan_s: number | null;
  open_to_verified_s: number | null;
}
export interface StatsResponse {
  ok: boolean;
  error?: string;
  total: number;
  open: number;
  auto_resolved: number;
  escalated: number;
  awaiting_approval: number;
  plans: { llm: number; runbook: number };
  mean_llm_latency_s: number | null;
  mean_time_to_plan_s: number | null;
  mean_open_to_verified_s: number | null;
  actions_by_status: Record<string, number>;
  outcomes: Record<string, number>;
  incidents: IncidentSummary[];
}

// /api/system
export interface ComponentStatus {
  name: string;
  role: string;
  ok: boolean | null; // null = unknown
  detail: string;
}
export interface SystemResponse {
  components: ComponentStatus[];
  targets: { job: string; instance: string; health: string; lastError?: string }[];
  firing: { alertname: string; service: string; severity: string; startsAt: string; summary: string }[];
  policies: Record<string, unknown> | null;
}
