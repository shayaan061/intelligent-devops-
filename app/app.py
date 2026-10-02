from flask import Flask, Response, request
from prometheus_client import Counter, Histogram, Gauge, generate_latest
from functools import wraps
import os
import threading
import time

import requests

app = Flask(__name__)

API_SERVICE_URL = os.environ.get("API_SERVICE_URL", "http://api-service:5000")
UPSTREAM_TIMEOUT = float(os.environ.get("UPSTREAM_TIMEOUT", "10"))

# -----------------------------
# Prometheus metrics
# -----------------------------

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"]
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["endpoint"]
)

UPSTREAM_LATENCY = Histogram(
    "upstream_request_duration_seconds",
    "Time spent calling the next service",
    ["upstream"]
)

# NOTE: fault_*_active gauges are GROUND TRUTH for evaluation/scoring only.
# They must never be fed to the ML detector or the LLM analysis engine.

CPU_FAULT_ACTIVE = Gauge(
    "fault_cpu_active",
    "Whether CPU fault injection is active"
)

MEMORY_FAULT_ACTIVE = Gauge(
    "fault_memory_active",
    "Whether memory fault injection is active"
)

LATENCY_FAULT_ACTIVE = Gauge(
    "fault_latency_active",
    "Whether latency fault injection is active"
)

ERROR_FAULT_ACTIVE = Gauge(
    "fault_error_active",
    "Whether HTTP error fault injection is active"
)

FAULT_GAUGES = {
    "cpu": CPU_FAULT_ACTIVE,
    "memory": MEMORY_FAULT_ACTIVE,
    "latency": LATENCY_FAULT_ACTIVE,
    "error": ERROR_FAULT_ACTIVE
}

# -----------------------------
# Fault state
# -----------------------------

fault_state = {
    "cpu": False,
    "memory": False,
    "latency": False,
    "error": False
}

# Incremented on every start/stop so an old timer cannot clear a newer fault
fault_generation = {name: 0 for name in fault_state}

state_lock = threading.Lock()

memory_data = None


def activate_fault(name):
    with state_lock:
        fault_generation[name] += 1
        fault_state[name] = True
        FAULT_GAUGES[name].set(1)
        return fault_generation[name]


def deactivate_fault(name, generation=None):
    with state_lock:
        # Only the current owner (or an explicit reset) may clear the fault
        if generation is not None and generation != fault_generation[name]:
            return False

        fault_generation[name] += 1
        fault_state[name] = False
        FAULT_GAUGES[name].set(0)
        return True


def is_current(name, generation):
    return fault_state[name] and fault_generation[name] == generation


# -----------------------------
# Timed faults (latency / error)
# -----------------------------

def timed_fault_worker(name, generation, duration):
    end_time = time.time() + duration

    while time.time() < end_time and is_current(name, generation):
        time.sleep(0.5)

    deactivate_fault(name, generation)


def start_timed_fault(name, duration):
    generation = activate_fault(name)

    thread = threading.Thread(
        target=timed_fault_worker,
        args=(name, generation, duration),
        daemon=True
    )

    thread.start()


# -----------------------------
# CPU fault
# -----------------------------

def cpu_worker(generation, duration):
    end_time = time.time() + duration

    # Stops early when /reset is called
    while time.time() < end_time and is_current("cpu", generation):
        # Deliberately consume CPU inside the container
        _ = 1234567 * 7654321

    deactivate_fault("cpu", generation)


def start_cpu_fault(duration):
    generation = activate_fault("cpu")

    thread = threading.Thread(
        target=cpu_worker,
        args=(generation, duration),
        daemon=True
    )

    thread.start()


# -----------------------------
# Memory fault
# -----------------------------

