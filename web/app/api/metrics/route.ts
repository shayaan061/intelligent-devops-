// Live per-service metrics for the service map and charts.
// Fixed queries only (the same ones as gateway/context.py, so the numbers match
// the alerts and the incident context). There is deliberately no generic
// Prometheus passthrough: fault_*_active gauges are ground truth for scoring
// and must never be shown as monitoring data.
import { NextResponse } from "next/server";
import { PROMETHEUS_URL, fetchJson } from "@/lib/config";
import type { MetricName, MetricsResponse, ServiceMetrics } from "@/lib/types";

export const dynamic = "force-dynamic";

const HTTP = (s: string) => `job="${s}", endpoint=~"/|/data"`;

const APP_QUERIES = (s: string): Partial<Record<MetricName, string>> => ({
  up: `max(up{job="${s}"})`,
  cpu:
    `sum(rate(container_cpu_usage_seconds_total{name="${s}"}[30s]))` +
    ` / max(container_spec_cpu_quota{name="${s}"} / container_spec_cpu_period{name="${s}"})`,
  mem: `max(container_memory_working_set_bytes{name="${s}"}) / max(container_spec_memory_limit_bytes{name="${s}"} > 0)`,
  p95: `histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{${HTTP(s)}}[30s])))`,
  err:
    `(sum(rate(http_requests_total{${HTTP(s)}, status=~"5.."}[30s])) or vector(0))` +
    ` / sum(rate(http_requests_total{${HTTP(s)}}[30s]))`,
  rps: `sum(rate(http_requests_total{${HTTP(s)}}[30s]))`,
  upstream_p95: `histogram_quantile(0.95, sum by (le) (rate(upstream_request_duration_seconds_bucket{job="${s}"}[30s])))`,
});

const REDIS_QUERIES: Partial<Record<MetricName, string>> = {
  up: "max(redis_up)",
  ops: "sum(rate(redis_commands_processed_total[30s]))",
  mem_bytes: "max(redis_memory_used_bytes)",
  clients: "max(redis_connected_clients)",
  mem: APP_QUERIES("redis").mem,
};

const QUERIES: Record<string, Partial<Record<MetricName, string>>> = {
  frontend: APP_QUERIES("frontend"),
  "api-service": APP_QUERIES("api-service"),
  redis: REDIS_QUERIES,
};

if (Object.values(QUERIES).some((qs) => Object.values(qs).some((q) => q?.includes("fault_")))) {
  throw new Error("fault_* metrics are ground truth and must never be queried by the dashboard");
}

type RangeResult = { data: { result: { values: [number, string][] }[] } };

function num(v: string): number | null {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

export async function GET(req: Request) {
  const minutes = Math.min(Math.max(Number(new URL(req.url).searchParams.get("minutes")) || 15, 1), 60);
  const end = Math.floor(Date.now() / 1000);
  const start = end - minutes * 60;
  const step = Math.max(5, Math.round((minutes * 60) / 120));
  const services: Record<string, ServiceMetrics> = {};
  let error: string | undefined;

  await Promise.all(
    Object.entries(QUERIES).map(async ([svc, qs]) => {
      const m: ServiceMetrics = { current: {}, series: {} };
      services[svc] = m;
      await Promise.all(
        Object.entries(qs).map(async ([name, q]) => {
          const url = `${PROMETHEUS_URL}/api/v1/query_range?` + new URLSearchParams({
            query: q!, start: String(start), end: String(end), step: String(step),
          });
          try {
            const body = await fetchJson<RangeResult>(url);
            const values = body.data.result[0]?.values ?? [];
            const series = values.map(([t, v]) => [t, num(v)] as [number, number | null]);
            m.series[name as MetricName] = series;
            // Current = the last sample, but only if it is recent (a stopped target has none)
            const last = series[series.length - 1];
            m.current[name as MetricName] = last && end - last[0] <= step * 2 ? last[1] : null;
          } catch (e) {
            error = String(e);
            m.current[name as MetricName] = null;
          }
        }),
      );
    }),
  );

  const body: MetricsResponse = { ok: !error, error, services };
  return NextResponse.json(body);
}
