"""Fault injector with ground-truth logging (SUGGESTED_PLAN.md §6.7, §10).

Injects the evaluation scenarios into the demo services and records, for each
run, when the fault really started and ended and *why* it ended:

  expired     the fault ran its full duration (nothing fixed it)
  remediated  it ended early: something reset/restarted the target
  cleanup     the injector had to undo it itself (e.g. restart a stopped container)

Scenarios 1-9 are the core set (SUGGESTED_PLAN.md §10). 10-14 are the extra set:
faults whose obvious fix is wrong (corrupted cache, slow Redis), faults below
the alert thresholds (subtle latency/errors, for the ML detector) and a fault
that comes back after every fix (to reach escalation). The Redis faults are
made inside the redis container (docker exec), not through an HTTP /inject.
15-19 are the novel set (added 26 Oct 2026, after the v1 evaluation): faults
no runbook was written for, to compare the LLM with the runbooks outside known
patterns (subtle faults on the frontend, a CPU limit that resets and restarts
can't undo, two faults at once, Redis memory filled with junk keys).

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
import math
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
    # (fault, extra /inject params); fault "stop" = docker stop the target,
    # "redis_corrupt" / "redis_slow" = made inside the redis container
    faults: list = field(default_factory=list)
    # Re-inject whenever the fault is cleared, until the planned end
    recurring: bool = False
    # More than one acceptable root cause (two faults at once); default (target,)
    root_causes: tuple = ()

    def expected_root_cause(self):
        return "|".join(self.root_causes) if self.root_causes else self.target


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
    # --- extra set ---
    # A non-integer `hits` makes api-service's INCR fail (503) while Redis is up.
    # Resetting/restarting api-service doesn't help, and Redis saves to disk, so
    # restarting it reloads the bad value: only flush_cache (approval) fixes it
    Scenario(10, "corrupted-cache", "redis", "flush_cache", [("redis_corrupt", {})]),
    # Redis pauses writes for 1.5 s every 2 s: both services get slow (p95 > 1 s)
    # but the cause is Redis, which has no latency metric of its own. Restarting
    # Redis ends it
    Scenario(11, "slow-redis", "redis", "restart_container", [("redis_slow", {"pause_ms": 1500})]),
    # Below the alert thresholds (HighLatency > 1 s, HighErrorRate > 10%)
    Scenario(12, "subtle-latency-api", "api-service", "reset_faults", [("latency", {"delay_s": 0.6})]),
    Scenario(13, "subtle-error-api", "api-service", "reset_faults", [("error", {"rate": 0.05})]),
    # Comes back after every reset/restart: should end in escalation
    Scenario(14, "recurring-latency-api", "api-service", "escalate", [("latency", {})], recurring=True),
    # --- novel set: no runbook was written for these ---
    # Below the thresholds, on the frontend (12/13 are on api-service)
    Scenario(15, "subtle-latency-frontend", "frontend", "reset_faults", [("latency", {"delay_s": 0.6})]),
    Scenario(16, "subtle-error-frontend", "frontend", "reset_faults", [("error", {"rate": 0.05})]),
    # The container's CPU limit is cut (docker update). Reset and restart keep
    # the limit; only restoring it helps: update_resources, which needs approval
    Scenario(17, "cpu-throttled-api", "api-service", "update_resources", [("cpu_limit", {"cpus": 0.05})]),
    # Two independent faults; both must be fixed, in either order
    Scenario(18, "two-faults", "api-service", "reset_faults",
             [("cpu", {"_target": "frontend"}), ("error", {})], root_causes=("frontend", "api-service")),
    # Junk keys fill Redis toward its 256 MB limit. Restarting reloads them from
    # disk; only flush_cache (approval) removes them
    Scenario(19, "redis-memory-pressure", "redis", "flush_cache", [("redis_fill", {"mb": 150})]),
]}

CORE_IDS = list(range(1, 10))
EXTRA_IDS = list(range(10, 15))
# 17 is left out of the suite (26 Oct pilot): the incident context shows CPU
# relative to the limit, so a cut limit looks normal and no analyzer can see it
NOVEL_IDS = [15, 16, 18, 19]

# Scenario 8 needs time to ramp; the extra and novel sets need time for several
# attempts (or to show that no rule fires); everything else uses --duration
MIN_DURATION = {8: 300, 10: 300, 11: 300, 12: 300, 13: 300, 14: 480,
                15: 300, 16: 300, 17: 300, 18: 300, 19: 300}

# Compose limits (docker-compose.yml `cpus: "1.0"`), restored after scenario 17
DEFAULT_NANO_CPUS = 1_000_000_000
FILL_PREFIX = "fill:"
FILL_SENTINEL = FILL_PREFIX + "0"

REDIS = "redis"
SLOW_PATTERN = "CLIENT PAUSE"   # matches the slow-redis loop's command line


# -----------------------------
# Helpers
# -----------------------------

def now():
    return datetime.now(timezone.utc)


def iso(ts):
    return ts.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


class Cancelled(Exception):
    """A run was cancelled from the web UI (web.py)."""


def pause(seconds, cancel=None):
    """Sleep, or raise Cancelled as soon as the `cancel` event is set."""
    if cancel is None:
        time.sleep(seconds)
    elif cancel.wait(seconds):
        raise Cancelled


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


def fault_target(scenario, extra):
    """A fault's own target (two-fault scenarios), else the scenario's."""
    return extra.get("_target", scenario.target)


def inject_http(service, fault, params, duration):
    body = {"fault": fault, "duration": duration, **{k: v for k, v in params.items() if not k.startswith("_")}}
    r = requests.post(f"{SERVICE_URLS[service]}/inject", json=body, timeout=5)

    if r.status_code != 200:
        raise RuntimeError(f"{service} /inject {fault} -> {r.status_code} {r.text.strip()}")


def reset_http(service):
    try:
        requests.post(f"{SERVICE_URLS[service]}/reset", timeout=5)
    except requests.RequestException:
        pass


def redis_exec(*cmd):
    """(exit code, output) of a command in the redis container."""
    res = docker_client().containers.get(REDIS).exec_run(list(cmd))
    return res.exit_code, res.output.decode(errors="replace").strip()


def cache_corrupted():
    """True if `hits` holds a non-integer. Redis down counts as still corrupted
    (it reloads the saved value when it comes back)."""
    try:
        code, out = redis_exec("redis-cli", "GET", "hits")
    except Exception:
        return True
    if code != 0:
        return True
    return out != "" and not out.lstrip("-").isdigit()


def redis_slow_running():
    """True while the pause loop runs (or Redis is mid-restart)."""
    if not container_running(REDIS):
        return True
    try:
        code, _ = redis_exec("pgrep", "-f", SLOW_PATTERN)
    except Exception:
        return True
    return code == 0


def start_redis_slow(pause_ms, duration):
    # Pauses write commands for pause_ms every 2 s; ends by itself after
    # `duration` (like the HTTP faults) or when the container restarts
    loop = (f"end=$(( $(date +%s) + {int(duration)} )); while [ $(date +%s) -lt $end ]; do "
            f"redis-cli {SLOW_PATTERN} {int(pause_ms)} WRITE >/dev/null; sleep 2; done")
    docker_client().containers.get(REDIS).exec_run(["sh", "-c", loop], detach=True)


def stop_redis_slow():
    redis_exec("pkill", "-f", SLOW_PATTERN)
    redis_exec("redis-cli", "CLIENT", "UNPAUSE")


def nano_cpus(name):
    """The container's CPU limit in units of 1e-9 CPUs (0 = no limit)."""
    return docker_client().containers.get(name).attrs["HostConfig"].get("NanoCpus") or 0


