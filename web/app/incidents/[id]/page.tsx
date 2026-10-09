"use client";

// One incident end to end: detection (alerts, ML anomalies) -> context the
// analyzer saw -> plan(s) with reasoning -> policy decisions and actions ->
// verification, re-analysis or escalation. From the incident store, so it
// works for past incidents too.
import Link from "next/link";
import { use } from "react";
import { Legend, ServiceLineChart } from "@/components/charts";
import { ActionLine, PlanView } from "@/components/incident";
import { Badge, Card, Empty, ErrorNote, KV } from "@/components/ui";
import { fmtBytes, fmtDateTime, fmtLatency, fmtNum, fmtPct, fmtPctAuto, fmtTime } from "@/lib/format";
import { usePoll } from "@/lib/live";
import type { ActionMsg, IncidentMsg, PlanMsg, ServiceContext, TimelineMsg } from "@/lib/types";

const TREND_X = (x: number) => (x === 0 ? "event" : `${x} min`);

function trendSeries(ctx: Record<string, ServiceContext | null> | undefined, metric: string, services: string[]) {
  return Object.fromEntries(services.map((s) => {
    const pts = ctx?.[s]?.trend?.[metric] ?? [];
    const n = pts.length;
    return [s, pts.map((v, i) => [i - (n - 1), v] as [number, number | null])];
  }));
}

export default function IncidentDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, error } = usePoll<TimelineMsg[]>(`/api/gateway/history/${encodeURIComponent(id)}`, 3000, [id]);

  if (error && !data) {
    return <div className="space-y-3"><Back /><ErrorNote error={`Could not load ${id}: ${error}`} /></div>;
  }
  if (!data) return <div className="space-y-3"><Back /><Empty>Loading…</Empty></div>;

  const incs = data.filter((m): m is IncidentMsg => m.type === "incident");
  const first = incs.find((m) => m.status === "open") ?? incs[0];
  const last = incs[incs.length - 1];
  // The context the analyzer saw for the first plan
  const ctxMsg = first ?? last;
  const services = Object.keys(ctxMsg?.context ?? {});
  const apps = services.filter((s) => s !== "redis");
  const steps = data.filter((m): m is PlanMsg | ActionMsg => m.type === "response_plan" || m.type === "action");
  const alerts = new Map<string, { name: string; service?: string | null; status?: string; value?: number | null; threshold?: number | null; startsAt?: string | null }>();
  for (const inc of incs) for (const a of inc.alerts ?? []) alerts.set(`${a.name}/${a.service}`, a);
  const anomalies = incs.flatMap((i) => i.ml_anomalies ?? []);

  return (
    <div className="space-y-4">
      <Back />
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-mono text-lg font-semibold">{id}</h1>
        <Badge status={last?.status} />
        <span className="text-sm text-muted">
          opened {fmtDateTime(first?.opened_at)}{last?.resolved_at ? ` · resolved ${fmtDateTime(last.resolved_at)}` : ""}
          {" · "}sources {(last?.sources ?? []).join(" + ") || "–"}
        </span>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="1 · Detection" className="lg:col-span-1">
          {[...alerts.values()].map((a) => (
            <div key={`${a.name}/${a.service}`} className="flex items-center justify-between gap-2 border-b border-line/60 py-1.5 text-sm last:border-0">
              <span><b>{a.name}</b> <span className="text-muted">on {a.service}</span></span>
              <span className="flex items-center gap-2">
                {a.status !== "resolved" && a.value != null && (
                  <span className="tabular text-xs text-muted">{fmtNum(a.value, 3)}{a.threshold != null ? ` > ${a.threshold}` : ""}</span>
                )}
                <Badge status={a.status === "resolved" ? "resolved" : "firing"} />
              </span>
            </div>
          ))}
          {anomalies.map((m, i) => (
            <div key={i} className="border-b border-line/60 py-1.5 text-sm last:border-0">
              <b>ML anomaly</b> <span className="text-muted">on {m.service} · score {fmtNum(m.score ?? null, 2)} · {(m.top_features ?? []).join(", ")}</span>
            </div>
          ))}
          {!alerts.size && !anomalies.length && <Empty>No alerts recorded.</Empty>}
        </Card>

        <Card title="2 · Context the analyzer saw" className="lg:col-span-2">
          {!services.length ? <Empty>No context recorded.</Empty> : (
            <>
              <div className="tabular grid gap-3 sm:grid-cols-3">
                {services.map((s) => {
                  const c = ctxMsg?.context?.[s] ?? {};
                  return (
                    <div key={s} className="rounded-md border border-line p-2">
                      <div className="mb-1 font-semibold">{s}</div>
                      <KV k="up" v={c.up === 1 ? "yes" : c.up === 0 ? "no" : "–"} />
                      {s === "redis" ? (
                        <>
                          <KV k="ops/s" v={fmtNum(c.ops ?? null, 1)} />
                          <KV k="memory" v={fmtBytes(c.mem_bytes ?? null)} />
                        </>
                      ) : (
                        <>
                          <KV k="p95" v={fmtLatency(c.p95 ?? null)} />
                          <KV k="upstream p95" v={fmtLatency(c.upstream_p95 ?? null)} />
                          <KV k="errors" v={fmtPct(c.err ?? null, 1)} />
                          <KV k="req/s" v={fmtNum(c.rps ?? null, 1)} />
                        </>
                      )}
                      <KV k="container" v={`${c.container?.status ?? "–"}${c.container?.restart_count ? ` · ${c.container.restart_count} restarts` : ""}`} />
                    </div>
                  );
                })}
              </div>
              <div className="mt-3 flex items-center justify-between gap-2">
                <span className="text-xs text-muted">Last 10 minutes before the event, one point per minute</span>
                <Legend services={apps} />
              </div>
              <div className="mt-2 grid gap-3 sm:grid-cols-2">
                <div><div className="text-xs text-muted">p95 latency</div>
                  <ServiceLineChart series={trendSeries(ctxMsg?.context, "p95", apps)} format={fmtLatency} xFormat={TREND_X} height={130} threshold={{ value: 1, label: "1 s" }} /></div>
                <div><div className="text-xs text-muted">Upstream p95</div>
                  <ServiceLineChart series={trendSeries(ctxMsg?.context, "upstream_p95", apps)} format={fmtLatency} xFormat={TREND_X} height={130} /></div>
                <div><div className="text-xs text-muted">Error rate</div>
                  <ServiceLineChart series={trendSeries(ctxMsg?.context, "err", apps)} format={fmtPctAuto} cap={1} xFormat={TREND_X} height={130} threshold={{ value: 0.1, label: "10%" }} /></div>
                <div><div className="text-xs text-muted">Requests per second</div>
                  <ServiceLineChart series={trendSeries(ctxMsg?.context, "rps", apps)} format={(v) => (v === null ? "–" : v.toFixed(1))} xFormat={TREND_X} height={130} /></div>
              </div>
            </>
          )}
        </Card>
      </div>

      <Card title="3 · Analysis, decisions and verification">
        {!steps.length ? <Empty>No plan yet.</Empty> : (
          <ol className="space-y-3">
            {steps.map((s, i) => (
              <li key={i}>
                {s.type === "response_plan" ? (
                  <div>
                    <div className="mb-1 text-xs text-muted">{fmtTime(s.received_at ?? s.created_at)} · response plan</div>
                    <PlanView plan={s} />
                  </div>
                ) : <ActionLine a={s} />}
              </li>
            ))}
          </ol>
        )}
      </Card>
    </div>
  );
}

function Back() {
  return <Link href="/incidents" className="text-sm text-info hover:underline">← All incidents</Link>;
}
