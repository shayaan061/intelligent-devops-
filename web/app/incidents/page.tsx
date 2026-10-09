"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, Card, Empty, ErrorNote } from "@/components/ui";
import { fmtDateTime, fmtSecs } from "@/lib/format";
import { usePoll } from "@/lib/live";
import type { StatsResponse } from "@/lib/types";

const FILTERS = ["all", "verified", "escalated", "pending_approval", "in_progress", "failed", "rejected", "no_action"];

export default function Incidents() {
  const { data, error } = usePoll<StatsResponse>("/api/stats", 5000);
  const [filter, setFilter] = useState("all");
  const rows = (data?.incidents ?? []).filter((i) => filter === "all" || i.outcome === filter);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-2 text-lg font-semibold">Incidents</h1>
        {FILTERS.map((f) => {
          const n = f === "all" ? data?.total : data?.outcomes[f];
          return (
            <button key={f} onClick={() => setFilter(f)}
              className={`rounded-full border px-3 py-1 text-xs ${filter === f ? "border-ink bg-ink text-card" : "border-line bg-card text-muted hover:text-ink"}`}>
              {f.replace(/_/g, " ")}{n ? ` · ${n}` : ""}
            </button>
          );
        })}
      </div>
      <ErrorNote error={error && `Incident store unavailable: ${error}`} />
      <Card>
        {!rows.length ? (
          <Empty>{data ? "No incidents match." : "Loading…"}</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="tabular w-full text-left text-sm">
              <thead className="text-xs text-muted">
                <tr className="border-b border-line">
                  <th className="py-2 pr-3 font-medium">Incident</th>
                  <th className="py-2 pr-3 font-medium">Opened</th>
                  <th className="py-2 pr-3 font-medium">Services</th>
                  <th className="py-2 pr-3 font-medium">Root cause</th>
                  <th className="py-2 pr-3 font-medium">Type</th>
                  <th className="py-2 pr-3 font-medium">Action</th>
                  <th className="py-2 pr-3 font-medium">Analysis</th>
                  <th className="py-2 pr-3 font-medium">Outcome</th>
                  <th className="py-2 pr-3 font-medium text-right">Open → verified</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((i) => (
                  <tr key={i.incident_id} className="border-b border-line/60 last:border-0 hover:bg-bg">
                    <td className="whitespace-nowrap py-2 pr-3">
                      <Link href={`/incidents/${encodeURIComponent(i.incident_id)}`} className="font-mono text-xs font-semibold hover:underline">{i.incident_id}</Link>
                    </td>
                    <td className="whitespace-nowrap py-2 pr-3 text-xs">{fmtDateTime(i.opened_at)}</td>
                    <td className="py-2 pr-3 text-xs">{i.services.join(", ") || "–"}</td>
                    <td className="py-2 pr-3 font-medium">{i.root_cause ?? "–"}</td>
                    <td className="py-2 pr-3 text-xs">{i.incident_type?.replace(/_/g, " ") ?? "–"}</td>
                    <td className="py-2 pr-3 text-xs">{i.action ?? "–"}</td>
                    <td className="py-2 pr-3 text-xs">
                      {i.source ?? "–"}{i.attempts > 1 ? ` · ${i.attempts} attempts` : ""}
                      {i.plan_latency_ms !== null && <span className="text-muted"> · {fmtSecs(i.plan_latency_ms / 1000)}</span>}
                    </td>
                    <td className="py-2 pr-3"><Badge status={i.outcome} /></td>
                    <td className="py-2 pr-3 text-right">{fmtSecs(i.open_to_verified_s)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <p className="text-xs text-muted">From the gateway&apos;s incident store (latest 50). The evaluation&apos;s MTTD and MTTR are measured from the injected faults by experiments/score.py.</p>
    </div>
  );
}
