"""Event Gateway (SUGGESTED_PLAN.md §6.3).

Inputs:
  POST /alerts      Alertmanager webhook (rules)
  POST /anomalies   ML detector: {"service", "score", "top_features": [...]}
  POST /responses   ResponsePlan from the analyzer (also accepted as a
                    message on /ws/responses)
  POST /actions     responder report (validated / executed / verified ...)
  POST /incidents/{id}/reanalyze   verifier: fix failed, analyze again

Outputs:
  /ws/events        every raw alert ("type": "alert") and every incident
                    update ("type": "incident", status open | updated |
                    reanalyze | resolved)
  /ws/responses     every ResponsePlan ("type": "response_plan") and every
                    responder report ("type": "action")
  GET /events, /responses, /incidents, /incidents/{id}, /health
  GET /history, /history/{id}   incident store (SQLite, INCIDENT_DB)
  GET /dashboard/   minimal UI (dashboard/index.html)

Flow: alerts and anomalies are grouped into incidents (incidents.py). A new
incident waits SETTLE_SECONDS so the symptom alerts that fire with the root
cause (e.g. HighLatency on frontend and api-service) land in the same
"open" message, then the context builder (context.py) attaches the last
10 minutes of metrics and the incident goes out. Later changes go out as
"updated", and "resolved" goes out once nothing is firing.

Rules for whatever this grows into:
- Every alert has a `service` label (frontend | api-service | redis, or
  monitoring for ExporterDown). It is the key onto the topology.
- Resolved notifications carry the annotation text from the last time the
  alert fired, so never read metric values from them.
- fault_* metrics are ground truth for scoring only. Nothing derived from
  them may leave the gateway; labels with that prefix are dropped.

Usage:
  uvicorn app:app --host 0.0.0.0 --port 8000
  websocat ws://localhost:8000/ws/events
"""

import asyncio
import json
import logging
import os
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from context import ContextBuilder, alert_value
from incidents import TOPOLOGY, Grouper, iso
from store import Store

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
GROUP_WINDOW = float(os.environ.get("GROUP_WINDOW", "60"))
SETTLE_SECONDS = float(os.environ.get("SETTLE_SECONDS", "10"))
CONTEXT_MINUTES = int(os.environ.get("CONTEXT_MINUTES", "10"))
# SQLite file for the incident store; ":memory:" (default) keeps nothing
INCIDENT_DB = os.environ.get("INCIDENT_DB", ":memory:")
DASHBOARD_DIR = os.environ.get("DASHBOARD_DIR", os.path.join(os.path.dirname(__file__), "..", "dashboard"))
SWEEP_SECONDS = 5

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gateway")
# One line per Prometheus query drowns out the incident log
logging.getLogger("httpx").setLevel(logging.WARNING)


def docker_or_none():
    """Docker client for container state, if the socket is mounted."""
    try:
        import docker
        client = docker.from_env()
        client.ping()
        return client
    except Exception as e:
        log.info("docker unavailable, container state will be null (%s)", e.__class__.__name__)
        return None


grouper = Grouper(window=GROUP_WINDOW)
store = Store(INCIDENT_DB)
builder = ContextBuilder(PROMETHEUS_URL, minutes=CONTEXT_MINUTES)
stats = {"webhooks": 0, "alerts": 0, "anomalies": 0, "incidents": 0, "responses": 0}


class Hub:
    """A WebSocket channel: broadcast to all clients, replay recent on connect."""

    def __init__(self, name, keep=100):
        self.name = name
        self.recent = deque(maxlen=keep)
        self.clients = set()

    async def broadcast(self, msg):
        self.recent.append(msg)
        store.add(self.name, msg, now_iso())
        text = json.dumps(msg)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        self.clients.difference_update(dead)

    async def serve(self, ws, on_message=None):
        await ws.accept()
        for msg in list(self.recent):
            await ws.send_text(json.dumps({**msg, "replay": True}))
        self.clients.add(ws)
        log.info("%s: client connected (%d total)", self.name, len(self.clients))
        try:
            while True:
                text = await ws.receive_text()
                if on_message:
                    await on_message(ws, text)
        except WebSocketDisconnect:
            pass
        finally:
            self.clients.discard(ws)
            log.info("%s: client disconnected (%d total)", self.name, len(self.clients))


