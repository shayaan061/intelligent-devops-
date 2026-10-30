"""Gateway tests: grouping, context builder, endpoints and WebSockets.

Run from gateway/:  pip install -r requirements-dev.txt && pytest -q
Prometheus is faked with httpx.MockTransport; no Docker needed.
"""

import os
import sys
import time

import httpx
import pytest

os.environ["SETTLE_SECONDS"] = "0.2"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as gw  # noqa: E402
from context import SERVICE_QUERIES, ContextBuilder, clean  # noqa: E402
from incidents import Grouper  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


def alert(name, service, fp, status="firing"):
    return {"alertname": name, "service": service, "fingerprint": fp, "status": status,
            "severity": "warning", "category": "http", "startsAt": "2026-10-06T10:00:00Z"}


# -----------------------------
# Grouping
# -----------------------------

def test_symptom_alerts_group_into_one_incident():
    g = Grouper(clock=Clock())
    inc, change = g.add_alert(alert("HighLatency", "api-service", "a"))
    assert change == "new"
    inc2, change = g.add_alert(alert("HighLatency", "frontend", "b"))
    assert inc2 is inc and change == "changed"
    assert inc.services() == ["api-service", "frontend"]


def test_repeat_notification_is_not_a_change():
    g = Grouper(clock=Clock())
    g.add_alert(alert("HighLatency", "api-service", "a"))
    _, change = g.add_alert(alert("HighLatency", "api-service", "a"))
    assert change is None


def test_resolves_when_last_alert_resolves_then_new_incident():
    g = Grouper(clock=Clock())
    inc, _ = g.add_alert(alert("HighLatency", "api-service", "a"))
    g.add_alert(alert("HighLatency", "frontend", "b"))
    assert g.resolve_alert(alert("HighLatency", "api-service", "a", "resolved")) is None
    assert g.resolve_alert(alert("HighLatency", "frontend", "b", "resolved")) is inc
    assert inc.resolved
    inc2, change = g.add_alert(alert("HighLatency", "api-service", "a"))
    assert change == "new" and inc2 is not inc


def test_monitoring_alerts_are_a_separate_incident():
    g = Grouper(clock=Clock())
    inc, _ = g.add_alert(alert("HighErrorRate", "frontend", "a"))
    mon, change = g.add_alert(alert("ExporterDown", "monitoring", "m"))
    assert change == "new" and mon is not inc


def test_ml_anomaly_keeps_incident_open_for_window():
    clock = Clock()
    g = Grouper(window=60, clock=clock)
    inc, change = g.add_anomaly({"service": "api-service", "score": 0.9, "top_features": ["mem"]})
    assert change == "new" and inc.sources() == ["ml"]
    _, change = g.add_alert(alert("HighMemory", "api-service", "a"))
    assert change == "changed" and inc.sources() == ["rule", "ml"]
    clock.t += 30
    assert g.resolve_alert(alert("HighMemory", "api-service", "a", "resolved")) is None  # anomaly is recent
    assert g.sweep() == []
    clock.t += 31
    assert g.sweep() == [inc]


def test_verified_fix_closes_without_the_anomaly_window():
    # 16 Oct: the next scenario started 60 s after a verified fix, joined the
    # still-open incident and was skipped as "incident already handled"
    clock = Clock()
    g = Grouper(window=60, clock=clock)
    inc, _ = g.add_anomaly({"service": "api-service", "score": 0.9, "top_features": ["cpu"]})
    g.add_alert(alert("HighCPU", "api-service", "a"))
    clock.t += 40
    g.resolve_alert(alert("HighCPU", "api-service", "a", "resolved"))
    assert not inc.resolved  # anomaly 40 s old, window 60 s
    assert g.mark_verified(inc.id, fresh=20) is inc and inc.resolved
    nxt, change = g.add_alert(alert("HighMemory", "api-service", "b"))
    assert change == "new" and nxt is not inc


def test_verified_report_never_closes_a_firing_or_fresh_incident():
    clock = Clock()
    g = Grouper(window=60, clock=clock)
    inc, _ = g.add_alert(alert("HighCPU", "api-service", "a"))
    assert g.mark_verified(inc.id, fresh=20) is None and not inc.resolved  # alert still firing
    g.add_anomaly({"service": "api-service", "score": 0.9, "top_features": ["cpu"]})
    clock.t += 10
    assert g.resolve_alert(alert("HighCPU", "api-service", "a", "resolved")) is None  # anomaly 10 s old
    clock.t += 11
    assert g.sweep() == [inc]  # 21 s > fresh, without waiting for the 60 s window
    assert g.mark_verified(inc.id, fresh=20) is None  # already resolved
    assert g.mark_verified("inc-nope", fresh=20) is None


