"""Dedup and grouping of alerts and ML anomalies into incidents (§6.3).

Rules:
- An alert is identified by its Alertmanager fingerprint. A repeat of a
  firing alert (repeat_interval) is a no-op, not a new event.
- A new alert or anomaly joins the open incident on the same dependency
  chain (frontend -> api-service -> redis); otherwise it opens a new one.
  An incident stays open while it has a firing alert or an ML anomaly from
  the last `window` seconds, so everything within 60 s of the last activity
  lands in one incident.
- An incident resolves once none of its alerts is firing and its ML
  anomalies are older than `window`. A later alert opens a new incident.

Pure and synchronous (the clock is injectable) so it can be unit-tested;
app.py does the I/O.
"""

import itertools
import time
from datetime import datetime, timezone

TOPOLOGY = {"frontend": ["api-service"], "api-service": ["redis"], "redis": []}

# Each service maps to the chain it belongs to. Everything outside the
# topology (ExporterDown has service="monitoring") is grouped on its own.
CHAIN = {svc: "app" for svc in TOPOLOGY}


def chain_of(service):
    return CHAIN.get(service, service or "unknown")


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Incident:
    def __init__(self, incident_id, chain, now):
        self.id = incident_id
        self.chain = chain
        self.opened_at = now
        self.last_activity = now
        self.resolved_at = None
        self.alerts = {}        # fingerprint -> alert dict (see Grouper.add_alert)
        self.anomalies = []     # ML anomaly dicts, newest last
        self.emitted = False    # has the "open" message gone out
        self.pending = False    # is an emit scheduled (app.py)

    @property
    def resolved(self):
        return self.resolved_at is not None

    def firing(self):
        return [a for a in self.alerts.values() if a["status"] == "firing"]

    def services(self):
        svcs = {a["service"] for a in self.alerts.values()} | {m["service"] for m in self.anomalies}
        return sorted(s for s in svcs if s)

    def sources(self):
        out = []
        if self.alerts:
            out.append("rule")
        if self.anomalies:
            out.append("ml")
        return out


class Grouper:
    def __init__(self, window=60, clock=time.time):
        self.window = window
        self.clock = clock
        self.incidents = {}     # id -> Incident, every incident ever seen (in memory)
        self._seq = itertools.count(1)

    def _new_id(self, now):
        stamp = datetime.fromtimestamp(now, timezone.utc).strftime("%y%m%d-%H%M%S")
        return f"inc-{stamp}-{next(self._seq)}"

    def open_incident(self, chain):
        for inc in reversed(list(self.incidents.values())):
            if inc.chain == chain and not inc.resolved:
                return inc
        return None

    def _join_or_open(self, service, now):
        chain = chain_of(service)
        inc = self.open_incident(chain)
        if inc is None:
            inc = Incident(self._new_id(now), chain, now)
            self.incidents[inc.id] = inc
            return inc, "new"
        return inc, "changed"

    def add_alert(self, alert):
        """A firing alert. Returns (incident, "new" | "changed" | None)."""
        now = self.clock()
        fp = alert["fingerprint"]
        for inc in self.incidents.values():
            if not inc.resolved and fp in inc.alerts:
                known = inc.alerts[fp]
                if known["status"] == "firing":
                    return inc, None  # Alertmanager repeat
                known.update(alert, status="firing", endsAt=None)
                inc.last_activity = now
                return inc, "changed"

        inc, change = self._join_or_open(alert["service"], now)
        inc.alerts[fp] = {**alert, "status": "firing"}
        inc.last_activity = now
        return inc, change

    def resolve_alert(self, alert):
        """A resolved alert. Returns the incident if it just resolved, else None."""
        now = self.clock()
        for inc in self.incidents.values():
            known = inc.alerts.get(alert["fingerprint"])
            if not inc.resolved and known is not None:
                known.update(status="resolved", endsAt=alert.get("endsAt"))
                inc.last_activity = now
                return inc if self._maybe_resolve(inc, now) else None
        return None

    def add_anomaly(self, anomaly):
        """An ML anomaly. Returns (incident, "new" | "changed")."""
        now = self.clock()
        inc, change = self._join_or_open(anomaly["service"], now)
        inc.anomalies.append({**anomaly, "_at": now})
        inc.last_activity = now
        return inc, change

    def _maybe_resolve(self, inc, now):
        if inc.firing():
            return False
        if any(now - m["_at"] < self.window for m in inc.anomalies):
            return False
        inc.resolved_at = now
        return True

    def sweep(self):
        """Resolve incidents whose last ML anomaly aged out. Returns them."""
        now = self.clock()
        return [inc for inc in list(self.incidents.values())
                if not inc.resolved and self._maybe_resolve(inc, now)]
