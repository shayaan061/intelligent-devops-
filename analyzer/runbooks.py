"""YAML runbook engine (SUGGESTED_PLAN.md §6.4).

Runbooks are the fallback when the LLM fails and the "no LLM" baseline (B1).
They find the root cause from the topology and the metric context only
(never from fault_* ground truth).

Runbook fields (runbooks/*.yaml, each file a list):
  name           unique id, reported in ResponsePlan.runbook
  priority       lower is tried first; the first runbook that matches AND
                 finds a root cause wins. Order: monitoring (5) > redis down
                 (10) > service down (20) > memory (30) > cpu (40) > errors
                 (50) > latency (60) > ML-only (70).
  match          any-of conditions:
                   alert: Name | [Names]        a firing alert with that name
                   down: svc | [svcs]           context <svc>.up == 0
                   only_alerts: [Names]         every firing alert is one of these
                   ml_feature: text             an ML anomaly with a top feature containing text
  root_cause     a service name, `none`, or a strategy:
                   matched_service              deepest service that triggered the match
                   deepest_service_with_errors  deepest service with its own 5xx and healthy dependencies
                   latency_origin               walk down while upstream_p95 explains p95
                   top_ml_anomaly               highest-scoring ML anomaly that matched
  incident_type, severity, confidence    copied into the plan
  action, fallback                        action types; the target is the root cause
                                          (escalate on a null root has target null)

Retries: actions already in history.previous_actions are skipped, so attempt
2 after a failed reset_faults recommends the restart, and when both were
tried the plan is escalate.

Usage:
  from runbooks import load_runbooks, run_runbooks
  plan = run_runbooks(IncidentEvent.model_validate(event), load_runbooks())
"""

import os
from datetime import datetime, timezone
from pathlib import Path

import yaml

from schemas import ACTION_TYPES, INCIDENT_TYPES, RESETTABLE, SERVICES, SEVERITIES, Action, ResponsePlan

RUNBOOK_DIR = Path(os.environ.get("RUNBOOK_DIR") or Path(__file__).resolve().parent.parent / "runbooks")

# Same thresholds as prometheus/rules.yml
ERR_THRESHOLD = 0.1
LATENCY_THRESHOLD = 1.0
# upstream_p95 >= this share of p95 means the time is spent waiting on the dependency
EXPLAINED_SHARE = 0.5

STRATEGIES = ("matched_service", "deepest_service_with_errors", "latency_origin", "top_ml_anomaly", "none")
REQUIRED = ("name", "priority", "match", "root_cause", "incident_type", "severity", "action", "confidence")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def as_list(v):
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


# -----------------------------
# Loading
# -----------------------------

def validate_runbook(rb, origin):
    missing = [k for k in REQUIRED if k not in rb]
    if missing:
        raise ValueError(f"{origin}: runbook {rb.get('name')!r} missing {missing}")

    name = rb["name"]
    if rb["incident_type"] not in INCIDENT_TYPES:
        raise ValueError(f"{origin}: {name}: bad incident_type {rb['incident_type']!r}")
    if rb["severity"] not in SEVERITIES:
        raise ValueError(f"{origin}: {name}: bad severity {rb['severity']!r}")
    for key in ("action", "fallback"):
        if rb.get(key) is not None and rb[key] not in ACTION_TYPES:
            raise ValueError(f"{origin}: {name}: {key} {rb[key]!r} not in the allowlist")
    if rb["root_cause"] not in STRATEGIES and rb["root_cause"] not in SERVICES:
        raise ValueError(f"{origin}: {name}: unknown root_cause {rb['root_cause']!r}")
    if rb["root_cause"] == "none" and (rb["action"] != "escalate" or rb.get("fallback") not in (None, "escalate")):
        raise ValueError(f"{origin}: {name}: root_cause none allows only escalate")
    if not 0 <= float(rb["confidence"]) <= 1:
        raise ValueError(f"{origin}: {name}: confidence must be 0..1")
    unknown = set(rb["match"] or {}) - {"alert", "down", "only_alerts", "ml_feature"}
    if not rb["match"] or unknown:
        raise ValueError(f"{origin}: {name}: bad match keys {sorted(unknown) or '(empty)'}")


def load_runbooks(directory=None):
    """All runbooks from *.yaml / *.yml, sorted by priority. Fails loudly on a bad file."""
    directory = Path(directory or RUNBOOK_DIR)
    files = sorted(list(directory.glob("*.yaml")) + list(directory.glob("*.yml")))
    if not files:
        raise FileNotFoundError(f"no runbooks in {directory}")

    runbooks = []
    for f in files:
        for rb in yaml.safe_load(f.read_text()) or []:
            validate_runbook(rb, f.name)
            runbooks.append(rb)

    names = [rb["name"] for rb in runbooks]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise ValueError(f"duplicate runbook names: {sorted(dupes)}")

    return sorted(runbooks, key=lambda rb: rb["priority"])


