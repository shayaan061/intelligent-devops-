"""Ollama client and prompt for the LLM Analysis Engine (SUGGESTED_PLAN.md §6.4).

Sends a compact IncidentEvent to a local model through Ollama's /api/chat
(stream off, temperature 0, `format` = the JSON schema of the answer, i.e.
Ollama structured outputs) and turns the answer into a ResponsePlan.

The model only fills the analysis fields. incident_id, source, model,
attempt, latency and timestamps are set here, never taken from the model.
Anything that goes wrong raises LLMError with a short reason; analyzer.py
then falls back to the runbooks and reports that reason as fallback_reason:
  unreachable, timeout, http_<status>, bad_response, invalid_json,
  invalid_action: <detail>, schema_error, low_confidence

Nothing named fault_* reaches the prompt (ground truth for scoring only).

Env:
  OLLAMA_URL     default http://host.docker.internal:11434
  OLLAMA_MODEL   default llama3.1:8b
  LLM_TIMEOUT    seconds, default 120 (CPU inference is slow)
"""

import json
import os
from datetime import datetime, timezone

import httpx
from pydantic import ValidationError

from schemas import (ACTION_TYPES, INCIDENT_TYPES, RESETTABLE, SERVICES, SEVERITIES, ResponsePlan,
                     strip_ground_truth)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "120"))

# Below this the policy validator would not act anyway (§6.5)
MIN_CONFIDENCE = 0.7

# Fields the model writes; everything else in ResponsePlan is metadata
LLM_FIELDS = ("root_cause_service", "incident_type", "severity", "probable_cause", "evidence",
              "confidence", "recommended_action", "fallback_action", "explanation")


class LLMError(Exception):
    """The LLM answer can't be used; str(e) is the fallback_reason."""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# -----------------------------
# Output schema (Ollama `format`)
# -----------------------------

# Written inline (no $ref/$defs) so Ollama's schema-to-grammar handles it
_ACTION = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": list(ACTION_TYPES)},
        "target": {"anyOf": [{"type": "string", "enum": list(SERVICES)}, {"type": "null"}]},
    },
    "required": ["type", "target"],
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "root_cause_service": {"anyOf": [{"type": "string", "enum": list(SERVICES)}, {"type": "null"}]},
        "incident_type": {"type": "string", "enum": list(INCIDENT_TYPES)},
        "severity": {"type": "string", "enum": list(SEVERITIES)},
        "probable_cause": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "recommended_action": _ACTION,
        "fallback_action": {"anyOf": [_ACTION, {"type": "null"}]},
        "explanation": {"type": "string"},
    },
    "required": list(LLM_FIELDS),
}


# -----------------------------
# Prompt
# -----------------------------

