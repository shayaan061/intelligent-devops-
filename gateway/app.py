"""Event Gateway, skeleton (SUGGESTED_PLAN.md §6.3, §15).

Receives Alertmanager webhooks on POST /alerts, turns each alert into a
minimal IncidentEvent-shaped message, logs it and broadcasts it to every
client on the /ws/events WebSocket.

Not here yet (rest of Phase 3): POST /anomalies, 60 s grouping along the
dependency chain into incidents, the PromQL context builder, /ws/responses.

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
from collections import deque
from datetime import datetime, timezone

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gateway")

app = FastAPI(title="Event Gateway")

# Sent to clients on connect, so a dashboard opened mid-incident has history
RECENT = deque(maxlen=100)

clients: set[WebSocket] = set()
clients_lock = asyncio.Lock()

stats = {"webhooks": 0, "events": 0}


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def without_ground_truth(d):
    return {k: v for k, v in (d or {}).items() if not k.startswith("fault_")}


def to_event(alert, group_status):
    """One Alertmanager alert -> minimal IncidentEvent-shaped message."""
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


async def broadcast(event):
    RECENT.append(event)
    stats["events"] += 1
    msg = json.dumps(event)
    async with clients_lock:
        targets = list(clients)
    dead = []
    for ws in targets:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    if dead:
        async with clients_lock:
            clients.difference_update(dead)


@app.post("/alerts")
async def alerts(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "body must be JSON"}, status_code=400)
    if not isinstance(body, dict) or not isinstance(body.get("alerts"), list):
        return JSONResponse({"error": "expected an Alertmanager webhook with alerts[]"}, status_code=400)

    stats["webhooks"] += 1
    group_status = body.get("status")
    events = [to_event(a, group_status) for a in body["alerts"] if isinstance(a, dict)]
    for e in events:
        log.info("%s %s service=%s severity=%s startsAt=%s",
                 e["status"].upper() if e["status"] else "?", e["alertname"],
                 e["service"], e["severity"], e["startsAt"])
        if not e["service"]:
            log.warning("alert %s has no service label; check rules.yml", e["alertname"])
        await broadcast(e)
    return {"accepted": len(events)}


@app.get("/events")
async def recent_events():
    return list(RECENT)


@app.get("/health")
async def health():
    async with clients_lock:
        n = len(clients)
    return {"status": "ok", "clients": n, **stats}


@app.websocket("/ws/events")
async def ws_events(ws: WebSocket):
    await ws.accept()
    for e in list(RECENT):
        await ws.send_text(json.dumps({**e, "replay": True}))
    async with clients_lock:
        clients.add(ws)
    log.info("ws client connected (%d total)", len(clients))
    try:
        # Clients don't send anything meaningful; this just waits for the close
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        async with clients_lock:
            clients.discard(ws)
        log.info("ws client disconnected (%d total)", len(clients))