def set_nano_cpus(name, value):
    # docker-py's Container.update() has no NanoCpus argument, so call the Engine
    # API directly (POST /containers/{id}/update), as `docker update --cpus` does
    api = docker_client().api
    res = api._post_json(api._url("/containers/{0}/update", name), data={"NanoCpus": int(value)})
    api._raise_for_status(res)


def cpu_limited(name):
    """True while the limit is below the compose default (scenario 17)."""
    try:
        return 0 < nano_cpus(name) < DEFAULT_NANO_CPUS
    except Exception:
        return True


def fill_redis(mb):
    """Writes about `mb` MB of 1 KB junk values under fill:* in chunks of 10,000
    keys (one EVAL per chunk keeps each Redis block short)."""
    total = int(mb) * 1024
    script = ("for i = tonumber(ARGV[1]), tonumber(ARGV[2]) do "
              f"redis.call('SET', '{FILL_PREFIX}' .. i, string.rep('x', 1024)) end return 1")
    for lo in range(0, total, 10_000):
        code, out = redis_exec("redis-cli", "EVAL", script, "0", str(lo), str(min(lo + 9_999, total - 1)))
        if code != 0 or out != "1":
            raise RuntimeError(f"fill {lo}: {code} {out}")


def redis_filled():
    """True while the junk keys are there. Redis down counts as filled (it
    reloads them from disk when it comes back)."""
    try:
        code, out = redis_exec("redis-cli", "EXISTS", FILL_SENTINEL)
    except Exception:
        return True
    return code != 0 or out != "0"


def clear_redis_fill():
    redis_exec("sh", "-c", f"redis-cli --scan --pattern '{FILL_PREFIX}*' | xargs -r -n 1000 redis-cli DEL >/dev/null")