def test_repeat_anomaly_refreshes_without_change():
    clock = Clock()
    g = Grouper(window=60, clock=clock)
    inc, _ = g.add_anomaly({"service": "api-service", "score": 0.6, "top_features": ["mem"],
                            "detected_at": "first"})
    for _ in range(6):  # 90 s of re-posts every 15 s
        clock.t += 15
        again, change = g.add_anomaly({"service": "api-service", "score": 0.8, "top_features": ["mem", "cpu"],
                                       "detected_at": "later"})
        assert again is inc and change is None
    assert len(inc.anomalies) == 1 and inc.anomalies[0]["score"] == 0.8
    assert inc.anomalies[0]["detected_at"] == "first"
    assert g.sweep() == [] and inc.ml_active(clock.t, 20) == ["api-service"]
    _, change = g.add_anomaly({"service": "frontend", "score": 0.7, "top_features": ["p95"]})
    assert change == "changed"  # a new service is news
    clock.t += 30
    assert inc.ml_active(clock.t, 20) == []
    clock.t += 31
    assert g.sweep() == [inc]


def test_refire_in_same_open_incident_is_a_change():
    g = Grouper(clock=Clock())
    inc, _ = g.add_alert(alert("HighLatency", "api-service", "a"))
    g.add_alert(alert("HighLatency", "frontend", "b"))
    g.resolve_alert(alert("HighLatency", "frontend", "b", "resolved"))
    inc2, change = g.add_alert(alert("HighLatency", "frontend", "b"))
    assert inc2 is inc and change == "changed"


# -----------------------------
# Context builder
# -----------------------------

