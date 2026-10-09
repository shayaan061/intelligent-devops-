"use client";

import Link from "next/link";
import { useState } from "react";
import { ApprovalQueue } from "@/components/Approvals";
import { Legend, ServiceLineChart } from "@/components/charts";
import { IncidentCard } from "@/components/incident";
import { ServiceMap } from "@/components/ServiceMap";
import { Card, Empty, ErrorNote, StatTile } from "@/components/ui";
import { fmtLatency, fmtPct, fmtPctAuto, fmtSecs } from "@/lib/format";
import { useLive, usePoll } from "@/lib/live";
import type { MetricName, MetricsResponse, StatsResponse } from "@/lib/types";

const RANGES = [5, 15, 30, 60];
const APPS = ["frontend", "api-service"];
const xTime = (x: number) => new Date(x * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

function pick(m: MetricsResponse | null, name: MetricName, services = APPS) {
  return Object.fromEntries(services.map((s) => [s, m?.services[s]?.series[name]]));
}

export default function Overview() {
  const [minutes, setMinutes] = useState(15);
  const { data: metrics, error: mErr } = usePoll<MetricsResponse>(`/api/metrics?minutes=${minutes}`, 5000);
  const { data: stats } = usePoll<StatsResponse>("/api/stats", 10000);
  const { incidents, steps } = useLive();

  const active = [...incidents.values()]
    .filter((i) => i.status !== "resolved")
    .sort((a, b) => (b.opened_at ?? "").localeCompare(a.opened_at ?? ""));
  const recent = [...incidents.values()]
    .filter((i) => i.status === "resolved")
    .sort((a, b) => (b.opened_at ?? "").localeCompare(a.opened_at ?? ""))
    .slice(0, 3);
  const acted = stats ? stats.incidents.filter((i) => i.outcome !== "no_action").length : 0;
  const plansTotal = stats ? stats.plans.llm + stats.plans.runbook : 0;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <StatTile label="Open incidents" value={active.length} hint={stats ? `${stats.total} in the store` : undefined} />
        <StatTile label="Auto-resolved" value={stats && acted ? fmtPct(stats.auto_resolved / acted) : "–"}
          hint={stats ? `${stats.auto_resolved} of ${acted} acted on` : undefined} />
        <StatTile label="Escalated" value={stats?.escalated ?? "–"} hint="sent to a human" />
        <StatTile label="Awaiting approval" value={stats?.awaiting_approval ?? "–"} />
        <StatTile label="Open → verified" value={fmtSecs(stats?.mean_open_to_verified_s)} hint="mean, incident opened to fix verified" />
        <StatTile label="Plans by LLM" value={plansTotal ? fmtPct(stats!.plans.llm / plansTotal) : "–"}
          hint={stats ? `${stats.plans.llm} LLM · ${stats.plans.runbook} runbook` : undefined} />
      </div>

      <Card title="Service map" action={<span className="text-xs text-muted">request path: frontend → api-service → redis</span>}>
        <ErrorNote error={mErr && `Metrics unavailable: ${mErr}`} />
        <ServiceMap metrics={metrics} />
      </Card>

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Card title={`Active incidents (${active.length})`} action={<Link href="/incidents" className="text-xs text-info hover:underline">All incidents →</Link>}>
            {active.length ? (
              <div className="space-y-3">{active.map((i) => <IncidentCard key={i.incident_id} inc={i} steps={steps.get(i.incident_id) ?? []} />)}</div>
            ) : (
              <Empty>No open incidents. Everything is healthy.</Empty>
            )}
            {recent.length > 0 && (
              <>
                <h3 className="mb-2 mt-4 text-xs font-semibold uppercase tracking-wide text-muted">Recently resolved</h3>
                <div className="space-y-3">{recent.map((i) => <IncidentCard key={i.incident_id} inc={i} steps={steps.get(i.incident_id) ?? []} />)}</div>
              </>
            )}
          </Card>
        </div>
        <Card title="Waiting for approval" action={<Link href="/approvals" className="text-xs text-info hover:underline">Details →</Link>}>
          <ApprovalQueue />
        </Card>
      </div>

      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">Live metrics</h2>
          <div className="flex rounded-md border border-line bg-card p-0.5 text-xs" role="group" aria-label="Time range">
            {RANGES.map((r) => (
              <button key={r} onClick={() => setMinutes(r)}
                className={`rounded px-2.5 py-1 ${minutes === r ? "bg-ink text-card" : "text-muted hover:text-ink"}`}>
                {r < 60 ? `${r} min` : "1 h"}
              </button>
            ))}
          </div>
          <Legend services={["frontend", "api-service", "redis"]} />
        </div>
        <div className={`grid gap-3 md:grid-cols-2 xl:grid-cols-3 ${metrics ? "" : "opacity-60"}`}>
          <Card title="p95 latency"><ServiceLineChart series={pick(metrics, "p95")} format={fmtLatency} xFormat={xTime} threshold={{ value: 1, label: "alert 1 s" }} /></Card>
          <Card title="Error rate (5xx)"><ServiceLineChart series={pick(metrics, "err")} format={fmtPctAuto} cap={1} xFormat={xTime} threshold={{ value: 0.1, label: "alert 10%" }} /></Card>
          <Card title="Requests per second"><ServiceLineChart series={pick(metrics, "rps")} format={(v) => (v === null ? "–" : v.toFixed(1))} xFormat={xTime} /></Card>
          <Card title="Upstream call p95 (waiting on the next service)"><ServiceLineChart series={pick(metrics, "upstream_p95")} format={fmtLatency} xFormat={xTime} /></Card>
          <Card title="CPU (share of limit)"><ServiceLineChart series={pick(metrics, "cpu")} format={fmtPctAuto} cap={1} xFormat={xTime} threshold={{ value: 0.8, label: "alert 80%" }} /></Card>
          <Card title="Memory (share of limit)"><ServiceLineChart series={pick(metrics, "mem", ["frontend", "api-service", "redis"])} format={fmtPctAuto} cap={1} xFormat={xTime} threshold={{ value: 0.8, label: "alert 80%" }} /></Card>
        </div>
        <p className="text-xs text-muted">
          Same queries as the alert rules and the incident context (30 s windows, healthchecks excluded). CPU and memory need cAdvisor container labels; with Docker Desktop&apos;s containerd image store on they show no data.
        </p>
      </div>
    </div>
  );
}
