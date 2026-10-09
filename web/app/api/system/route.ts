// Health of every part of the pipeline, for the System page and the header.
import { NextResponse } from "next/server";
import { ALERTMANAGER_URL, GATEWAY_URL, OLLAMA_MODEL, OLLAMA_URL, PROMETHEUS_URL, RESPONDER_URL, fetchJson } from "@/lib/config";
import type { ComponentStatus, PlanMsg, SystemResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

async function probe(name: string, role: string, fn: () => Promise<string>): Promise<ComponentStatus> {
  try {
    return { name, role, ok: true, detail: await fn() };
  } catch (e) {
    return { name, role, ok: false, detail: e instanceof Error ? e.message : String(e) };
  }
}

type Targets = { data: { activeTargets: { labels: Record<string, string>; health: string; lastError?: string }[] } };
type AmAlert = { labels: Record<string, string>; annotations: Record<string, string>; startsAt: string; status: { state: string } };

export async function GET() {
  let targets: SystemResponse["targets"] = [];
  let firing: SystemResponse["firing"] = [];
  let policies: Record<string, unknown> | null = null;

  const components = await Promise.all([
    probe("Prometheus", "Metric collection and alert rules (5 s scrape)", async () => {
      const t = await fetchJson<Targets>(`${PROMETHEUS_URL}/api/v1/targets`);
      targets = t.data.activeTargets.map((x) => ({
        job: x.labels.job, instance: x.labels.instance, health: x.health, lastError: x.lastError || undefined,
      }));
      const up = targets.filter((x) => x.health === "up").length;
      if (up < targets.length) throw new Error(`${up}/${targets.length} scrape targets up`);
      return `${up}/${targets.length} scrape targets up`;
    }),
    probe("Alertmanager", "Routes firing alerts to the gateway webhook", async () => {
      const alerts = await fetchJson<AmAlert[]>(`${ALERTMANAGER_URL}/api/v2/alerts?active=true&silenced=false&inhibited=false`);
      firing = alerts.map((a) => ({
        alertname: a.labels.alertname, service: a.labels.service ?? "", severity: a.labels.severity ?? "",
        startsAt: a.startsAt, summary: a.annotations.summary ?? a.annotations.description ?? "",
      }));
      return `${firing.length} alert${firing.length === 1 ? "" : "s"} firing`;
    }),
    probe("Event Gateway", "Grouping, context builder, WebSockets, incident store", async () => {
      const h = await fetchJson<{ open_incidents: number; clients: { events: number; responses: number } }>(`${GATEWAY_URL}/health`);
      return `${h.open_incidents} open incident(s); ${h.clients.events} event / ${h.clients.responses} response subscribers`;
    }),
    probe("LLM Analysis Engine", "Analyzer: LLM plan, runbook fallback", async () => {
      // The analyzer has no HTTP port: report what its last plan says
      const recent = await fetchJson<PlanMsg[]>(`${GATEWAY_URL}/responses`);
      const plans = recent.filter((m) => m.type === "response_plan");
      const last = plans[plans.length - 1];
      if (!last) return "no plans yet";
      return `last plan: ${last.source}${last.model ? ` (${last.model})` : ""}` +
        `${last.fallback_reason ? `, fallback: ${last.fallback_reason}` : ""}`;
    }),
    probe("Ollama", `Local LLM runtime (${OLLAMA_MODEL})`, async () => {
      const tags = await fetchJson<{ models: { name: string }[] }>(`${OLLAMA_URL}/api/tags`, undefined, 2500);
      const has = tags.models.some((m) => m.name === OLLAMA_MODEL || m.name.startsWith(OLLAMA_MODEL + ":"));
      if (!has) throw new Error(`${OLLAMA_MODEL} not downloaded; plans fall back to runbooks`);
      return `${OLLAMA_MODEL} available`;
    }),
    probe("Responder", "Policy validator, executor, verifier", async () => {
      const h = await fetchJson<{ mode: string; docker: boolean; pending_approvals: number }>(`${RESPONDER_URL}/health`);
      policies = await fetchJson<Record<string, unknown>>(`${RESPONDER_URL}/policies`).catch(() => null);
      if (!h.docker) throw new Error(`mode ${h.mode}; Docker socket unavailable, restarts will fail`);
      return `mode ${h.mode}; ${h.pending_approvals} pending approval(s)`;
    }),
  ]);

  // The scrape targets double as health for the demo services
  const body: SystemResponse = { components, targets, firing, policies };
  return NextResponse.json(body);
}
