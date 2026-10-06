"""Shared contract between the gateway and the analyzer (SUGGESTED_PLAN.md §6.3, §6.4).

IncidentEvent   gateway -> analyzer, on ws://<gateway>/ws/events (type == "incident").
                Tolerant: unknown fields are kept, every metric may be null
                (no traffic, stopped container, Docker info unavailable).
ResponsePlan    analyzer -> gateway, POSTed to <gateway>/responses.
                Strict: enums, allowlisted actions, confidence 0..1, no extra fields.

Conventions decided here:
- `escalate` is the only action that may have `target: null`. It names the
  best-guess service when there is one, and null when the problem is not an
  app service (ExporterDown -> service "monitoring").
- `root_cause_service` is null only when no app service is the cause
  (monitoring problem) or the analyzer cannot tell (incident_type "unknown").
- `reset_faults` exists only on frontend and api-service; redis has no /reset.
- fault_* keys are ground truth for scoring. They are stripped from every
  incoming event, at any depth, before anything else sees them.

The analyzer only recommends. The policy validator (§6.5) decides what runs.
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

SERVICES = ("frontend", "api-service", "redis")
ACTION_TYPES = ("reset_faults", "restart_container", "flush_cache", "update_resources", "escalate")
INCIDENT_TYPES = ("cpu_saturation", "memory_pressure", "latency_degradation", "error_spike",
                  "service_down", "dependency_down", "unknown")
SEVERITIES = ("low", "medium", "high", "critical")

# Services with the /reset endpoint (both Flask apps); redis has none
RESETTABLE = ("frontend", "api-service")

# Used when an event arrives without a topology
DEFAULT_TOPOLOGY = {"frontend": ["api-service"], "api-service": ["redis"], "redis": []}

Service = Literal["frontend", "api-service", "redis"]
ActionType = Literal["reset_faults", "restart_container", "flush_cache", "update_resources", "escalate"]
IncidentType = Literal["cpu_saturation", "memory_pressure", "latency_degradation", "error_spike",
                       "service_down", "dependency_down", "unknown"]
Severity = Literal["low", "medium", "high", "critical"]


def strip_ground_truth(value):
    """Drop every dict key starting with fault_, recursively."""
    if isinstance(value, dict):
        return {k: strip_ground_truth(v) for k, v in value.items()
                if not (isinstance(k, str) and k.startswith("fault_"))}
    if isinstance(value, list):
        return [strip_ground_truth(v) for v in value]
    return value


# -----------------------------
# IncidentEvent (tolerant)
# -----------------------------

class _Tolerant(BaseModel):
    model_config = ConfigDict(extra="allow")


class Alert(_Tolerant):
    name: str
    service: Optional[str] = None      # frontend | api-service | redis | monitoring
    status: str = "firing"             # firing | resolved
    severity: Optional[str] = None
    category: Optional[str] = None
    startsAt: Optional[str] = None
    value: Optional[float] = None      # stale on resolved alerts, never read it then
    threshold: Optional[float] = None


class MLAnomaly(_Tolerant):
    service: str
    score: Optional[float] = None
    top_features: list[str] = Field(default_factory=list)


class ContainerInfo(_Tolerant):
    status: Optional[str] = None
    restart_count: Optional[int] = None
    started_at: Optional[str] = None


class ServiceContext(_Tolerant):
    """Current values for one service. cpu/mem are fractions of the container
    limit, p95/upstream_p95 seconds, err the 5xx fraction. Redis uses ops,
    mem_bytes and clients instead of the HTTP fields."""
    up: Optional[float] = None
    cpu: Optional[float] = None
    mem: Optional[float] = None
    p95: Optional[float] = None
    err: Optional[float] = None
    rps: Optional[float] = None
    upstream_p95: Optional[float] = None
    ops: Optional[float] = None
    mem_bytes: Optional[float] = None
    clients: Optional[float] = None
    container: Optional[ContainerInfo] = None
    # ~10 samples, one per minute, oldest first; entries may be null
    trend: dict[str, list[Optional[float]]] = Field(default_factory=dict)


class History(_Tolerant):
    attempt: int = 1
    # Each entry is {"type", "target", ...} or {"action": {"type", "target"}, ...}
    previous_actions: list[dict[str, Any]] = Field(default_factory=list)


class IncidentEvent(_Tolerant):
    type: str = "incident"
    incident_id: str
    status: str = "open"               # open | updated | reanalyze | resolved
    timestamp: Optional[str] = None
    opened_at: Optional[str] = None
    resolved_at: Optional[str] = None
    sources: list[str] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)
    alerts: list[Alert] = Field(default_factory=list)
    ml_anomalies: list[MLAnomaly] = Field(default_factory=list)
    topology: dict[str, list[str]] = Field(default_factory=lambda: dict(DEFAULT_TOPOLOGY))
    context: dict[str, Optional[ServiceContext]] = Field(default_factory=dict)
    history: History = Field(default_factory=History)

    @model_validator(mode="before")
    @classmethod
    def _drop_ground_truth(cls, data):
        return strip_ground_truth(data)

    def firing_alerts(self):
        """Alerts still firing; resolved ones in an `updated` incident don't count."""
        return [a for a in self.alerts if a.status != "resolved"]

    def ctx(self, service):
        """Context for a service, or an all-null one (never None)."""
        return self.context.get(service) or ServiceContext()


# -----------------------------
# ResponsePlan (strict)
# -----------------------------

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Action(_Strict):
    type: ActionType
    target: Optional[Service] = None

    @model_validator(mode="after")
    def _check(self):
        if self.type != "escalate" and self.target is None:
            raise ValueError(f"{self.type} needs a target")
        if self.type == "reset_faults" and self.target not in RESETTABLE:
            raise ValueError(f"reset_faults is not available on {self.target}")
        return self


class ResponsePlan(_Strict):
    incident_id: str
    root_cause_service: Optional[Service]
    incident_type: IncidentType
    severity: Severity
    probable_cause: str
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_action: Action
    fallback_action: Optional[Action] = None
    explanation: str = ""
    # Metadata, always filled by the analyzer, never by the model
    source: Literal["llm", "runbook"]
    model: Optional[str] = None             # null for runbook
    runbook: Optional[str] = None           # runbook name when source == runbook
    fallback_reason: Optional[str] = None   # why the LLM wasn't used
    attempt: int = Field(default=1, ge=1)
    latency_ms: float = Field(default=0.0, ge=0.0)
    created_at: str