def memory_worker(generation, size_mb, duration, ramp_seconds):
    global memory_data

    try:
        end_time = time.time() + duration

        # Allocate in 10 MB chunks, spread over ramp_seconds (0 = all at once).
        # A gradual leak is the scenario rules catch late and ML should catch early.
        chunks = []
        memory_data = chunks
        steps = max(1, size_mb // 10)
        delay = ramp_seconds / steps

        for step in range(steps):
            if time.time() >= end_time or not is_current("memory", generation):
                break

            chunk_mb = 10 if step < steps - 1 else size_mb - 10 * (steps - 1)

            # Fill with non-zero bytes so the pages are actually committed
            # (a zeroed bytearray may not raise the container's RSS)
            chunks.append(bytearray(b"\x01") * (chunk_mb * 1024 * 1024))

            if delay:
                time.sleep(delay)

        while time.time() < end_time and is_current("memory", generation):
            time.sleep(0.5)

    finally:
        if deactivate_fault("memory", generation):
            memory_data = None


def start_memory_fault(size_mb, duration, ramp_seconds=0):
    generation = activate_fault("memory")

    thread = threading.Thread(
        target=memory_worker,
        args=(generation, size_mb, duration, ramp_seconds),
        daemon=True
    )

    thread.start()


# -----------------------------
# Reset fault
# -----------------------------

def reset_faults():
    global memory_data

    for name in fault_state:
        deactivate_fault(name)

    memory_data = None


# -----------------------------
# Request instrumentation
# -----------------------------

def instrumented(endpoint):
    """Record count and latency for every request, including errors."""

    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            status = "500"

            try:
                response = app.make_response(func(*args, **kwargs))
                status = str(response.status_code)
                return response

            finally:
                REQUEST_COUNT.labels(
                    request.method, endpoint, status
                ).inc()

                REQUEST_LATENCY.labels(endpoint).observe(
                    time.time() - start
                )

        return wrapper

    return decorator


# -----------------------------
# Application
# -----------------------------

@app.route("/")
@instrumented("/")
def home():

    if fault_state["latency"]:
        time.sleep(5)

    if fault_state["error"]:
        return {"error": "Injected test failure"}, 500

    start = time.time()

    try:
        upstream = requests.get(
            f"{API_SERVICE_URL}/data",
            timeout=UPSTREAM_TIMEOUT
        )
        upstream.raise_for_status()
        data = upstream.json()

    except requests.RequestException as exc:
        return {"error": "api-service unavailable", "detail": str(exc)}, 502

    finally:
        UPSTREAM_LATENCY.labels("api-service").observe(
            time.time() - start
        )

    return {
        "service": "frontend",
        "message": "Intelligent DevOps Test Application",
        "data": data
    }


@app.route("/health")
@instrumented("/health")
def health():

    return {
        "status": "healthy",
        "faults": fault_state
    }


@app.route("/inject", methods=["POST"])
def inject():

    data = request.get_json(silent=True) or {}

    fault = data.get("fault")

    try:
        duration = int(data.get("duration", 30))
    except (TypeError, ValueError):
        return {"error": "duration must be an integer"}, 400

    # Safety limit. Long enough for a fault to outlast detection,
    # analysis and remediation (the verify loop needs it still active)
    duration = max(1, min(duration, 600))

    if fault not in fault_state:
        return {
            "error": "Unknown fault type"
        }, 400

    if fault_state[fault]:
        return {
            "status": "already_running"
        }, 409

    if fault == "cpu":

        start_cpu_fault(duration)

        return {
            "status": "started",
            "fault": "cpu",
            "duration": duration
        }

    if fault == "memory":

        try:
            size_mb = int(data.get("size_mb", 100))
            ramp_seconds = int(data.get("ramp_seconds", 0))
        except (TypeError, ValueError):
            return {"error": "size_mb and ramp_seconds must be integers"}, 400

        # Safety limit. 450 MB + baseline must be able to cross the
        # HighMemory threshold (80% of the 512m limit) without OOM-killing
        size_mb = max(10, min(size_mb, 450))
        ramp_seconds = max(0, min(ramp_seconds, duration))

        start_memory_fault(
            size_mb,
            duration,
            ramp_seconds
        )

        return {
            "status": "started",
            "fault": "memory",
            "size_mb": size_mb,
            "ramp_seconds": ramp_seconds,
            "duration": duration
        }

    # latency / error: auto-clear after `duration`
    start_timed_fault(fault, duration)

    return {
        "status": "started",
        "fault": fault,
        "duration": duration
    }


@app.route("/reset", methods=["POST"])
def reset():

    reset_faults()

    return {
        "status": "reset",
        "faults": fault_state
    }


@app.route("/metrics")
def metrics():

    return Response(
        generate_latest(),
        mimetype="text/plain"
    )


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        threaded=True
    )