events_hub = Hub("ws/events")
responses_hub = Hub("ws/responses")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _reject_constant(name):
    raise ValueError(f"{name} is not valid JSON")


def strict_loads(raw):
    """json.loads without NaN/Infinity. Python accepts them, but they aren't
    JSON: once stored or replayed they make every JSON response that includes
    them fail (FastAPI raises on NaN) and browsers can't parse them."""
    return json.loads(raw, parse_constant=_reject_constant)


async def read_json(request):
    return strict_loads(await request.body())


def without_ground_truth(d):
    return {k: v for k, v in (d or {}).items() if not k.startswith("fault_")}


def to_event(alert, group_status):
    """One Alertmanager alert -> raw alert message."""
    labels = without_ground_truth(alert.get("labels"))
    status = alert.get("status") or group_status
    event = {
        "type": "alert",
        "source": "rule",
        "received_at": now_iso(),
        "fingerprint": alert.get("fingerprint"),
        "alertname": labels.get("alertname"),
        "service": labels.get("service"),
        "status": status,
        "severity": labels.get("severity"),
        "category": labels.get("category"),
        "startsAt": alert.get("startsAt"),
        "endsAt": alert.get("endsAt") if status == "resolved" else None,
        "labels": labels,
    }
    # Annotations on a resolved alert are stale (values from the last firing)
    if status == "firing":
        event["annotations"] = without_ground_truth(alert.get("annotations"))
    return event


# -----------------------------
# Incident messages
# -----------------------------

async def incident_message(inc, status):
    context = await builder.build()
    alerts = []
    for a in inc.alerts.values():
        value, threshold = alert_value(a, context) if a["status"] == "firing" else (None, None)
        alerts.append({"name": a["alertname"], "service": a["service"], "status": a["status"],
                       "severity": a["severity"], "category": a["category"],
                       "startsAt": a["startsAt"], "value": value, "threshold": threshold})
    anomalies = [{k: v for k, v in m.items() if not k.startswith("_")} for m in inc.anomalies]
    return {
        "type": "incident",
        "incident_id": inc.id,
        "status": status,
        "timestamp": now_iso(),
        "opened_at": iso(inc.opened_at),
        "resolved_at": iso(inc.resolved_at) if inc.resolved else None,
        "sources": inc.sources(),
        "services": inc.services(),
        "alerts": alerts,
        "ml_anomalies": anomalies,
        "topology": TOPOLOGY,
        "context": context,
        # Filled in from the responder's action reports (§6.6)
        "history": {"attempt": inc.attempt, "previous_actions": list(inc.actions)},
    }


async def emit_later(inc):
    """Wait for related alerts to arrive, then send open/updated."""
    await asyncio.sleep(SETTLE_SECONDS)
    inc.pending = False
    if inc.resolved:
        return
    status = "updated" if inc.emitted else "open"
    msg = await incident_message(inc, status)
    if inc.resolved:  # resolved while the context was being built
        return
    inc.emitted = True
    log.info("incident %s %s services=%s alerts=%s", inc.id, status, msg["services"],
             [f'{a["name"]}/{a["service"]}' for a in msg["alerts"] if a["status"] == "firing"])
    await events_hub.broadcast(msg)


def schedule(inc, change):
    if change is None:
        return
    if change == "new":
        stats["incidents"] += 1
    if not inc.pending:
        inc.pending = True
        asyncio.create_task(emit_later(inc))


async def emit_resolved(inc):
    msg = await incident_message(inc, "resolved")
    log.info("incident %s resolved after %.0fs", inc.id, inc.resolved_at - inc.opened_at)
    await events_hub.broadcast(msg)


async def sweeper():
    while True:
        await asyncio.sleep(SWEEP_SECONDS)
        for inc in grouper.sweep():
            await emit_resolved(inc)


@asynccontextmanager
async def lifespan(_app):
    builder.docker = await asyncio.to_thread(docker_or_none)
    task = asyncio.create_task(sweeper())
    yield
    task.cancel()