def inject_faults(scenario, duration):
    for fault, extra in scenario.faults:
        if fault == "stop":
            docker_client().containers.get(scenario.target).stop(timeout=5)
        elif fault == "redis_corrupt":
            code, out = redis_exec("redis-cli", "SET", "hits", "corrupted")
            if code != 0 or out != "OK":
                raise RuntimeError(f"SET hits -> {code} {out}")
        elif fault == "redis_slow":
            start_redis_slow(extra.get("pause_ms", 1500), duration)
        elif fault == "cpu_limit":
            set_nano_cpus(scenario.target, float(extra.get("cpus", 0.05)) * 1e9)
        elif fault == "redis_fill":
            fill_redis(extra.get("mb", 150))
        else:
            inject_http(fault_target(scenario, extra), fault, extra, duration)


def fault_active(scenario):
    """Is any part of the scenario's fault still in effect?"""
    for fault, extra in scenario.faults:
        if fault == "stop":
            if not container_running(scenario.target):
                return True
        elif fault == "redis_corrupt":
            if cache_corrupted():
                return True
        elif fault == "redis_slow":
            if redis_slow_running():
                return True
        elif fault == "cpu_limit":
            if cpu_limited(scenario.target):
                return True
        elif fault == "redis_fill":
            if redis_filled():
                return True
        else:
            flags = http_faults(fault_target(scenario, extra))
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

def run_scenario(scenario, duration, cancel=None):
    duration = max(duration, MIN_DURATION.get(scenario.id, 0))
    params = ";".join(f"{f}:{p}" if p else f for f, p in scenario.faults)

    if fault_active(scenario):
        log(f"scenario {scenario.id} skipped: {scenario.target} already faulty (run `reset` first)")
        return None

    log(f"scenario {scenario.id} {scenario.name}: injecting into {scenario.target} for {duration}s")

    start = now()

    try:
        inject_faults(scenario, duration)

    except Exception as exc:
        log(f"scenario {scenario.id} failed to inject: {exc}")
        cleanup(scenario)
        return None

    planned_end = start.timestamp() + duration
    cleared = 0

    try:
        # Poll until the fault is gone (expired or remediated) or its time is up
        while time.time() < planned_end:
            pause(1, cancel)

            if not fault_active(scenario):
                # Recurring: something fixed it; bring it back for the rest of the
                # run (not in the last 5 s, where it may just be expiring)
                if not scenario.recurring or planned_end - time.time() < 5:
                    break
                cleared += 1
                while (any(http_faults(fault_target(scenario, e)) is None for _, e in scenario.faults)
                       and time.time() < planned_end):
                    pause(1, cancel)
                # Rounded up so the re-injected fault doesn't expire before planned_end
                remaining = math.ceil(planned_end - time.time())
                if remaining < 5:
                    break
                log(f"scenario {scenario.id}: cleared ({cleared}), re-injecting for {remaining}s")
                try:
                    inject_faults(scenario, remaining)
                except Exception as exc:
                    log(f"scenario {scenario.id}: re-inject failed ({exc}); ending the run")
                    break

        # HTTP faults clear themselves up to ~0.5s after planned_end
        while time.time() < planned_end + 3 and fault_active(scenario):
            pause(0.5, cancel)

    except (KeyboardInterrupt, Cancelled):
        # No ground-truth row: the run didn't finish
        log(f"interrupted: undoing scenario {scenario.id}")
        cleanup(scenario)
        raise

    end = now()
    if scenario.recurring:
        params += f";cleared={cleared}"

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
        "expected_root_cause": scenario.expected_root_cause(),
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
    for fault, extra in scenario.faults:
        if fault == "stop":
            if not container_running(scenario.target):
                docker_client().containers.get(scenario.target).start()
        elif fault == "redis_corrupt":
            if container_running(REDIS) and cache_corrupted():
                redis_exec("redis-cli", "SET", "hits", "0")
        elif fault == "redis_slow":
            if container_running(REDIS):
                stop_redis_slow()
        elif fault == "cpu_limit":
            set_nano_cpus(scenario.target, DEFAULT_NANO_CPUS)
        elif fault == "redis_fill":
            if container_running(REDIS):
                clear_redis_fill()
        else:
            reset_http(fault_target(scenario, extra))

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

    # Faults made inside the redis container
    try:
        if container_running(REDIS):
            stop_redis_slow()
            if cache_corrupted():
                redis_exec("redis-cli", "SET", "hits", "0")
            if redis_filled():
                clear_redis_fill()
    except Exception as exc:
        log(f"could not reset redis faults: {exc}")

    # CPU limits cut by scenario 17
    for name in SERVICE_URLS:
        try:
            if cpu_limited(name):
                set_nano_cpus(name, DEFAULT_NANO_CPUS)
                log(f"restored the CPU limit of {name}")
        except Exception as exc:
            log(f"could not restore the CPU limit of {name}: {exc}")

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
