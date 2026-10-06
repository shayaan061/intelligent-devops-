"""Web control panel for the fault injector: http://localhost:8088

A browser front end to injector.py. Scenario runs go through
injector.run_scenario, so they append to experiments/ground_truth.csv
exactly like the CLI. Manual faults and container stop/start are for
demos and are NOT logged as ground truth.

Only one scenario run (single or suite) at a time. Manual faults are
refused while a run is active so they can't corrupt its ground truth, and
"Reset all" cancels the run first (otherwise the reset would be recorded
as `remediated`).

Usage:
  python web.py                 # PORT (default 8088), PROMETHEUS_URL
"""

import csv
import os
import random
import threading
import time
from collections import deque
from datetime import datetime

import requests
from flask import Flask, jsonify, request, send_from_directory

import injector as inj

PORT = int(os.environ.get("PORT", "8088"))
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")

app = Flask(__name__, static_folder="static")

LOG = deque(maxlen=300)


def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.append(line)


# run_scenario / cleanup / reset_all log through the module global
inj.log = log

job_lock = threading.Lock()
job = None  # the active run: dict, see start_job()


def job_busy():
    with job_lock:
        return job is not None


# -----------------------------
# Background runs
# -----------------------------

def run_job(this, ids, duration, gap):
    cancel = this["cancel"]

    try:
        for i, sid in enumerate(ids):
            d = max(duration, inj.MIN_DURATION.get(sid, 0))
            this.update(index=i, scenario=sid, phase="running", started=time.time(), until=time.time() + d)

            row = inj.run_scenario(inj.SCENARIOS[sid], duration, cancel)
            if row:
                this["done"].append({"scenario": sid, "end_reason": row["end_reason"]})

            if i < len(ids) - 1:
                this.update(scenario=None, phase="settling", started=time.time(), until=time.time() + gap)
                log(f"waiting {gap}s for the system to settle")
                inj.pause(gap, cancel)

        log("run finished")

    except inj.Cancelled:
        log("run cancelled")

    except Exception as exc:
        log(f"run failed: {exc}")

    finally:
        global job
        with job_lock:
            if job is this:
                job = None


def start_job(ids, duration, gap):
    global job

    with job_lock:
        if job is not None:
            return None

        job = {
            "ids": ids, "duration": duration, "gap": gap, "index": 0, "scenario": None,
            "phase": "starting", "started": time.time(), "until": None, "done": [],
            "cancel": threading.Event(),
        }
        this = job

    this["thread"] = threading.Thread(target=run_job, args=(this, ids, duration, gap), daemon=True)
    this["thread"].start()
    return this


def cancel_job(wait=True):
    with job_lock:
        this = job

    if this is None:
        return False

    this["cancel"].set()
    if wait:
        this["thread"].join(timeout=45)  # cleanup waits up to 30s for the target
    return True


# -----------------------------
# Status
# -----------------------------

def container_status(name):
    try:
        c = inj.docker_client().containers.get(name)
        health = (c.attrs.get("State", {}).get("Health") or {}).get("Status")
        return {"state": c.status, "health": health}
    except Exception as exc:
        return {"state": "unknown", "health": None, "error": str(exc).splitlines()[0][:120]}


def services_status():
    out = {}

    for name in inj.CONTAINERS:
        s = container_status(name)
        s["faults"] = inj.http_faults(name) if name in inj.SERVICE_URLS else None
        s["reachable"] = s["faults"] is not None if name in inj.SERVICE_URLS else None
        out[name] = s

    return out


def prometheus_alerts():
    try:
        r = requests.get(f"{PROMETHEUS_URL}/api/v1/alerts", timeout=2)
        alerts = r.json()["data"]["alerts"]
    except Exception:
        return None

    return sorted(
        [{
            "name": a["labels"].get("alertname"),
            "service": a["labels"].get("service"),
            "severity": a["labels"].get("severity"),
            "state": a["state"],
            "since": a.get("activeAt"),
            "summary": a.get("annotations", {}).get("summary", ""),
        } for a in alerts],
        key=lambda a: (a["state"] != "firing", a["service"] or "", a["name"] or ""),
    )