app = FastAPI(title="Event Gateway", lifespan=lifespan)


# -----------------------------
# Inputs
# -----------------------------

@app.post("/alerts")
async def alerts(request: Request):
    try:
        body = await read_json(request)
    except Exception:
        return JSONResponse({"error": "body must be JSON"}, status_code=400)
    if not isinstance(body, dict) or not isinstance(body.get("alerts"), list):
        return JSONResponse({"error": "expected an Alertmanager webhook with alerts[]"}, status_code=400)

    stats["webhooks"] += 1
    group_status = body.get("status")
    events = [to_event(a, group_status) for a in body["alerts"] if isinstance(a, dict)]
    for e in events:
        log.info("%s %s service=%s severity=%s startsAt=%s",
                 (e["status"] or "?").upper(), e["alertname"], e["service"], e["severity"], e["startsAt"])
        if not e["service"]:
            log.warning("alert %s has no service label; check rules.yml", e["alertname"])
        if not e["fingerprint"]:
            log.warning("alert %s has no fingerprint; not grouped", e["alertname"])
        await events_hub.broadcast(e)
        stats["alerts"] += 1

        if not e["fingerprint"]:
            continue
        if e["status"] == "firing":
            schedule(*grouper.add_alert(e))
        elif e["status"] == "resolved":
            inc = grouper.resolve_alert(e)
            if inc is not None:
                await emit_resolved(inc)
    return {"accepted": len(events)}


@app.post("/anomalies")
async def anomalies(request: Request):
    try:
        body = await read_json(request)
    except Exception:
        return JSONResponse({"error": "body must be JSON"}, status_code=400)
    if not isinstance(body, dict) or body.get("service") not in TOPOLOGY:
        return JSONResponse({"error": f"expected {{service, score, top_features}}, service in {list(TOPOLOGY)}"},
                            status_code=400)
    anomaly = {
        "service": body["service"],
        "score": body.get("score"),
        "top_features": [f for f in body.get("top_features") or [] if not str(f).startswith("fault_")],
        "detected_at": body.get("timestamp") or now_iso(),
    }
    stats["anomalies"] += 1
    log.info("ANOMALY service=%s score=%s features=%s", anomaly["service"], anomaly["score"], anomaly["top_features"])
    inc, change = grouper.add_anomaly(anomaly)
    schedule(inc, change)
    return {"incident_id": inc.id}


async def accept_response(plan):
    if not isinstance(plan, dict) or not plan.get("incident_id"):
        return "expected a ResponsePlan with incident_id"
    if plan["incident_id"] not in grouper.incidents:
        log.warning("response for unknown incident %s (gateway restarted?)", plan["incident_id"])
    stats["responses"] += 1
    msg = {k: v for k, v in plan.items() if k != "replay"}
    msg.update(type="response_plan", received_at=now_iso())
    rec = msg.get("recommended_action") or {}
    log.info("PLAN %s root=%s action=%s/%s confidence=%s source=%s", msg["incident_id"],
             msg.get("root_cause_service"), rec.get("type"), rec.get("target"),
             msg.get("confidence"), msg.get("source"))
    await responses_hub.broadcast(msg)
    return None


# Action records from the responder that count as "tried" for re-analysis
TRIED = {"executed", "failed"}


@app.post("/actions")
async def actions(request: Request):
    """Responder report: validation outcome, execution, verification.

    Broadcast on /ws/responses as type "action". Executed or failed actions
    are added to the incident's history.previous_actions.
    """
    try:
        rec = await read_json(request)
    except Exception:
        return JSONResponse({"error": "body must be JSON"}, status_code=400)
    if not isinstance(rec, dict) or not rec.get("incident_id") or not rec.get("status"):
        return JSONResponse({"error": "expected {incident_id, status, action, ...}"}, status_code=400)
    inc = grouper.incidents.get(rec["incident_id"])
    action = rec.get("action") or {}
    if inc is not None and rec["status"] in TRIED and action.get("type"):
        inc.actions.append({"type": action["type"], "target": action.get("target"),
                            "attempt": rec.get("attempt"), "status": rec["status"], "at": now_iso()})
    msg = {k: v for k, v in rec.items() if k != "replay"}
    msg.update(type="action", received_at=now_iso())
    log.info("ACTION %s %s %s/%s %s", msg["incident_id"], msg["status"], action.get("type"),
             action.get("target"), msg.get("reason") or "")
    await responses_hub.broadcast(msg)
    return {"accepted": True}


