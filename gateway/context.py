"""Context builder (§6.3): the last 10 minutes of key metrics per service.

For every service in the chain it runs one PromQL range query per metric
(10 min, one point per minute). The last point is the current value and the
whole list is the trend. Container state and restart count come from the
Docker API when the socket is mounted.

The windows and filters match prometheus/rules.yml (30 s rates, only the
`/` and `/data` endpoints), so the numbers line up with the alerts.

NEVER query fault_*_active here: those gauges are ground truth for scoring.
The assert at import time enforces it.
"""

import asyncio
import logging
import math
import time

import httpx

log = logging.getLogger("gateway.context")

HTTP = 'job="{s}", endpoint=~"/|/data"'

APP_QUERIES = {
    "up": 'max(up{{job="{s}"}})',
    "cpu": ('sum(rate(container_cpu_usage_seconds_total{{name="{s}"}}[30s]))'
            ' / max(container_spec_cpu_quota{{name="{s}"}} / container_spec_cpu_period{{name="{s}"}})'),
    "mem": ('max(container_memory_working_set_bytes{{name="{s}"}})'
            ' / max(container_spec_memory_limit_bytes{{name="{s}"}} > 0)'),
    "p95": 'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{{' + HTTP + '}}[30s])))',
    "err": ('(sum(rate(http_requests_total{{' + HTTP + ', status=~"5.."}}[30s])) or vector(0))'
            ' / sum(rate(http_requests_total{{' + HTTP + '}}[30s]))'),
    "rps": 'sum(rate(http_requests_total{{' + HTTP + '}}[30s]))',
    "upstream_p95": 'histogram_quantile(0.95, sum by (le) (rate(upstream_request_duration_seconds_bucket{{job="{s}"}}[30s])))',
}

REDIS_QUERIES = {
    "up": "max(redis_up)",
    "ops": "sum(rate(redis_commands_processed_total[30s]))",
    "mem_bytes": "max(redis_memory_used_bytes)",
    "clients": "max(redis_connected_clients)",
    "mem": APP_QUERIES["mem"],
}

SERVICE_QUERIES = {"frontend": APP_QUERIES, "api-service": APP_QUERIES, "redis": REDIS_QUERIES}

assert not any("fault_" in q for qs in SERVICE_QUERIES.values() for q in qs.values()), \
    "fault_* metrics are ground truth and must never be in the context"

# Alert -> the context metric that is its value, and the rule threshold
ALERT_METRIC = {
    "HighCPU": ("cpu", 0.8),
    "HighMemory": ("mem", 0.8),
    "HighLatency": ("p95", 1.0),
    "HighErrorRate": ("err", 0.1),
    "ServiceDown": ("up", None),
    "RedisDown": ("up", None),
}


def clean(v):
    """Prometheus string -> rounded float, or None for NaN/Inf/missing."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, 4)


class ContextBuilder:
    def __init__(self, prometheus_url, minutes=10, step=60, timeout=5.0, docker_client=None):
        self.prometheus_url = prometheus_url.rstrip("/")
        self.minutes = minutes
        self.step = step
        self.timeout = timeout
        self.docker = docker_client
        self.transport = None  # tests inject httpx.MockTransport

    async def _range(self, client, query, start, end):
        """Values at each step, oldest first; None where there was no data."""
        try:
            r = await client.get(f"{self.prometheus_url}/api/v1/query_range",
                                 params={"query": query, "start": start, "end": end, "step": self.step})
            r.raise_for_status()
            result = r.json()["data"]["result"]
        except Exception as e:
            log.warning("query failed (%s): %s", e.__class__.__name__, query)
            return None
        points = {}
        if result:
            # Aggregated queries return a single series
            for ts, v in result[0]["values"]:
                points[round(float(ts))] = clean(v)
        n = int((end - start) // self.step) + 1
        return [points.get(round(start + i * self.step)) for i in range(n)]

    def _container(self, name):
        if self.docker is None:
            return None
        try:
            attrs = self.docker.containers.get(name).attrs
            return {"status": attrs["State"]["Status"],
                    "restart_count": attrs.get("RestartCount", 0),
                    "started_at": attrs["State"].get("StartedAt")}
        except Exception as e:
            if e.__class__.__name__ == "NotFound":
                return {"status": "missing", "restart_count": None, "started_at": None}
            log.warning("docker inspect %s failed: %s", name, e)
            return None

    async def build(self, services=None):
        services = services or list(SERVICE_QUERIES)
        end = math.floor(time.time())
        start = end - self.minutes * 60
        jobs = [(svc, metric, q.format(s=svc))
                for svc in services for metric, q in SERVICE_QUERIES[svc].items()]

        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            series = await asyncio.gather(*(self._range(client, q, start, end) for _, _, q in jobs))
        containers = await asyncio.gather(*(asyncio.to_thread(self._container, s) for s in services))

        context = {svc: {"trend": {}} for svc in services}
        for (svc, metric, _), values in zip(jobs, series):
            values = values or []
            context[svc][metric] = values[-1] if values else None
            if metric != "up":
                context[svc]["trend"][metric] = values
        for svc, info in zip(services, containers):
            context[svc]["container"] = info
        return context


def alert_value(alert, context):
    """(value, threshold) for an alert, read from the fresh context."""
    metric, threshold = ALERT_METRIC.get(alert.get("alertname") or alert.get("name"), (None, None))
    svc = context.get(alert.get("service")) or {}
    return (svc.get(metric) if metric else None), threshold