SYSTEM_PROMPT = """You are an SRE root-cause analyst for a 3-service web app running in Docker Compose.
You receive one incident as JSON and answer with ONE JSON object that matches the given schema. You only recommend; a policy validator decides what runs.

Topology (caller -> callee): frontend -> api-service -> redis. Users hit frontend.

Metrics per service:
- up: 1 running, 0 down. cpu, mem: fraction of the container limit (0.9 = 90%).
- p95: the service's own p95 request latency in seconds. upstream_p95: p95 of its calls to the next service (frontend -> api-service, api-service -> redis).
- err: fraction of requests answered with 5xx. rps: requests per second.
- redis has ops (commands/s), mem_bytes, clients instead.
- trend: about one sample per minute for the last 10 minutes, oldest first; null = no data.
Alert thresholds: HighCPU cpu > 0.8, HighMemory mem > 0.8, HighLatency p95 > 1 s, HighErrorRate err > 0.1, ServiceDown up == 0, RedisDown redis down. ExporterDown (service "monitoring") is a monitoring problem, not an app problem.

Telling the cause from a symptom:
- Failures propagate UP the chain. redis down -> api-service returns 503 -> frontend returns 502, so both show errors. A slow api-service makes frontend slow too.
- Latency: if a service's upstream_p95 is about its whole p95 (>= half of it), its time is spent waiting on the callee, so it is a symptom; look at the callee. The root cause is the deepest slow service whose upstream_p95 is small compared to its p95.
- Errors: the root cause is the deepest service with its own errors whose callee is healthy (up and not erroring).
- A down dependency beats everything: redis up == 0 or RedisDown -> root cause redis, even if api-service and frontend show errors.
- Priority when several problems appear: down > memory > cpu > errors > latency. Recommend ONE action for the root cause, not one per symptom.

Allowed actions (type, and target must be frontend, api-service or redis):
- reset_faults: clear an injected cpu/latency/error/memory fault on frontend or api-service. NEVER on redis (redis has no reset).
- restart_container: restart the container. Use for a down service or dependency, for memory pressure (mem near the limit or rising steadily), and as the fallback when reset_faults does not help.
- flush_cache: flush redis (needs human approval, rarely right).
- update_resources: change container limits (needs human approval, rarely right).
- escalate: hand over to a human. Use it when the problem is outside the app (ExporterDown), when nothing in the data explains the incident, or when previous_actions already tried the sensible actions. target may be null.
Usual mapping: down service -> restart_container; memory_pressure -> restart_container; cpu_saturation, error_spike, latency_degradation -> reset_faults with fallback restart_container.
If history.previous_actions already contains an action for this incident, do not recommend it again; move to the next one.

incident_type: cpu_saturation | memory_pressure | latency_degradation | error_spike | service_down (frontend or api-service down) | dependency_down (redis down) | unknown.
severity: critical for down services, high for active degradation, medium for early warnings or monitoring problems.
confidence: 0..1, how sure you are of the root cause. evidence: short facts with numbers taken from the incident.

Example 1. Alerts: HighLatency api-service, HighLatency frontend. frontend p95 5.1 upstream_p95 5.0; api-service p95 5.0 upstream_p95 0.002; redis up 1.
Answer: {"root_cause_service": "api-service", "incident_type": "latency_degradation", "severity": "high", "probable_cause": "api-service handler is delayed ~5 s while redis answers in 2 ms; frontend is slow only because it waits on api-service.", "evidence": ["api-service p95 5.0 s", "api-service upstream_p95 0.002 s", "frontend upstream_p95 5.0 s of its 5.1 s p95"], "confidence": 0.85, "recommended_action": {"type": "reset_faults", "target": "api-service"}, "fallback_action": {"type": "restart_container", "target": "api-service"}, "explanation": "Reset api-service; restart it if latency stays high."}

Example 2. Alerts: RedisDown redis, HighErrorRate api-service, HighErrorRate frontend. redis up 0; api-service err 1.0; frontend err 1.0.
Answer: {"root_cause_service": "redis", "incident_type": "dependency_down", "severity": "critical", "probable_cause": "redis is down, so api-service fails every request and frontend passes the failure on.", "evidence": ["redis up 0", "api-service err 1.0", "frontend err 1.0"], "confidence": 0.95, "recommended_action": {"type": "restart_container", "target": "redis"}, "fallback_action": {"type": "escalate", "target": "redis"}, "explanation": "Restart redis; the errors upstream are symptoms."}

Example 3. Alerts: HighCPU api-service, HighLatency api-service. api-service cpu 0.97 p95 1.6 upstream_p95 0.002; frontend p95 1.7 upstream_p95 1.6.
Answer: {"root_cause_service": "api-service", "incident_type": "cpu_saturation", "severity": "high", "probable_cause": "api-service is CPU bound, which also slows its responses.", "evidence": ["api-service cpu 0.97", "api-service p95 1.6 s with upstream_p95 0.002 s"], "confidence": 0.85, "recommended_action": {"type": "reset_faults", "target": "api-service"}, "fallback_action": {"type": "restart_container", "target": "api-service"}, "explanation": "One action on api-service covers both alerts."}
"""

# Rounding keeps the prompt short without losing what matters
_KEEP = ("up", "cpu", "mem", "p95", "err", "rps", "upstream_p95", "ops", "mem_bytes", "clients")


def _r(v):
    if isinstance(v, float):
        return round(v, 3) if abs(v) < 1000 else round(v)
    return v