def recent_ground_truth(n=12):
    try:
        with open(inj.GROUND_TRUTH, newline="") as f:
            return list(csv.DictReader(f))[-n:][::-1]
    except FileNotFoundError:
        return []


def job_view():
    with job_lock:
        this = job

    if this is None:
        return None

    return {k: v for k, v in this.items() if k not in ("cancel", "thread")} | {
        "total": len(this["ids"]),
        "cancelling": this["cancel"].is_set(),
        "now": time.time(),
    }


# -----------------------------
# API
# -----------------------------

def int_arg(data, key, default, lo, hi):
    try:
        return max(lo, min(int(data.get(key, default)), hi))
    except (TypeError, ValueError):
        return default


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/scenarios")
def scenarios():
    return jsonify([{
        "id": s.id, "name": s.name, "target": s.target, "expected_action": s.expected_action,
        "faults": [f for f, _ in s.faults], "params": [p for _, p in s.faults],
        "min_duration": inj.MIN_DURATION.get(s.id),
    } for s in inj.SCENARIOS.values()])


@app.get("/api/state")
def state():
    return jsonify({
        "services": services_status(),
        "alerts": prometheus_alerts(),
        "job": job_view(),
        "log": list(LOG)[-120:],
        "ground_truth": recent_ground_truth(),
    })


@app.post("/api/run")
def run():
    data = request.get_json(silent=True) or {}

    ids = data.get("scenarios") or []
    if not ids or any(i not in inj.SCENARIOS for i in ids):
        return {"error": "pick at least one valid scenario"}, 400

    repeat = int_arg(data, "repeat", 1, 1, 10)
    duration = int_arg(data, "duration", 180, 30, 600)
    gap = int_arg(data, "gap", 60, 0, 600)

    ids = list(ids) * repeat
    if data.get("shuffle"):
        seed = data.get("seed")
        random.Random(seed if seed not in ("", None) else None).shuffle(ids)

    if start_job(ids, duration, gap) is None:
        return {"error": "a run is already in progress"}, 409

    log(f"run started: scenarios {ids}, duration {duration}s, gap {gap}s")
    return {"status": "started", "scenarios": ids}


@app.post("/api/cancel")
def cancel():
    if not cancel_job(wait=False):
        return {"error": "nothing is running"}, 409
    log("cancelling run…")
    return {"status": "cancelling"}


@app.post("/api/reset")
def reset():
    def work():
        if cancel_job():
            log("run cancelled for reset")
        inj.reset_all()

    threading.Thread(target=work, daemon=True).start()
    return {"status": "resetting"}, 202


@app.post("/api/inject")
def inject():
    """Manual fault, straight to the service's /inject. Not ground truth."""
    if job_busy():
        return {"error": "a scenario run is active; cancel it first"}, 409

    data = request.get_json(silent=True) or {}
    service = data.pop("service", None)
    if service not in inj.SERVICE_URLS:
        return {"error": f"service must be one of {list(inj.SERVICE_URLS)}"}, 400

    try:
        r = requests.post(f"{inj.SERVICE_URLS[service]}/inject", json=data, timeout=5)
    except requests.RequestException as exc:
        return {"error": f"{service} unreachable: {exc}"}, 502

    log(f"manual: {service} /inject {data} -> {r.status_code} {r.text.strip()[:200]}")
    return r.text, r.status_code, {"Content-Type": r.headers.get("Content-Type", "application/json")}


@app.post("/api/container")
def container():
    """Manual container stop/start. Not ground truth."""
    data = request.get_json(silent=True) or {}
    name, action = data.get("name"), data.get("action")

    if name not in inj.CONTAINERS or action not in ("stop", "start", "restart"):
        return {"error": "bad container or action"}, 400
    # Starting a stopped target mid-run would be scored as `remediated`
    if job_busy():
        return {"error": "a scenario run is active; cancel it first"}, 409

    try:
        c = inj.docker_client().containers.get(name)
        if action == "stop":
            c.stop(timeout=5)
        elif action == "start":
            c.start()
        else:
            c.restart(timeout=5)
    except Exception as exc:
        log(f"manual: {action} {name} failed: {exc}")
        return {"error": str(exc)}, 500

    log(f"manual: {action} {name}")
    return {"status": "ok"}


if __name__ == "__main__":
    log(f"injector UI on http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, threaded=True)