def fake_prometheus(value_for):
    """MockTransport answering query_range with a constant per query."""
    seen = []

    def handler(request):
        q = request.url.params["query"]
        seen.append(q)
        start, end, step = (float(request.url.params[k]) for k in ("start", "end", "step"))
        v = value_for(q)
        values = [] if v is None else [[start + i * step, v] for i in range(int((end - start) // step) + 1)]
        result = [{"metric": {}, "values": values}] if values else []
        return httpx.Response(200, json={"status": "success", "data": {"resultType": "matrix", "result": result}})

    return httpx.MockTransport(handler), seen


def test_no_query_touches_ground_truth():
    for qs in SERVICE_QUERIES.values():
        for q in qs.values():
            assert "fault_" not in q


@pytest.mark.anyio
async def test_context_builder_shapes_and_nulls():
    def value_for(q):
        if "upstream_request" in q and 'job="api-service"' in q:
            return "0.002"
        if "http_request_duration" in q and 'job="api-service"' in q:
            return "5.0"
        if "container_" in q:
            return None          # cAdvisor without name labels (macOS containerd store)
        if "redis_up" in q:
            return "1"
        return "NaN"

    transport, seen = fake_prometheus(value_for)
    b = ContextBuilder("http://prom", minutes=10)
    b.transport = transport
    ctx = await b.build()

    assert set(ctx) == {"frontend", "api-service", "redis"}
    api = ctx["api-service"]
    assert api["p95"] == 5.0 and api["upstream_p95"] == 0.002
    assert api["cpu"] is None and api["mem"] is None   # no data
    assert ctx["frontend"]["p95"] is None                # NaN -> None
    assert len(api["trend"]["p95"]) == 11                # 10 min at 60 s, both ends
    assert "up" not in api["trend"]
    assert ctx["redis"]["up"] == 1.0
    assert api["container"] is None                      # no docker client
    assert all("fault_" not in q for q in seen)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_clean():
    assert clean("NaN") is None and clean("+Inf") is None and clean(None) is None
    assert clean("0.123456") == 0.1235


# -----------------------------
# Endpoints + WebSockets
# -----------------------------

def webhook(status, *alerts_):
    return {"version": "4", "status": status, "receiver": "gateway", "alerts": [
        {"status": status, "fingerprint": fp, "startsAt": "2026-10-06T10:00:00Z",
         "endsAt": "2026-10-06T10:02:00Z" if status == "resolved" else "0001-01-01T00:00:00Z",
         "labels": {"alertname": name, "service": svc, "severity": "warning", "category": "http",
                    "fault_latency_active": "1"},
         "annotations": {"summary": f"{name} on {svc}"}}
        for name, svc, fp in alerts_]}


@pytest.fixture
def client(monkeypatch):
    transport, _ = fake_prometheus(lambda q: "5.0" if "duration" in q else "1")
    gw.builder.transport = transport
    gw.grouper.incidents.clear()
    gw.events_hub.recent.clear()
    gw.responses_hub.recent.clear()
    monkeypatch.setattr(gw, "docker_or_none", lambda: None)
    with TestClient(gw.app) as c:
        yield c


def next_of_type(ws, type_):
    while True:
        msg = ws.receive_json()
        if msg.get("type") == type_:
            return msg


def test_alerts_become_one_open_incident_then_resolved(client):
    with client.websocket_connect("/ws/events") as ws:
        r = client.post("/alerts", json=webhook("firing", ("HighLatency", "api-service", "a")))
        assert r.json() == {"accepted": 1}
        raw = next_of_type(ws, "alert")
        assert raw["service"] == "api-service" and not any(k.startswith("fault_") for k in raw["labels"])

        client.post("/alerts", json=webhook("firing", ("HighLatency", "frontend", "b")))
        inc = next_of_type(ws, "incident")
        assert inc["status"] == "open"
        assert inc["services"] == ["api-service", "frontend"]
        assert {a["name"] for a in inc["alerts"]} == {"HighLatency"}
        assert all(a["value"] == 5.0 and a["threshold"] == 1.0 for a in inc["alerts"])
        assert inc["topology"]["api-service"] == ["redis"]
        assert inc["history"] == {"attempt": 1, "previous_actions": []}
        assert "fault_" not in str(inc)

        client.post("/alerts", json=webhook("resolved", ("HighLatency", "api-service", "a"),
                                            ("HighLatency", "frontend", "b")))
        done = next_of_type(ws, "incident")
        assert done["status"] == "resolved" and done["incident_id"] == inc["incident_id"]
        assert done["resolved_at"] is not None

    assert client.get("/incidents").json()[0]["incident_id"] == inc["incident_id"]
    assert client.get(f'/incidents/{inc["incident_id"]}').json()["status"] == "resolved"


def test_late_alert_sends_updated(client):
    with client.websocket_connect("/ws/events") as ws:
        client.post("/alerts", json=webhook("firing", ("HighLatency", "api-service", "a")))
        first = next_of_type(ws, "incident")
        time.sleep(0.05)
        client.post("/alerts", json=webhook("firing", ("HighErrorRate", "frontend", "c")))
        upd = next_of_type(ws, "incident")
        assert upd["status"] == "updated" and upd["incident_id"] == first["incident_id"]
        assert len(upd["alerts"]) == 2


def test_anomaly_endpoint(client):
    assert client.post("/anomalies", json={"service": "nope"}).status_code == 400
    with client.websocket_connect("/ws/events") as ws:
        r = client.post("/anomalies", json={"service": "api-service", "score": 0.91,
                                            "top_features": ["mem", "fault_memory_active"]})
        inc = next_of_type(ws, "incident")
        assert inc["incident_id"] == r.json()["incident_id"]
        assert inc["sources"] == ["ml"]
        assert inc["ml_anomalies"][0]["top_features"] == ["mem"]
    summ = client.get("/incidents").json()[0]
    assert summ["ml_active"] == ["api-service"] and summ["anomalies"] == 1


def test_responses_post_and_ws(client):
    plan = {"incident_id": "inc-x", "root_cause_service": "api-service",
            "recommended_action": {"type": "reset_faults", "target": "api-service"}, "confidence": 0.9}
    with client.websocket_connect("/ws/responses") as ws:
        assert client.post("/responses", json=plan).json() == {"accepted": True}
        msg = ws.receive_json()
        assert msg["type"] == "response_plan" and msg["incident_id"] == "inc-x"
        ws.send_json({**plan, "incident_id": "inc-y"})
        assert ws.receive_json()["incident_id"] == "inc-y"
        ws.send_text("not json")
        assert ws.receive_json()["type"] == "error"
    assert client.post("/responses", json={"x": 1}).status_code == 400
    with client.websocket_connect("/ws/responses") as ws2:
        assert ws2.receive_json()["replay"] is True


def test_bad_webhooks(client):
    assert client.post("/alerts", content=b"nope").status_code == 400
    assert client.post("/alerts", json={"x": 1}).status_code == 400
    h = client.get("/health").json()
    assert h["status"] == "ok" and "open_incidents" in h


def test_verified_action_resolves_incident_and_next_fault_opens_new_one(client):
    with client.websocket_connect("/ws/events") as ws:
        client.post("/anomalies", json={"service": "api-service", "score": 0.9, "top_features": ["cpu"]})
        inc = next_of_type(ws, "incident")
        iid = inc["incident_id"]
        # Forged or early: the anomaly is fresh, so the incident stays open
        rec = {"incident_id": iid, "status": "verified", "attempt": 1,
               "action": {"type": "reset_faults", "target": "api-service"}}
        client.post("/actions", json=rec)
        assert client.get(f"/incidents/{iid}").json()["status"] != "resolved"

        gw.grouper.incidents[iid].anomalies[0]["_at"] -= 30  # anomaly now 30 s old (< 60 s window)
        client.post("/actions", json=rec)
        done = next_of_type(ws, "incident")
        assert done["status"] == "resolved" and done["incident_id"] == iid

        client.post("/alerts", json=webhook("firing", ("HighMemory", "api-service", "m")))
        nxt = next_of_type(ws, "incident")
        assert nxt["status"] == "open" and nxt["incident_id"] != iid
    assert client.post("/actions", json={**rec, "incident_id": ["x"]}).status_code == 400


def test_actions_feed_history_and_reanalyze(client):
    with client.websocket_connect("/ws/events") as ws:
        client.post("/alerts", json=webhook("firing", ("HighLatency", "api-service", "a")))
        inc = next_of_type(ws, "incident")
        iid = inc["incident_id"]

        with client.websocket_connect("/ws/responses") as rws:
            rec = {"incident_id": iid, "status": "executed", "attempt": 1,
                   "action": {"type": "reset_faults", "target": "api-service"}}
            assert client.post("/actions", json=rec).json() == {"accepted": True}
            msg = rws.receive_json()
            assert msg["type"] == "action" and msg["status"] == "executed"
        # Only tried actions count as history
        client.post("/actions", json={**rec, "status": "pending_approval"})
        assert client.post("/actions", json={"status": "x"}).status_code == 400

        r = client.post(f"/incidents/{iid}/reanalyze", json={"attempt": 2})
        assert r.json() == {"attempt": 2}
        again = next_of_type(ws, "incident")
        assert again["status"] == "reanalyze"
        assert again["history"]["attempt"] == 2
        assert [(a["type"], a["target"]) for a in again["history"]["previous_actions"]] == \
            [("reset_faults", "api-service")]

    assert client.post("/incidents/nope/reanalyze", json={"attempt": 2}).status_code == 404
    assert client.post(f"/incidents/{iid}/reanalyze", json={}).status_code == 400
    client.post("/alerts", json=webhook("resolved", ("HighLatency", "api-service", "a")))
    assert client.post(f"/incidents/{iid}/reanalyze", json={"attempt": 3}).status_code == 409


def test_store_keeps_incident_timeline(client):
    with client.websocket_connect("/ws/events") as ws:
        client.post("/alerts", json=webhook("firing", ("HighLatency", "api-service", "s1")))
        iid = next_of_type(ws, "incident")["incident_id"]
    client.post("/responses", json={"incident_id": iid, "confidence": 0.9,
                                    "recommended_action": {"type": "reset_faults", "target": "api-service"}})
    client.post("/actions", json={"incident_id": iid, "status": "executed",
                                  "action": {"type": "reset_faults", "target": "api-service"}})
    timeline = client.get(f"/history/{iid}").json()
    assert [(m["channel"], m["type"]) for m in timeline] == [
        ("ws/events", "incident"), ("ws/responses", "response_plan"), ("ws/responses", "action")]
    assert any(h["incident_id"] == iid and h["status"] == "open" for h in client.get("/history").json())
    assert client.get("/history/nope").status_code == 404


def test_store_survives_reopen(tmp_path):
    from store import Store
    path = str(tmp_path / "inc.db")
    Store(path).add("ws/events", {"type": "incident", "incident_id": "inc-9", "status": "open"}, "t1")
    assert Store(path).timeline("inc-9")[0]["status"] == "open"


def test_dashboard_is_served(client):
    r = client.get("/dashboard/")
    assert r.status_code == 200 and "Incident Dashboard" in r.text


def test_nan_and_infinity_are_rejected_everywhere(client):
    nan_plan = b'{"incident_id": "inc-n", "confidence": NaN, "recommended_action": {"type": "reset_faults", "target": "api-service"}}'
    hdr = {"Content-Type": "application/json"}
    assert client.post("/responses", content=nan_plan, headers=hdr).status_code == 400
    assert client.post("/actions", content=b'{"incident_id": "i", "status": "executed", "x": Infinity}',
                       headers=hdr).status_code == 400
    assert client.post("/anomalies", content=b'{"service": "api-service", "score": -Infinity}',
                       headers=hdr).status_code == 400
    assert client.post("/alerts", content=b'{"alerts": [], "v": NaN}', headers=hdr).status_code == 400
    with client.websocket_connect("/ws/responses") as ws:
        ws.send_text(nan_plan.decode())
        assert ws.receive_json()["type"] == "error"
    # Nothing poisoned the replay buffers: JSON responses still work
    assert client.get("/responses").status_code == 200
    assert client.get("/events").status_code == 200
