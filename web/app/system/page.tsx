"use client";

// The system itself: health of each stage of the loop, Prometheus targets,
// what Alertmanager has firing, and the safety rules the responder enforces.
import { Badge, Card, Empty, ErrorNote, KV } from "@/components/ui";
import { ago, fmtSecs } from "@/lib/format";
import { usePoll } from "@/lib/live";
import type { StatsResponse, SystemResponse } from "@/lib/types";

const PIPELINE = ["Prometheus", "Alertmanager", "Event Gateway", "LLM Analysis Engine", "Responder"];
const STAGE_LABEL: Record<string, string> = {
  Prometheus: "Monitor", Alertmanager: "Detect", "Event Gateway": "Group + context",
  "LLM Analysis Engine": "Analyze", Responder: "Validate · act · verify",
};

type Policies = {
  mode?: string;
  actions?: Record<string, { targets: (string | null)[]; requires_approval: boolean }>;
  min_confidence?: number;
  cooldown_seconds?: number;
  max_actions_per_incident?: number;
  verify_delay_seconds?: number;
  max_attempts?: number;
  cooldowns?: { type: string; target: string | null; remaining_s: number }[];
};

export default function System() {
  const { data, error } = usePoll<SystemResponse>("/api/system", 5000);
  const { data: stats } = usePoll<StatsResponse>("/api/stats", 15000);
  const byName = new Map((data?.components ?? []).map((c) => [c.name, c]));
  const p = (data?.policies ?? null) as Policies | null;

  return (
    <div className="space-y-5">
      <h1 className="text-lg font-semibold">System</h1>
      <ErrorNote error={error} />

      <Card title="Pipeline">
        <div className="flex flex-col gap-2 lg:flex-row lg:items-stretch">
          {PIPELINE.map((name, i) => {
            const c = byName.get(name);
            return (
              <div key={name} className="flex flex-1 flex-col gap-2 lg:flex-row lg:items-center">
                {i > 0 && <div aria-hidden className="self-center text-muted">→</div>}
                <div className={`flex-1 rounded-lg border-2 p-3 ${c?.ok === false ? "border-bad" : c?.ok ? "border-ok/60" : "border-line"}`}>
                  <div className="text-[10px] uppercase tracking-wide text-muted">{STAGE_LABEL[name]}</div>
                  <div className="flex items-center justify-between gap-2">
                    <b className="text-sm">{name}</b>
                    <Badge status={c ? (c.ok ? "up" : "down") : "pending"} label={c ? (c.ok ? "ok" : "problem") : "…"} />
                  </div>
                  <div className="mt-1 text-xs text-muted">{c?.detail ?? "checking…"}</div>
                </div>
              </div>
            );
          })}
        </div>
        <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted">
          {byName.get("Ollama") && (
            <span className="inline-flex items-center gap-2 rounded border border-line px-2 py-1">
              <Badge status={byName.get("Ollama")!.ok ? "up" : "down"} label={byName.get("Ollama")!.ok ? "ok" : "problem"} />
              Ollama: {byName.get("Ollama")!.detail}
            </span>
          )}
          <span className="rounded border border-line px-2 py-1">
            Verify loop: wait {p?.verify_delay_seconds ?? "–"} s → re-check alerts → re-analyze, at most {p?.max_attempts ?? "–"} attempts → escalate
          </span>
        </div>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Scrape targets">
          {!data?.targets.length ? <Empty>No targets (Prometheus unreachable?).</Empty> : (
            <table className="w-full text-sm">
              <tbody>
                {data.targets.map((t) => (
                  <tr key={t.job + t.instance} className="border-b border-line/60 last:border-0">
                    <td className="py-1.5 pr-2 font-medium">{t.job}</td>
                    <td className="py-1.5 pr-2 text-xs text-muted">{t.instance}{t.lastError ? ` · ${t.lastError}` : ""}</td>
                    <td className="py-1.5 text-right"><Badge status={t.health === "up" ? "up" : "down"} label={t.health} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card title="Alerts firing now (Alertmanager)">
          {!data?.firing.length ? <Empty>No alerts firing.</Empty> : (
            <div className="space-y-1.5">
              {data.firing.map((a, i) => (
                <div key={i} className="flex items-start justify-between gap-2 border-b border-line/60 pb-1.5 text-sm last:border-0">
                  <div>
                    <b>{a.alertname}</b> <span className="text-muted">on {a.service}</span>
                    <div className="text-xs text-muted">{a.summary}</div>
                  </div>
                  <div className="text-right">
                    <Badge status={a.severity === "critical" ? "critical" : "warning"} label={a.severity || "alert"} />
                    <div className="text-xs text-muted">{ago(a.startsAt)}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card title="Safety policy (responder/policies.yaml)" className="lg:col-span-2">
          {!p ? <Empty>Responder unreachable.</Empty> : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="text-xs text-muted">
                    <tr className="border-b border-line">
                      <th className="py-1.5 pr-3 font-medium">Allowed action</th>
                      <th className="py-1.5 pr-3 font-medium">Targets</th>
                      <th className="py-1.5 font-medium">Mode</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(p.actions ?? {}).map(([type, rule]) => (
                      <tr key={type} className="border-b border-line/60 last:border-0">
                        <td className="py-1.5 pr-3 font-mono text-xs">{type}</td>
                        <td className="py-1.5 pr-3 text-xs">{rule.targets.map((t) => t ?? "none").join(", ")}</td>
                        <td className="py-1.5"><Badge status={rule.requires_approval ? "pending_approval" : "executed"} label={rule.requires_approval ? "needs approval" : "automatic"} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-xs text-muted">Anything not listed is rejected. The LLM only recommends; no arbitrary commands are ever executed.</p>
            </>
          )}
        </Card>
        <Card title="Rules">
          {!p ? <Empty>–</Empty> : (
            <>
              <KV k="Responder mode" v={p.mode === "dry_run" ? "dry run (validate only)" : p.mode ?? "–"} />
              <KV k="Min. confidence to act" v={p.min_confidence ?? "–"} />
              <KV k="Cooldown, same action + target" v={fmtSecs(p.cooldown_seconds)} />
              <KV k="Max actions per incident" v={p.max_actions_per_incident ?? "–"} />
              <KV k="Verify after" v={fmtSecs(p.verify_delay_seconds)} />
              <KV k="Max analysis attempts" v={p.max_attempts ?? "–"} />
              <h3 className="mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-muted">Active cooldowns</h3>
              {!p.cooldowns?.length ? <Empty>None.</Empty> : p.cooldowns.map((c, i) => (
                <KV key={i} k={<span className="font-mono text-xs">{c.type} → {c.target ?? "–"}</span>} v={`${Math.ceil(c.remaining_s)} s left`} />
              ))}
            </>
          )}
        </Card>
      </div>

      <Card title="Responder outcomes (incident store)">
        {!stats?.ok ? <Empty>Incident store unavailable.</Empty> : (
          <div className="grid gap-5 sm:grid-cols-2">
            <div>
              <h3 className="mb-1 text-xs text-muted">Action records by status</h3>
              {Object.entries(stats.actions_by_status).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
                <KV key={k} k={<Badge status={k} />} v={v} />
              ))}
              {!Object.keys(stats.actions_by_status).length && <Empty>No actions yet.</Empty>}
            </div>
            <div>
              <h3 className="mb-1 text-xs text-muted">Analysis</h3>
              <KV k="Plans by the LLM" v={stats.plans.llm} />
              <KV k="Plans by runbooks" v={stats.plans.runbook} />
              <KV k="Mean LLM analysis time" v={fmtSecs(stats.mean_llm_latency_s)} />
              <KV k="Mean incident open → plan" v={fmtSecs(stats.mean_time_to_plan_s)} />
              <KV k="Mean incident open → verified" v={fmtSecs(stats.mean_open_to_verified_s)} />
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
