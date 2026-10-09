// Operational statistics from the gateway's incident store (GET /history,
// /history/{id}). These are what the system itself observed: time from
// incident open to plan, open to verified, outcomes, LLM vs runbook.
// The evaluation's MTTD/MTTR need the injector's ground truth and come from
// experiments/score.py, not from here.
import { NextResponse } from "next/server";
import { GATEWAY_URL, fetchJson } from "@/lib/config";
import type { ActionMsg, HistoryRow, IncidentMsg, IncidentSummary, PlanMsg, StatsResponse, TimelineMsg } from "@/lib/types";

export const dynamic = "force-dynamic";

const secs = (a?: string | null, b?: string | null) =>
  a && b ? (Date.parse(b) - Date.parse(a)) / 1000 : null;
const mean = (xs: (number | null)[]) => {
  const v = xs.filter((x): x is number => x !== null && Number.isFinite(x));
  return v.length ? v.reduce((s, x) => s + x, 0) / v.length : null;
};

function summarize(row: HistoryRow, timeline: TimelineMsg[]): IncidentSummary {
  const incs = timeline.filter((m): m is IncidentMsg => m.type === "incident");
  const plans = timeline.filter((m): m is PlanMsg => m.type === "response_plan");
  const actions = timeline.filter((m): m is ActionMsg => m.type === "action");
  const first = incs[0];
  const last = incs[incs.length - 1];
  const plan = plans[0];
  const statuses = actions.map((a) => a.status);
  const verified = actions.find((a) => a.status === "verified");
  const lastAction = actions[actions.length - 1];

  let outcome = "no_action";
  if (verified) outcome = "verified";
  else if (statuses.includes("escalated")) outcome = "escalated";
  else if (lastAction?.status === "pending_approval") outcome = "pending_approval";
  else if (statuses.includes("rejected")) outcome = "rejected";
  else if (statuses.includes("failed")) outcome = "failed";
  else if (actions.length || plans.length) outcome = "in_progress";

  const acted = actions.find((a) => a.status === "executed") ?? lastAction;
  return {
    incident_id: row.incident_id,
    opened_at: first?.opened_at ?? row.first_at,
    status: row.status,
    services: last?.services ?? [],
    root_cause: plan?.root_cause_service ?? null,
    incident_type: plan?.incident_type ?? null,
    source: plan?.source ?? null,
    action: acted?.action ? `${acted.action.type}${acted.action.target ? " " + acted.action.target : ""}` : null,
    outcome,
    attempts: Math.max(1, ...plans.map((p) => p.attempt ?? 1)),
    plan_latency_ms: plan?.latency_ms ?? null,
    time_to_plan_s: secs(first?.opened_at, plan?.received_at ?? plan?.created_at),
    open_to_verified_s: verified?.open_to_verified_s ?? null,
  };
}

export async function GET() {
  try {
    const rows = await fetchJson<HistoryRow[]>(`${GATEWAY_URL}/history`);
    const timelines = await Promise.all(
      rows.map((r) =>
        fetchJson<TimelineMsg[]>(`${GATEWAY_URL}/history/${encodeURIComponent(r.incident_id)}`).catch(() => []),
      ),
    );
    const incidents = rows.map((r, i) => summarize(r, timelines[i]));
    const allPlans = timelines.flat().filter((m): m is PlanMsg => m.type === "response_plan");
    const allActions = timelines.flat().filter((m): m is ActionMsg => m.type === "action");

    const count = <T,>(xs: T[], key: (x: T) => string) =>
      xs.reduce<Record<string, number>>((acc, x) => ((acc[key(x)] = (acc[key(x)] ?? 0) + 1), acc), {});

    const body: StatsResponse = {
      ok: true,
      total: incidents.length,
      open: incidents.filter((i) => i.status && i.status !== "resolved").length,
      auto_resolved: incidents.filter((i) => i.outcome === "verified").length,
      escalated: incidents.filter((i) => i.outcome === "escalated").length,
      awaiting_approval: incidents.filter((i) => i.outcome === "pending_approval").length,
      plans: {
        llm: allPlans.filter((p) => p.source === "llm").length,
        runbook: allPlans.filter((p) => p.source === "runbook").length,
      },
      mean_llm_latency_s: mean(allPlans.filter((p) => p.source === "llm").map((p) => (p.latency_ms ?? NaN) / 1000)),
      mean_time_to_plan_s: mean(incidents.map((i) => i.time_to_plan_s)),
      mean_open_to_verified_s: mean(incidents.map((i) => i.open_to_verified_s)),
      actions_by_status: count(allActions, (a) => a.status),
      outcomes: count(incidents, (i) => i.outcome),
      incidents,
    };
    return NextResponse.json(body);
  } catch (e) {
    return NextResponse.json({ ok: false, error: String(e) }, { status: 502 });
  }
}
