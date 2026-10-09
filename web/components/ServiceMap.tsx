"use client";

// frontend -> api-service -> redis with live values. A service is "down" when
// Prometheus says up == 0, "alerting" while an open incident has a firing alert
// on it, and the latest plan's root cause is marked so cause and symptom differ.
import { Sparkline, SERVICE_COLOR } from "./charts";
import { Badge } from "./ui";
import { fmtBytes, fmtLatency, fmtNum, fmtPct } from "@/lib/format";
import { useLive } from "@/lib/live";
import { SERVICES, type MetricsResponse, type PlanMsg } from "@/lib/types";

export function ServiceMap({ metrics }: { metrics: MetricsResponse | null }) {
  const { incidents, steps } = useLive();
  const firing: Record<string, string[]> = {};
  const rootCause = new Set<string>();
  for (const inc of incidents.values()) {
    if (inc.status === "resolved") continue;
    for (const a of inc.alerts ?? []) {
      if (a.status !== "resolved" && a.service) (firing[a.service] ??= []).push(a.name);
    }
    const plans = (steps.get(inc.incident_id) ?? []).filter((s): s is PlanMsg => s.type === "response_plan");
    const root = plans[plans.length - 1]?.root_cause_service;
    if (root) rootCause.add(root);
  }

  return (
    <div className="flex flex-col items-stretch gap-2 md:flex-row">
      {SERVICES.map((svc, i) => {
        const m = metrics?.services[svc];
        const c = m?.current ?? {};
        const up = c.up;
        const names = [...new Set(firing[svc] ?? [])];
        const state = up === 0 ? "down" : names.length ? "firing" : up === 1 ? "healthy" : "unknown";
        const border = state === "down" || state === "firing" ? "border-bad" : state === "healthy" ? "border-ok/60" : "border-line";
        const trend = (svc === "redis" ? m?.series.ops : m?.series.p95)?.map(([, v]) => v) ?? [];
        return (
          <div key={svc} className="flex flex-1 flex-col items-stretch gap-2 md:flex-row">
            {i > 0 && <div aria-hidden className="self-center text-lg text-muted md:px-1">{"→"}</div>}
            <div className={`flex-1 rounded-lg border-2 bg-card p-3 ${border}`}>
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: SERVICE_COLOR[svc] }} />
                  <span className="font-semibold">{svc}</span>
                </div>
                <Badge status={state === "firing" ? "firing" : state} label={state === "firing" ? "alerting" : undefined} />
              </div>
              {rootCause.has(svc) && <div className="mt-1 text-xs font-semibold text-bad">⚑ root cause (latest plan)</div>}
              {names.length > 0 && <div className="mt-1 text-xs text-muted">{names.join(", ")}</div>}
              <dl className="tabular mt-2 grid grid-cols-3 gap-x-2 gap-y-1 text-xs">
                {svc === "redis" ? (
                  <>
                    <Stat k="ops/s" v={fmtNum(c.ops ?? null, 1)} />
                    <Stat k="memory" v={fmtBytes(c.mem_bytes ?? null)} />
                    <Stat k="clients" v={fmtNum(c.clients ?? null, 0)} />
                  </>
                ) : (
                  <>
                    <Stat k="req/s" v={fmtNum(c.rps ?? null, 1)} />
                    <Stat k="p95" v={fmtLatency(c.p95 ?? null)} />
                    <Stat k="errors" v={fmtPct(c.err ?? null, 1)} />
                    <Stat k="upstream p95" v={fmtLatency(c.upstream_p95 ?? null)} />
                    <Stat k="cpu" v={fmtPct(c.cpu ?? null)} />
                    <Stat k="mem" v={fmtPct(c.mem ?? null)} />
                  </>
                )}
              </dl>
              <div className="mt-2">
                <div className="text-[10px] uppercase tracking-wide text-muted">{svc === "redis" ? "ops/s" : "p95 latency"}, last 15 min</div>
                <Sparkline points={trend} color={SERVICE_COLOR[svc]} />
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Stat({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <dt className="text-muted">{k}</dt>
      <dd className="font-semibold">{v}</dd>
    </div>
  );
}
