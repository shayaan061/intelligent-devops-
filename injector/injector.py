"""Fault injector with ground-truth logging (SUGGESTED_PLAN.md §6.7, §10).

Injects the evaluation scenarios into the demo services and records, for each
run, when the fault really started and ended and *why* it ended:

  expired     the fault ran its full duration (nothing fixed it)
  remediated  it ended early: something reset/restarted the target
  cleanup     the injector had to undo it itself (e.g. restart a stopped container)

The CSV is ground truth for scoring only; never feed it to the detector or LLM.

Usage:
  python injector.py list
  python injector.py run 4 --duration 180
  python injector.py suite --scenarios 1-9 --repeat 3 --shuffle --gap 60
  python injector.py random --count 10
  python injector.py reset
"""

import argparse
import csv
import os
import random
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

SERVICE_URLS = {
    "frontend": os.environ.get("FRONTEND_URL", "http://localhost:5001"),
    "api-service": os.environ.get("API_SERVICE_URL", "http://localhost:5002"),
}

# Compose container names (see docker-compose.yml)
CONTAINERS = ["frontend", "api-service", "redis"]

GROUND_TRUTH = os.environ.get(
    "GROUND_TRUTH_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "experiments", "ground_truth.csv"),
)

CSV_FIELDS = [
    "run_id", "scenario", "name", "fault", "target_service", "expected_root_cause",
    "expected_action", "start", "planned_end", "end", "end_reason", "params",
]


# -----------------------------
# Scenarios (SUGGESTED_PLAN.md §10)
# -----------------------------

@dataclass
class Scenario:
    id: int
    name: str
    target: str
    expected_action: str
    # (fault, extra /inject params); fault "stop" = docker stop the target
    faults: list = field(default_factory=list)


SCENARIOS = {s.id: s for s in [
    Scenario(1, "cpu-frontend", "frontend", "reset_faults", [("cpu", {})]),
    Scenario(2, "cpu-api", "api-service", "reset_faults", [("cpu", {})]),
    Scenario(3, "memory-api", "api-service", "restart_container", [("memory", {"size_mb": 420})]),
    Scenario(4, "latency-api", "api-service", "reset_faults", [("latency", {})]),
    Scenario(5, "error-api", "api-service", "reset_faults", [("error", {})]),
    Scenario(6, "redis-stopped", "redis", "restart_container", [("stop", {})]),
    Scenario(7, "frontend-stopped", "frontend", "restart_container", [("stop", {})]),
    # Rule only fires once 80% is crossed near the end of the ramp; ML should see it earlier
    Scenario(8, "gradual-memory-api", "api-service", "restart_container",
             [("memory", {"size_mb": 440, "ramp_seconds": 240})]),
    Scenario(9, "cpu-latency-api", "api-service", "reset_faults", [("cpu", {}), ("latency", {})]),
]}

# Scenario 8 needs time to ramp; everything else uses --duration
MIN_DURATION = {8: 300}


# -----------------------------
# Helpers
# -----------------------------

def now():
    return datetime.now(timezone.utc)


def iso(ts):
    return ts.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


_docker = None


def docker_client():
    global _docker

    if _docker is None:
        import docker  # only needed for container scenarios / reset
        _docker = docker.from_env()

    return _docker


def container_running(name):
    try:
        return docker_client().containers.get(name).status == "running"
    except Exception:
        return False


def http_faults(service):
    """Active fault flags from /health, or None if the service is unreachable."""
    try:
        return requests.get(f"{SERVICE_URLS[service]}/health", timeout=2).json()["faults"]
    except Exception:
        return None


def inject_http(service, fault, params, duration):
    body = {"fault": fault, "duration": duration, **params}
    r = requests.post(f"{SERVICE_URLS[service]}/inject", json=body, timeout=5)

    if r.status_code != 200:
        raise RuntimeError(f"{service} /inject {fault} -> {r.status_code} {r.text.strip()}")


def reset_http(service):
    try:
        requests.post(f"{SERVICE_URLS[service]}/reset", timeout=5)
    except requests.RequestException:
        pass


def fault_active(scenario):
    """Is any part of the scenario's fault still in effect?"""
    for fault, _ in scenario.faults:
        if fault == "stop":
            if not container_running(scenario.target):
                return True
        else:
            flags = http_faults(scenario.target)
            # Unreachable mid-restart: treat as still active until it comes back
            if flags is None or flags.get(fault):
                return True

    return False


def append_ground_truth(row):
    os.makedirs(os.path.dirname(os.path.abspath(GROUND_TRUTH)), exist_ok=True)
    new_file = not os.path.exists(GROUND_TRUTH)

    with open(GROUND_TRUTH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)


# -----------------------------
# Running a scenario
# -----------------------------