def compact_incident(incident):
    """The parts of an IncidentEvent the model needs, current values first,
    trends as short rounded lists. Ground truth is stripped again for safety."""
    context = {}
    for svc, c in incident.context.items():
        if c is None:
            context[svc] = None
            continue
        entry = {k: _r(getattr(c, k)) for k in _KEEP if getattr(c, k) is not None}
        if c.container is not None:
            entry["container"] = {k: v for k, v in (("status", c.container.status),
                                                    ("restart_count", c.container.restart_count))
                                  if v is not None}
        trend = {k: [_r(x) for x in v] for k, v in c.trend.items() if v and any(x is not None for x in v)}
        if trend:
            entry["trend"] = trend
        context[svc] = entry

    return strip_ground_truth({
        "incident_id": incident.incident_id,
        "status": incident.status,
        "alerts": [{k: v for k, v in (("name", a.name), ("service", a.service),
                                      ("value", _r(a.value)), ("threshold", a.threshold)) if v is not None}
                   for a in incident.firing_alerts()],
        "ml_anomalies": [{"service": m.service, "score": _r(m.score), "top_features": m.top_features}
                         for m in incident.ml_anomalies],
        "topology": incident.topology,
        "context": context,
        "history": {"attempt": incident.history.attempt,
                    "previous_actions": incident.history.previous_actions},
    })


def build_messages(incident):
    user = ("Incident:\n" + json.dumps(compact_incident(incident), separators=(",", ":"))
            + "\nAnswer with the JSON object only.")
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


# -----------------------------
# Ollama call and validation
# -----------------------------

def call_ollama(messages, client=None):
    """Raw content string of the model's answer."""
    body = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "format": OUTPUT_SCHEMA,
        "options": {"temperature": 0},
    }
    try:
        if client is None:
            r = httpx.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=LLM_TIMEOUT)
        else:
            r = client.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=LLM_TIMEOUT)
    except httpx.TimeoutException:
        raise LLMError("timeout")
    except httpx.HTTPError:
        raise LLMError("unreachable")

    if r.status_code != 200:
        raise LLMError(f"http_{r.status_code}")
    try:
        content = r.json()["message"]["content"]
    except (ValueError, KeyError, TypeError):
        raise LLMError("bad_response")
    if not isinstance(content, str):
        raise LLMError("bad_response")
    return content


def action_problem(action, field):
    """Reason string if an action dict breaks the allowlist rules, else None."""
    if action is None:
        return None if field == "fallback_action" else f"{field} missing"
    if not isinstance(action, dict):
        return f"{field} not an object"
    typ, target = action.get("type"), action.get("target")
    if typ not in ACTION_TYPES:
        return f"{field} type {typ!r} not allowed"
    if target is not None and target not in SERVICES:
        return f"{field} target {target!r} unknown"
    if typ != "escalate" and target is None:
        return f"{field} {typ} without target"
    if typ == "reset_faults" and target not in RESETTABLE:
        return f"{field} reset_faults on {target}"
    return None


def parse_answer(content, incident):
    """Model answer -> ResponsePlan (metadata filled here). Raises LLMError."""
    try:
        raw = json.loads(content)
    except (ValueError, TypeError):
        raise LLMError("invalid_json")
    if not isinstance(raw, dict):
        raise LLMError("invalid_json")

    for field in ("recommended_action", "fallback_action"):
        problem = action_problem(raw.get(field), field)
        if problem:
            raise LLMError(f"invalid_action: {problem}")

    fields = {k: raw[k] for k in LLM_FIELDS if k in raw}
    try:
        plan = ResponsePlan.model_validate({
            **fields,
            "incident_id": incident.incident_id,
            "source": "llm",
            "model": OLLAMA_MODEL,
            "runbook": None,
            "fallback_reason": None,
            "attempt": incident.history.attempt,
            "latency_ms": 0.0,
            "created_at": now_iso(),
        })
    except ValidationError:
        raise LLMError("schema_error")

    if plan.confidence < MIN_CONFIDENCE:
        raise LLMError("low_confidence")
    return plan


def llm_plan(incident, client=None):
    """ResponsePlan from the model, or LLMError(reason)."""
    return parse_answer(call_ollama(build_messages(incident), client), incident)