# -----------------------------
# Topology and signal helpers
# -----------------------------

def depths(topology):
    """Distance from the entry point(s): frontend 0, api-service 1, redis 2."""
    nodes = set(topology) | {d for deps in topology.values() for d in deps}
    called = {d for deps in topology.values() for d in deps}
    depth = {n: 0 for n in nodes if n not in called}
    frontier = list(depth)
    while frontier:
        nxt = []
        for n in frontier:
            for d in topology.get(n, []):
                if d not in depth:
                    depth[d] = depth[n] + 1
                    nxt.append(d)
        frontier = nxt
    return depth


def deepest(services, topology):
    """The service furthest down the chain; ties keep the input order."""
    known = [s for s in services if s in SERVICES]
    if not known:
        return None
    depth = depths(topology)
    return max(known, key=lambda s: depth.get(s, -1))


def alert_services(incident, names):
    return [a.service for a in incident.firing_alerts() if a.name in names and a.service]


def has_alert(incident, name, service):
    return any(a.name == name and a.service == service for a in incident.firing_alerts())


def is_down(incident, service):
    return incident.ctx(service).up == 0 or has_alert(incident, "ServiceDown", service) \
        or (service == "redis" and has_alert(incident, "RedisDown", service))


def own_errors(incident, service):
    err = incident.ctx(service).err
    return has_alert(incident, "HighErrorRate", service) or (err is not None and err >= ERR_THRESHOLD)


def p95_of(incident, service):
    """Current p95, or the firing HighLatency value when the context has none."""
    p95 = incident.ctx(service).p95
    if p95 is not None:
        return p95
    vals = [a.value for a in incident.firing_alerts()
            if a.name == "HighLatency" and a.service == service and a.value is not None]
    return max(vals) if vals else None


def is_slow(incident, service):
    p95 = incident.ctx(service).p95
    return has_alert(incident, "HighLatency", service) or (p95 is not None and p95 >= LATENCY_THRESHOLD)


# -----------------------------
# Root-cause strategies
# -----------------------------

def deepest_service_with_errors(incident):
    """Deepest service with its own errors whose dependencies are all healthy."""
    topo = incident.topology
    erroring = [s for s in SERVICES if own_errors(incident, s)]

    def deps_healthy(s):
        return all(not is_down(incident, d) and not own_errors(incident, d) for d in topo.get(s, []))

    return deepest([s for s in erroring if deps_healthy(s)], topo) or deepest(erroring, topo)


def latency_origin(incident):
    """Start at the shallowest slow service and walk down while its upstream
    explains its latency (upstream_p95 >= half of p95 and a dependency is slow)."""
    topo = incident.topology
    depth = depths(topo)
    slow = sorted((s for s in SERVICES if is_slow(incident, s)), key=lambda s: depth.get(s, 99))
    if not slow:
        return None

    current, seen = slow[0], set()
    while current not in seen:
        seen.add(current)
        p95, up95 = p95_of(incident, current), incident.ctx(current).upstream_p95
        slow_deps = [d for d in topo.get(current, []) if is_slow(incident, d)]
        if not slow_deps or p95 is None or up95 is None or up95 < EXPLAINED_SHARE * p95:
            return current
        current = deepest(slow_deps, topo) or current
    return current


def top_ml_anomaly(incident, feature):
    hits = [m for m in incident.ml_anomalies
            if m.service in SERVICES and any(feature in f for f in m.top_features)]
    if not hits:
        return None
    return max(hits, key=lambda m: m.score if m.score is not None else 0.0).service


# -----------------------------
# Matching
# -----------------------------

def match(rb, incident):
    """Services that triggered the runbook, or None if it doesn't match.
    An empty list means it matched without naming a service."""
    m = rb["match"]
    firing = incident.firing_alerts()
    hit, services = False, []

    names = as_list(m.get("alert"))
    if names:
        found = alert_services(incident, names)
        if any(a.name in names for a in firing):
            hit = True
        services += found

    for svc in as_list(m.get("down")):
        if incident.ctx(svc).up == 0:
            hit = True
            services.append(svc)

    only = as_list(m.get("only_alerts"))
    if only and firing and all(a.name in only for a in firing):
        hit = True

    feature = m.get("ml_feature")
    if feature:
        svc = top_ml_anomaly(incident, feature)
        if svc:
            hit = True
            services.append(svc)

    return services if hit else None