def run_scenario(scenario, duration):
    duration = max(duration, MIN_DURATION.get(scenario.id, 0))
    params = ";".join(f"{f}:{p}" if p else f for f, p in scenario.faults)

    if fault_active(scenario):
        log(f"scenario {scenario.id} skipped: {scenario.target} already faulty (run `reset` first)")
        return None

    log(f"scenario {scenario.id} {scenario.name}: injecting into {scenario.target} for {duration}s")

    start = now()

    try:
        for fault, extra in scenario.faults:
            if fault == "stop":
                docker_client().containers.get(scenario.target).stop(timeout=5)
            else:
                inject_http(scenario.target, fault, extra, duration)

    except Exception as exc:
        log(f"scenario {scenario.id} failed to inject: {exc}")
        cleanup(scenario)
        return None

    planned_end = start.timestamp() + duration

    try:
        # Poll until the fault is gone (expired or remediated) or its time is up
        while time.time() < planned_end:
            time.sleep(1)

            if not fault_active(scenario):
                break

        # HTTP faults clear themselves up to ~0.5s after planned_end
        while time.time() < planned_end + 3 and fault_active(scenario):
            time.sleep(0.5)

    except KeyboardInterrupt:
        log(f"interrupted: undoing scenario {scenario.id}")
        cleanup(scenario)
        raise

    end = now()

    if end.timestamp() < planned_end - 1:
        end_reason = "remediated"
    elif fault_active(scenario):
        cleanup(scenario)
        end_reason = "cleanup"
        end = now()
    else:
        end_reason = "expired"

    row = {
        "run_id": uuid.uuid4().hex[:8],
        "scenario": scenario.id,
        "name": scenario.name,
        "fault": "+".join(f for f, _ in scenario.faults),
        "target_service": scenario.target,
        "expected_root_cause": scenario.target,
        "expected_action": scenario.expected_action,
        "start": iso(start),
        "planned_end": iso(datetime.fromtimestamp(planned_end, timezone.utc)),
        "end": iso(end),
        "end_reason": end_reason,
        "params": params,
    }

    append_ground_truth(row)
    log(f"scenario {scenario.id} ended: {end_reason} after {(end - start).total_seconds():.0f}s")

    return row


def cleanup(scenario):
    """Undo a scenario's fault (HTTP faults expire on their own; containers don't)."""
    for fault, _ in scenario.faults:
        if fault == "stop":
            if not container_running(scenario.target):
                docker_client().containers.get(scenario.target).start()
        else:
            reset_http(scenario.target)

    # Wait for the target to come back so the next scenario starts clean
    for _ in range(30):
        if not fault_active(scenario):
            return
        time.sleep(1)

    log(f"warning: {scenario.target} still not healthy after cleanup")


def reset_all():
    for name in CONTAINERS:
        try:
            if not container_running(name):
                log(f"starting {name}")
                docker_client().containers.get(name).start()
        except Exception as exc:
            log(f"could not start {name}: {exc}")

    for service in SERVICE_URLS:
        reset_http(service)

    log("all faults reset")


# -----------------------------
# CLI
# -----------------------------

def parse_ids(spec):
    ids = []

    for part in spec.split(","):
        if "-" in part:
            lo, hi = part.split("-")
            ids.extend(range(int(lo), int(hi) + 1))
        else:
            ids.append(int(part))

    unknown = [i for i in ids if i not in SCENARIOS]
    if unknown:
        sys.exit(f"unknown scenario(s): {unknown}")

    return ids


def run_many(ids, duration, gap):
    for i, sid in enumerate(ids):
        run_scenario(SCENARIOS[sid], duration)

        if i < len(ids) - 1:
            log(f"waiting {gap}s for the system to settle")
            time.sleep(gap)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="show scenarios")

    p_run = sub.add_parser("run", help="run one scenario")
    p_run.add_argument("scenario", type=int, choices=sorted(SCENARIOS))
    p_run.add_argument("--duration", type=int, default=180)

    p_suite = sub.add_parser("suite", help="run scenarios in sequence")
    p_suite.add_argument("--scenarios", default="1-9", help="e.g. 1-9 or 2,4,6")
    p_suite.add_argument("--repeat", type=int, default=1)
    p_suite.add_argument("--shuffle", action="store_true")
    p_suite.add_argument("--duration", type=int, default=180)
    p_suite.add_argument("--gap", type=int, default=60, help="seconds between scenarios")
    p_suite.add_argument("--seed", type=int)

    p_rand = sub.add_parser("random", help="run random scenarios")
    p_rand.add_argument("--count", type=int, default=5)
    p_rand.add_argument("--duration", type=int, default=180)
    p_rand.add_argument("--gap", type=int, default=60)
    p_rand.add_argument("--seed", type=int)

    sub.add_parser("reset", help="clear all faults and start stopped containers")

    args = parser.parse_args()

    if args.cmd == "list":
        for s in SCENARIOS.values():
            faults = " + ".join(f for f, _ in s.faults)
            print(f"{s.id}  {s.name:<20} {faults:<14} target={s.target:<12} expect={s.expected_action}")

    elif args.cmd == "run":
        run_scenario(SCENARIOS[args.scenario], args.duration)

    elif args.cmd == "suite":
        ids = parse_ids(args.scenarios) * args.repeat
        if args.shuffle:
            random.Random(args.seed).shuffle(ids)
        run_many(ids, args.duration, args.gap)

    elif args.cmd == "random":
        rng = random.Random(args.seed)
        run_many([rng.choice(list(SCENARIOS)) for _ in range(args.count)], args.duration, args.gap)

    elif args.cmd == "reset":
        reset_all()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("interrupted")
        sys.exit(130)
