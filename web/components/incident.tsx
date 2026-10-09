"use client";

import Link from "next/link";
import { Badge } from "./ui";
import { actionLabel, ago, fmtNum, fmtSecs, fmtTime } from "@/lib/format";
import type { ActionMsg, IncidentMsg, PlanMsg, StepMsg } from "@/lib/types";

const ACTION_TEXT: Record<string, string> = {
  executed: "Executed", failed: "Execution failed", verified: "Verified: alerts cleared",
  unresolved: "Still firing after verification", escalated: "Escalated to a human",
  pending_approval: "Waiting for approval", approved: "Approved by operator", rejected: "Rejected by operator",
  skipped: "Skipped", dry_run: "Dry run (not executed)",
};

/** The analysis: root cause, type, confidence, evidence, the explanation, and the actions. */
export function PlanView({ plan, compact = false }: { plan: PlanMsg; compact?: boolean }) {
  const conf = typeof plan.confidence === "number" ? plan.confidence : null;
  return (
    <div className="rounded-md border border-line p-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted">Attempt {plan.attempt ?? 1}</span>
        <Badge status={plan.source ?? "unknown"} label={plan.source === "llm" ? `LLM${plan.model ? ` · ${plan.model}` : ""}` : `runbook${plan.runbook ? ` · ${plan.runbook}` : ""}`} />
        {plan.fallback_reason && <span className="text-xs text-muted">fallback: {plan.fallback_reason}</span>}
        {typeof plan.latency_ms === "number" && <span className="text-xs text-muted">analysis took {fmtSecs(plan.latency_ms / 1000)}</span>}
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-4">
        <Field k="Root cause" v={<b>{plan.root_cause_service ?? "unknown"}</b>} />
        <Field k="Incident type" v={(plan.incident_type ?? "–").replace(/_/g, " ")} />
        <Field k="Severity" v={plan.severity ?? "–"} />
        <Field k="Confidence" v={
          <div className="flex items-center gap-2">
            <div className="h-1.5 w-16 overflow-hidden rounded bg-line" aria-hidden>
              <div className={`h-full ${conf !== null && conf >= 0.7 ? "bg-ok" : "bg-warn"}`} style={{ width: `${(conf ?? 0) * 100}%` }} />
            </div>
            <span className="tabular">{fmtNum(conf, 2)}</span>
            {conf !== null && conf < 0.7 && <span className="text-xs text-muted">(below 0.7)</span>}
          </div>
        } />
      </div>
      <div className="mt-2 text-sm">
        <span className="text-muted">Recommended: </span><b>{actionLabel(plan.recommended_action)}</b>
        {plan.fallback_action && <><span className="text-muted"> · fallback: </span>{actionLabel(plan.fallback_action)}</>}
      </div>
      {plan.probable_cause && <p className="mt-2 text-sm">{plan.probable_cause}</p>}
      {!compact && (plan.evidence?.length ?? 0) > 0 && (
        <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm text-muted">
          {plan.evidence!.map((e, i) => <li key={i}>{e}</li>)}
        </ul>
      )}
      {!compact && plan.explanation && <p className="mt-2 text-sm text-muted">{plan.explanation}</p>}
    </div>
  );
}

function Field({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs text-muted">{k}</div>
      <div className="text-sm">{v}</div>
    </div>
  );
}

export function ActionLine({ a }: { a: ActionMsg }) {
  return (
    <div className="flex flex-wrap items-start gap-2 py-1 text-sm">
      <span className="tabular w-16 shrink-0 text-xs text-muted">{fmtTime(a.at ?? a.received_at)}</span>
      <Badge status={a.status} />
      <span>
        <b>{ACTION_TEXT[a.status] ?? a.status}</b>
        {a.action && <> · {actionLabel(a.action)}</>}
        {a.reason && <span className="text-muted"> · {a.reason}</span>}
        {a.detail && <span className="text-muted"> · {a.detail}</span>}
        {typeof a.open_to_verified_s === "number" && <span className="text-muted"> · {fmtSecs(a.open_to_verified_s)} after the incident opened</span>}
      </span>
    </div>
  );
}

/** Compact card for the live feed. */
export function IncidentCard({ inc, steps }: { inc: IncidentMsg; steps: StepMsg[] }) {
  const plans = steps.filter((s): s is PlanMsg => s.type === "response_plan");
  const actions = steps.filter((s): s is ActionMsg => s.type === "action");
  const plan = plans[plans.length - 1];
  const firing = (inc.alerts ?? []).filter((a) => a.status !== "resolved");
  return (
    <div className="rounded-md border border-line p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link href={`/incidents/${encodeURIComponent(inc.incident_id)}`} className="font-mono text-sm font-semibold hover:underline">
          {inc.incident_id}
        </Link>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted">opened {ago(inc.opened_at)}</span>
          <Badge status={inc.status} />
        </div>
      </div>
      <div className="mt-1 flex flex-wrap gap-1.5 text-xs">
        {(firing.length ? firing : inc.alerts ?? []).map((a, i) => (
          <span key={i} className="rounded border border-line px-1.5 py-0.5">
            {a.name} · {a.service}{a.status === "resolved" ? " (cleared)" : ""}
          </span>
        ))}
        {(inc.ml_anomalies ?? []).map((m, i) => (
          <span key={`ml${i}`} className="rounded border border-line px-1.5 py-0.5">ML anomaly · {m.service}</span>
        ))}
      </div>
      {plan ? <div className="mt-2"><PlanView plan={plan} compact /></div>
        : inc.status !== "resolved" && <p className="mt-2 text-xs text-muted">Analyzing…</p>}
      {actions.length > 0 && <div className="mt-1 divide-y divide-line/60">{actions.slice(-4).map((a, i) => <ActionLine key={i} a={a} />)}</div>}
    </div>
  );
}