def resolve_root(rb, incident, matched):
    """(found, root). found is False when the strategy can't name a service,
    so the next runbook gets a chance."""
    rc = rb["root_cause"]
    if rc == "none":
        return True, None
    if rc in SERVICES:
        return True, rc
    if rc == "matched_service":
        root = deepest(matched, incident.topology)
    elif rc == "deepest_service_with_errors":
        root = deepest_service_with_errors(incident)
    elif rc == "latency_origin":
        root = latency_origin(incident)
    else:  # top_ml_anomaly
        root = top_ml_anomaly(incident, rb["match"].get("ml_feature") or "")
    return root is not None, root


def previous_action_keys(incident):
    keys = set()
    for p in incident.history.previous_actions:
        a = p.get("action") if isinstance(p.get("action"), dict) else p
        if a.get("type"):
            keys.add((a.get("type"), a.get("target")))
    return keys


def choose_actions(rb, root, incident):
    """(recommended, fallback), skipping actions already tried for this incident."""
    tried = previous_action_keys(incident)
    # redis has no /reset; never emit reset_faults where it can't run
    candidates = [t for t in (rb["action"], rb.get("fallback"))
                  if t and not (t == "reset_faults" and root not in RESETTABLE)]
    fresh = [t for t in candidates if t == "escalate" or (t, root) not in tried]
    if not fresh:
        fresh = ["escalate"]
    rec = Action(type=fresh[0], target=root)
    if len(fresh) > 1:
        fb = Action(type=fresh[1], target=root)
    else:
        # Out of runbook actions: a human is the last resort
        fb = Action(type="escalate", target=root) if rec.type != "escalate" else None
    return rec, fb, len(fresh) < len(candidates)


def evidence_for(incident, root):
    ev = [f"{a.name} firing on {a.service}" + (f" (value {a.value:g}, threshold {a.threshold:g})"
          if a.value is not None and a.threshold is not None else "")
          for a in incident.firing_alerts()]
    for s in SERVICES:
        c = incident.context.get(s)
        if c is None:
            continue
        parts = [f"{k}={getattr(c, k):g}" for k in ("up", "cpu", "mem", "p95", "err", "upstream_p95", "ops")
                 if getattr(c, k) is not None]
        if parts:
            ev.append(f"{s}: " + ", ".join(parts))
    for m in incident.ml_anomalies:
        ev.append(f"ML anomaly on {m.service} (score {m.score}, features {', '.join(m.top_features)})")
    return ev


def run_runbooks(incident, runbooks, fallback_reason=None, latency_ms=0.0):
    """First matching runbook -> ResponsePlan. No match -> escalate, type unknown."""
    for rb in runbooks:
        matched = match(rb, incident)
        if matched is None:
            continue
        found, root = resolve_root(rb, incident, matched)
        if not found:
            continue

        rec, fb, skipped = choose_actions(rb, root, incident)
        cause = rb.get("description") or rb["name"]
        expl = f"Runbook {rb['name']} matched; root cause {root or 'outside the app services'}."
        if skipped:
            expl += " Actions already tried for this incident were skipped."
        return ResponsePlan(
            incident_id=incident.incident_id,
            root_cause_service=root,
            incident_type=rb["incident_type"],
            severity=rb["severity"],
            probable_cause=cause,
            evidence=evidence_for(incident, root),
            confidence=float(rb["confidence"]),
            recommended_action=rec,
            fallback_action=fb,
            explanation=expl,
            source="runbook",
            model=None,
            runbook=rb["name"],
            fallback_reason=fallback_reason,
            attempt=incident.history.attempt,
            latency_ms=latency_ms,
            created_at=now_iso(),
        )

    # Nothing matched: a human decides. Best-guess target, nothing executed.
    guess = deepest([a.service for a in incident.firing_alerts()]
                    + [m.service for m in incident.ml_anomalies], incident.topology)
    return ResponsePlan(
        incident_id=incident.incident_id,
        root_cause_service=guess,
        incident_type="unknown",
        severity="medium",
        probable_cause="No runbook matched the alerts and anomalies in this incident.",
        evidence=evidence_for(incident, guess),
        confidence=0.5,
        recommended_action=Action(type="escalate", target=guess),
        fallback_action=None,
        explanation="Escalated to a human; no automatic action is safe without a matching runbook.",
        source="runbook",
        model=None,
        runbook="no-match",
        fallback_reason=fallback_reason,
        attempt=incident.history.attempt,
        latency_ms=latency_ms,
        created_at=now_iso(),
    )