@app.post("/incidents/{incident_id}/reanalyze")
async def reanalyze(incident_id: str, request: Request):
    """Verifier: the fix didn't work. Re-send the incident with attempt + history."""
    inc = grouper.incidents.get(incident_id)
    if inc is None:
        return JSONResponse({"error": "unknown incident"}, status_code=404)
    if inc.resolved:
        return JSONResponse({"error": "incident already resolved"}, status_code=409)
    try:
        body = await read_json(request)
        attempt = int(body["attempt"])
    except Exception:
        return JSONResponse({"error": "expected {attempt: int}"}, status_code=400)
    inc.attempt = max(inc.attempt, attempt)
    msg = await incident_message(inc, "reanalyze")
    log.info("incident %s reanalyze attempt=%d previous=%s", inc.id, inc.attempt,
             [f'{a["type"]}/{a["target"]}' for a in inc.actions])
    await events_hub.broadcast(msg)
    return {"attempt": inc.attempt}


@app.post("/responses")
async def responses(request: Request):
    try:
        plan = await read_json(request)
    except Exception:
        return JSONResponse({"error": "body must be JSON"}, status_code=400)
    error = await accept_response(plan)
    if error:
        return JSONResponse({"error": error}, status_code=400)
    return {"accepted": True}


# -----------------------------
# Outputs
# -----------------------------

@app.get("/events")
async def recent_events():
    return list(events_hub.recent)


@app.get("/responses")
async def recent_responses():
    return list(responses_hub.recent)


def summary(inc):
    return {"incident_id": inc.id, "opened_at": iso(inc.opened_at),
            "resolved_at": iso(inc.resolved_at) if inc.resolved else None,
            "services": inc.services(), "sources": inc.sources(),
            "firing": sorted(f'{a["alertname"]}/{a["service"]}' for a in inc.firing()),
            "anomalies": len(inc.anomalies), "attempt": inc.attempt, "actions": list(inc.actions)}


@app.get("/incidents")
async def incidents():
    return [summary(i) for i in reversed(list(grouper.incidents.values()))]


@app.get("/incidents/{incident_id}")
async def incident(incident_id: str):
    inc = grouper.incidents.get(incident_id)
    if inc is None:
        return JSONResponse({"error": "unknown incident"}, status_code=404)
    status = "resolved" if inc.resolved else ("open" if inc.emitted else "pending")
    return await incident_message(inc, status)


@app.get("/history")
async def history():
    """Incidents in the store, newest first (survives gateway restarts)."""
    return store.incidents()


@app.get("/history/{incident_id}")
async def incident_history(incident_id: str):
    """Full timeline: incident updates, plans, actions, verification."""
    timeline = store.timeline(incident_id)
    if not timeline:
        return JSONResponse({"error": "unknown incident"}, status_code=404)
    return timeline


@app.get("/health")
async def health():
    return {"status": "ok", "clients": {"events": len(events_hub.clients), "responses": len(responses_hub.clients)},
            "open_incidents": sum(not i.resolved for i in grouper.incidents.values()), **stats}


@app.websocket("/ws/events")
async def ws_events(ws: WebSocket):
    await events_hub.serve(ws)


@app.websocket("/ws/responses")
async def ws_responses(ws: WebSocket):
    async def on_message(sender, text):
        try:
            error = await accept_response(strict_loads(text))
        except ValueError:  # JSONDecodeError, NaN/Infinity
            error = "message must be valid JSON"
        if error:
            await sender.send_text(json.dumps({"type": "error", "error": error}))
    await responses_hub.serve(ws, on_message)


# Minimal dashboard (§6.8): http://localhost:8000/dashboard/
if os.path.isdir(DASHBOARD_DIR):
    app.mount("/dashboard", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")
else:
    log.info("no dashboard at %s", DASHBOARD_DIR)
