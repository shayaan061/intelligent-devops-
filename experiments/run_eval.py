"""Evaluation runner (SUGGESTED_PLAN.md §10): runs the scenarios for B1, B2 and S
in resumable blocks and scores them; also runs the no-fault soak test.

Suites (--suite, default core):
  core   scenarios 1-9 on B1, B2, S; stages 1/2/3 = 3/10/20 rounds per system
  extra  scenarios 10-14 (corrupted cache, slow Redis, subtle latency, subtle
         errors, recurring fault) on B1, B2, S, plus 3, 4, 6, 8 on SF;
         stages 1/2/3 = 3/5/10 rounds per system
  novel  scenarios 15, 16, 18, 19, faults no runbook was written for (subtle
         frontend latency/errors, two faults at once, Redis memory filled),
         on B1, B2, S and SF; stages 1/2/3 = 3/5/10 rounds per system
Each suite has its own manifest and ground truth (core: experiments/eval/,
extra: experiments/eval/extra/, novel: experiments/eval/novel/), so the runs
of one suite never mix with another's.

A round is one pass of a system's scenarios, in a shuffled order fixed by
(suite, system, round). `run` does the missing rounds of a stage, interleaving
the systems (round 1 of B1, B2, S, then round 2, ...), and can be stopped at
any time (Ctrl+C undoes the active fault; that run is redone on the next
`run`). Finished runs are never redone unless voided. A run the Mac slept
through is voided automatically.

Systems (the stack is switched before each block and restored at the end):
  B1  rules + YAML runbooks (ANALYZER_MODE=runbook), ml-detector stopped
  B2  rules + LLM (ANALYZER_MODE=llm), ml-detector stopped
  S   rules + ML + LLM + runbook fallback (full system)
  SF  S with the LLM unreachable (OLLAMA_URL points at a closed port): every
      plan comes from the runbook fallback (extra suite only)
B0 (fixed by hand) is not automated.

Each run is `docker compose run --rm injector run <n>` with a ground-truth
file per system (<suite dir>/gt_<system>.csv); <suite dir>/runs.csv records
which (system, round, scenario) each run_id belongs to. Before every run the
stack must be healthy and quiet (no firing alerts, no open incident), and at
least --gap seconds (default 300 = the responder's cooldown) must have passed
since the previous run or soak ended, whichever suite or system it belonged to.

Soak (false-alarm rate): `soak` runs the stack with no faults for --hours and
records the window in experiments/eval/soak/windows.csv; with --events it does
a harmless event every --every minutes (restart frontend, load 5 -> 10 users
for 10 min, restart api-service, load 5 -> 2 users for 10 min), logged in
soak/events.csv. Every incident opened in a window is a false alarm;
`soak-score` counts them per awake hour and attributes them to events.

Usage:
  python experiments/run_eval.py status [--suite extra]
  python experiments/run_eval.py run --stage 1                 # all missing rounds of stage 1
  python experiments/run_eval.py run --stage 1 --rounds 1      # one round per system
  python experiments/run_eval.py run --stage 1 --systems B2 --hours 2
  python experiments/run_eval.py run --suite extra --stage 1 --rounds 1
  python experiments/run_eval.py void <run_id> --reason "Docker VM stalled" [--suite extra]
  python experiments/run_eval.py score --stage 1 [--suite extra]   # needs pyyaml
  python experiments/run_eval.py soak --hours 12 --events
  python experiments/run_eval.py soak-score

`run`/`soak` keep the Mac awake with caffeinate -i (screen may turn off).
Closing the lid still sleeps the Mac unless `sudo pmset -a disablesleep 1` is
set; they warn if it isn't. Don't run builds or pip installs during a block,
and don't use the injector UI during a run or soak. Everything except `score`
uses only the standard library; `score` needs pyyaml (score.py).
"""

import argparse
import csv
import json
import os
import random
import shutil
import signal
import sqlite3
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EVAL_DIR = os.path.join(HERE, "eval")
LOG_PATH = os.path.join(EVAL_DIR, "run_eval.log")
RESULTS_DIR = os.path.join(HERE, "results")

DEFAULT_OLLAMA_URL = "http://host.docker.internal:11434"   # docker-compose.yml default
DEAD_OLLAMA_URL = "http://host.docker.internal:9"          # nothing listens: connection refused
SYSTEMS = {
    "B1": {"analyzer_mode": "runbook", "ml": False},
    "B2": {"analyzer_mode": "llm", "ml": False},
    "S": {"analyzer_mode": "llm", "ml": True},
    "SF": {"analyzer_mode": "llm", "ml": True, "ollama_url": DEAD_OLLAMA_URL},
}
CORE_IDS = list(range(1, 10))
EXTRA_IDS = list(range(10, 15))
# Faults no runbook was written for (added 26 Oct 2026). 17 (CPU limit cut) is
# not in the suite: the context shows CPU relative to the limit, so the cause is
# invisible to every analyzer (pilot, 26 Oct)
NOVEL_IDS = [15, 16, 18, 19]
SUITES = {
    "core": {"dir": "", "stages": {1: 3, 2: 10, 3: 20},
             "cells": {"B1": CORE_IDS, "B2": CORE_IDS, "S": CORE_IDS}},
    "extra": {"dir": "extra", "stages": {1: 3, 2: 5, 3: 10},
              "cells": {"B1": EXTRA_IDS, "B2": EXTRA_IDS, "S": EXTRA_IDS, "SF": [3, 4, 6, 8]}},
    "novel": {"dir": "novel", "stages": {1: 3, 2: 5, 3: 10},
              "cells": {"B1": NOVEL_IDS, "B2": NOVEL_IDS, "S": NOVEL_IDS, "SF": NOVEL_IDS}},
}
SUITE = "core"
DURATION = 180             # the injector raises it per scenario (MIN_DURATION: 8, 10-19)
GAP = 300
MAX_GAP = 900              # score.py --max-gap: blocks of one system are split by other systems' blocks
QUIET_TIMEOUT = 600        # wait at most this long for alerts/incidents to clear before a run
SETTLE_AFTER_SWITCH = 60

SOAK_EVENTS = [("restart", "frontend"), ("load", 10), ("restart", "api-service"), ("load", 2)]
LOAD_DEFAULT = 5           # docker-compose.yml LOAD_USERS default
LOAD_EVENT_SECONDS = 600
EVENT_ATTRIBUTION = 300    # an incident within this long after an event is attributed to it

GATEWAY = os.environ.get("GATEWAY_URL", "http://localhost:8000")
RESPONDER = os.environ.get("RESPONDER_URL", "http://localhost:8001")
ALERTMANAGER = os.environ.get("ALERTMANAGER_URL", "http://localhost:9093")
PROMETHEUS = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
OLLAMA = os.environ.get("OLLAMA_HOST_URL", "http://localhost:11434")

STACK = ["frontend", "api-service", "redis", "redis-exporter", "cadvisor", "prometheus", "alertmanager",
         "gateway", "analyzer", "responder", "load"]
RUN_FIELDS = ["system", "round", "slot", "scenario", "run_id", "status", "started", "ended", "end_reason", "note"]
WINDOW_FIELDS = ["system", "start", "end", "awake_hours", "events", "note"]
EVENT_FIELDS = ["window_start", "at", "event", "detail", "until"]


class Abort(Exception):
    """The stack isn't fit to run on; stop the block (finished runs are kept)."""


def now():
    return time.time()


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def log(msg):
    line = f"{iso(now())} {msg}"
    print(line, flush=True)
    os.makedirs(EVAL_DIR, exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


# -----------------------------
# Suites
# -----------------------------

def use_suite(name):
    global SUITE
    if name not in SUITES:
        sys.exit(f"unknown suite {name} (choose from {', '.join(SUITES)})")
    SUITE = name


def suite_dir(name=None):
    sub = SUITES[name or SUITE]["dir"]
    return os.path.join(EVAL_DIR, sub) if sub else EVAL_DIR


def runs_csv(name=None):
    return os.path.join(suite_dir(name), "runs.csv")


def stages():
    return SUITES[SUITE]["stages"]


def cells():
    return SUITES[SUITE]["cells"]


def gt_path(system):
    return os.path.join(suite_dir(), f"gt_{system}.csv")


def gt_container_path(system):
    """The same file as seen by the injector container (./experiments/eval -> /experiments/eval)."""
    return "/experiments/eval/" + os.path.relpath(gt_path(system), EVAL_DIR).replace(os.sep, "/")


def order(system, rnd):
    """Scenario order of a round: shuffled, but the same every time it's asked.
    The core seed is unchanged from before the extra suite existed."""
    ids = list(cells()[system])
    random.Random(f"{system}-{rnd}" if SUITE == "core" else f"{SUITE}-{system}-{rnd}").shuffle(ids)
    return ids


# -----------------------------
# Manifest (<suite dir>/runs.csv)
# -----------------------------

def load_manifest(path=None):
    path = path or runs_csv()
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def append_csv(path, fields, row):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in fields})


def append_manifest(row, path=None):
    append_csv(path or runs_csv(), RUN_FIELDS, row)


def done_slots(manifest):
    """{(system, round, scenario)} with a finished, non-voided run."""
    return {(r["system"], int(r["round"]), int(r["scenario"]))
            for r in manifest if r["status"] == "done"}


def todo(manifest, stage, systems, rounds=None):
    """Missing runs in run order: [(system, round, slot, scenario)].
    Rounds are interleaved across systems; `rounds` limits how many rounds
    (per system) that still have missing runs are included."""
    done = done_slots(manifest)
    out, taken = [], {s: 0 for s in systems}
    for rnd in range(1, stages()[stage] + 1):
        for system in systems:
            missing = [(system, rnd, slot, sid) for slot, sid in enumerate(order(system, rnd), 1)
                       if (system, rnd, sid) not in done]
            if not missing or (rounds is not None and taken[system] >= rounds):
                continue
            taken[system] += 1
            out.extend(missing)
    return out


def last_end(manifest):
    ends = [r["ended"] for r in manifest if r.get("ended")]
    if not ends:
        return None
    return max(ts(e) for e in ends)


def soak_dir():
    return os.path.join(EVAL_DIR, "soak")


def last_end_any():
    """When the last run of any suite, or the last soak, ended."""
    ends = [last_end(load_manifest(runs_csv(name))) for name in SUITES]
    ends += [ts(w["end"]) for w in load_manifest(os.path.join(soak_dir(), "windows.csv")) if w.get("end")]
    ends = [e for e in ends if e]
    return max(ends) if ends else None


# -----------------------------
# Stack control and health
# -----------------------------

def sh(args, env=None, timeout=120):
    return subprocess.run(args, cwd=ROOT, env={**os.environ, **(env or {})}, capture_output=True,
                          text=True, timeout=timeout)


def get_json(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def running_containers():
    out = sh(["docker", "ps", "--format", "{{.Names}}"], timeout=30)
    if out.returncode != 0:
        raise Abort(f"docker ps failed: {out.stderr.strip()}")
    return set(out.stdout.split())


def container_env(name):
    out = sh(["docker", "inspect", name, "--format", "{{range .Config.Env}}{{println .}}{{end}}"], timeout=30)
    return dict(line.split("=", 1) for line in out.stdout.splitlines() if "=" in line)


def analyzer_target(system):
    cfg = SYSTEMS[system]
    return {"ANALYZER_MODE": cfg["analyzer_mode"], "OLLAMA_URL": cfg.get("ollama_url", DEFAULT_OLLAMA_URL)}


def switch_system(system):
    """Bring the stack into the configuration of `system`. Returns True if anything changed."""
    cfg = SYSTEMS[system]
    changed = False
    want = analyzer_target(system)
    have = container_env("analyzer")
    if any(have.get(k) != v for k, v in want.items()):
        log(f"analyzer -> {' '.join(f'{k}={v}' for k, v in want.items())}")
        out = sh(["docker", "compose", "up", "-d", "--no-deps", "analyzer"], env=want, timeout=180)
        if out.returncode != 0:
            raise Abort(f"could not restart analyzer: {out.stderr.strip()}")
        changed = True
    ml_running = "ml-detector" in running_containers()
    if cfg["ml"] and not ml_running:
        log("starting ml-detector")
        out = sh(["docker", "compose", "up", "-d", "--no-deps", "ml-detector"], timeout=180)
        if out.returncode != 0:
            raise Abort(f"could not start ml-detector: {out.stderr.strip()}")
        changed = True
    elif not cfg["ml"] and ml_running:
        log("stopping ml-detector")
        sh(["docker", "compose", "stop", "ml-detector"], timeout=120)
        changed = True
    return changed


def restore_default():
    """Back to the everyday stack: LLM analyzer + ML detector (= system S)."""
    try:
        switch_system("S")
    except Exception as e:
        log(f"could not restore the default stack: {e}")


def health_problems(system):
    """Reasons the stack can't run a scenario now (empty = fine)."""
    problems = []
    cfg = SYSTEMS[system]
    want = set(STACK) | ({"ml-detector"} if cfg["ml"] else set())
    up = running_containers()
    missing = sorted(want - up)
    if missing:
        problems.append(f"not running: {', '.join(missing)}")
    if not cfg["ml"] and "ml-detector" in up:
        problems.append("ml-detector running in a no-ML system")
    have = container_env("analyzer")
    if any(have.get(k) != v for k, v in analyzer_target(system).items()):
        problems.append("analyzer in the wrong mode")
    if container_env("responder").get("RESPONDER_MODE", "auto") != "auto":
        problems.append("responder not in auto mode")
    checks = [("gateway", f"{GATEWAY}/health"), ("responder", f"{RESPONDER}/health")]
    if cfg["analyzer_mode"] == "llm" and "ollama_url" not in cfg:
        checks.append(("ollama", f"{OLLAMA}/api/tags"))
    for name, url in checks:
        try:
            get_json(url)
        except Exception as e:
            problems.append(f"{name} unreachable ({e.__class__.__name__})")
    try:
        targets = get_json(f"{PROMETHEUS}/api/v1/targets")["data"]["activeTargets"]
        down = sorted(t["labels"].get("job", "?") for t in targets if t["health"] != "up")
        if down:
            problems.append(f"prometheus targets down: {', '.join(down)}")
    except Exception as e:
        problems.append(f"prometheus unreachable ({e.__class__.__name__})")
    return problems


def noise():
    """Firing alerts and open incidents left over from earlier (must be none before a run)."""
    out = []
    try:
        alerts = get_json(f"{ALERTMANAGER}/api/v2/alerts?active=true&silenced=false&inhibited=false")
        out += [f"alert {a['labels'].get('alertname')}/{a['labels'].get('service')}" for a in alerts]
    except Exception as e:
        out.append(f"alertmanager unreachable ({e.__class__.__name__})")
    try:
        out += [f"incident {i['incident_id']}" for i in get_json(f"{GATEWAY}/incidents")
                if not i.get("resolved_at")]
    except Exception as e:
        out.append(f"gateway unreachable ({e.__class__.__name__})")
    return out


def wait_until_ready(system, cancel_after=QUIET_TIMEOUT):
    deadline = now() + cancel_after
    reset_done = False
    while True:
        problems = health_problems(system) + noise()
        if not problems:
            return
        if now() > deadline:
            raise Abort("stack not ready: " + "; ".join(problems))
        if not reset_done and now() > deadline - cancel_after / 2:
            log("still not ready, running injector reset: " + "; ".join(problems))
            injector(["reset"], system)
            reset_done = True
        else:
            log("waiting: " + "; ".join(problems))
        time.sleep(30)


def set_load(users):
    out = sh(["docker", "compose", "up", "-d", "--no-deps", "load"], env={"LOAD_USERS": str(users)}, timeout=180)
    if out.returncode != 0:
        raise Abort(f"could not set load to {users} users: {out.stderr.strip()}")


# -----------------------------
# Running
# -----------------------------

def injector(args, system, timeout=None):
    cmd = ["docker", "compose", "run", "--rm", "-T",
           "-e", f"GROUND_TRUTH_PATH={gt_container_path(system)}", "injector", *args]
    return subprocess.run(cmd, cwd=ROOT, timeout=timeout)


def gt_rows(system):
    path = gt_path(system)
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def new_row(system, before):
    """The ground-truth row the injector appended during a run (None if none or
    several). Counted, not matched by time: Docker's clock can drift from the
    Mac's after a sleep."""
    rows = gt_rows(system)[before:]
    return rows[0] if len(rows) == 1 else None


def slept(wall0, mono0, slack=20):
    """True if the Mac slept since (wall0, mono0): the monotonic clock stops
    during sleep on macOS, the wall clock doesn't."""
    return (time.time() - wall0) - (time.monotonic() - mono0) > slack


def run_one(system, rnd, slot, sid):
    before = len(gt_rows(system))
    wall0, mono0 = time.time(), time.monotonic()
    log(f"{SUITE} {system} round {rnd} slot {slot}/{len(cells()[system])}: scenario {sid}")
    try:
        proc = injector(["run", str(sid), "--duration", str(DURATION)], system, timeout=DURATION + 900)
    except subprocess.TimeoutExpired:
        cleanup_injector(system)
        raise Abort(f"scenario {sid} timed out; it will be redone")
    row = new_row(system, before)
    if proc.returncode != 0 or row is None:
        raise Abort(f"scenario {sid} did not finish (exit {proc.returncode}); it will be redone")
    status, note = "done", ""
    if slept(wall0, mono0):
        status, note = "void", "Mac slept during the run"
        log(f"the Mac slept during run {row['run_id']}: voided, it will be redone")
    append_manifest({"system": system, "round": rnd, "slot": slot, "scenario": sid, "run_id": row["run_id"],
                     "status": status, "started": row["start"], "ended": iso(now()),
                     "end_reason": row["end_reason"], "note": note})
    log(f"{SUITE} {system} round {rnd} scenario {sid}: run {row['run_id']} {row['end_reason']}")


def cleanup_injector(system):
    """Remove a leftover injector container and undo any fault it left behind."""
    out = sh(["docker", "ps", "-aq", "--filter", "label=com.docker.compose.service=injector"], timeout=30)
    ids = out.stdout.split()
    if ids:
        sh(["docker", "rm", "-f", *ids], timeout=60)
    log("injector reset (undo any active fault)")
    injector(["reset"], system, timeout=180)


def on_sigterm(signum, frame):
    raise KeyboardInterrupt


def check_sleep():
    if sys.platform != "darwin":
        return
    out = subprocess.run(["pmset", "-g"], capture_output=True, text=True).stdout
    disabled = any(line.split()[:1] == ["SleepDisabled"] and line.split()[-1] == "1"
                   for line in out.splitlines())
    if disabled:
        log("sleep is disabled (lid can be closed); run `sudo pmset -a disablesleep 0` when done")
    else:
        log("WARNING: closing the lid will sleep the Mac and spoil the running scenario "
            "(keep it open, or `sudo pmset -a disablesleep 1`)")


def keep_awake():
    if sys.platform == "darwin" and shutil.which("caffeinate"):
        return subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
    return None


def wait_gap(gap):
    """Sleep until `gap` s have passed since the last finished run or soak (any suite)."""
    prev = last_end_any()
    if prev and now() - prev < gap:
        wait = gap - (now() - prev)
        log(f"waiting {wait:.0f}s (gap since the previous run)")
        time.sleep(wait)


def parse_systems(spec):
    systems = spec.split(",") if spec else list(cells())
    for s in systems:
        if s not in cells():
            sys.exit(f"system {s} is not in the {SUITE} suite (choose from {', '.join(cells())})")
    return systems


def cmd_run(args):
    use_suite(args.suite)
    systems = parse_systems(args.systems)
    plan = todo(load_manifest(), args.stage, systems, args.rounds)
    if not plan:
        log(f"{SUITE} stage {args.stage}: nothing left to run for {', '.join(systems)}")
        return
    hours = len(plan) * (DURATION / 2 + args.gap) / 3600
    log(f"{SUITE} stage {args.stage}: {len(plan)} runs to do for {', '.join(systems)} (~{hours:.1f} h)")
    if args.dry_run:
        for system, rnd, slot, sid in plan:
            print(f"  {system} round {rnd} slot {slot}: scenario {sid}")
        return

    signal.signal(signal.SIGTERM, on_sigterm)   # `kill <pid>` stops like Ctrl+C
    check_sleep()
    caffeinate = keep_awake()
    stop_at = now() + args.hours * 3600 if args.hours else None
    current = None
    try:
        for system, rnd, slot, sid in plan:
            if stop_at and now() > stop_at:
                log(f"--hours {args.hours} reached; stopping (resume with the same command)")
                break
            if system != current:
                # The previous run's incident (re-analysis, verify) must finish
                # under its own system before the stack changes
                wait_gap(args.gap)
                if switch_system(system):
                    log(f"waiting {SETTLE_AFTER_SWITCH}s for the switch to settle")
                    time.sleep(SETTLE_AFTER_SWITCH)
                current = system
            wait_gap(args.gap)
            wait_until_ready(system)
            run_one(system, rnd, slot, sid)
        else:
            log(f"{SUITE} stage {args.stage}: done for {', '.join(systems)}")
        if not args.no_restore:
            wait_gap(args.gap)   # the last run finishes before the stack is restored
    except Abort as e:
        log(f"STOPPED: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        signal.signal(signal.SIGINT, signal.SIG_IGN)  # don't let a second Ctrl+C skip the cleanup
        log("interrupted; undoing the active run (it will be redone on the next `run`)")
        if current:
            cleanup_injector(current)
        sys.exit(130)
    finally:
        if not args.no_restore:
            restore_default()
        if caffeinate:
            caffeinate.terminate()
        if sys.platform == "darwin":
            log("block over. If you disabled sleep: sudo pmset -a disablesleep 0")


# -----------------------------
# Soak: no faults, count false alarms
# -----------------------------

def do_event(event):
    """Start a harmless event; returns (detail, seconds until it is undone)."""
    kind, arg = event
    if kind == "restart":
        out = sh(["docker", "restart", arg], timeout=120)
        if out.returncode != 0:
            raise Abort(f"could not restart {arg}: {out.stderr.strip()}")
        return f"restart {arg}", 0
    set_load(arg)
    return f"load {LOAD_DEFAULT} -> {arg} users", LOAD_EVENT_SECONDS


def progress_path():
    return os.path.join(soak_dir(), "in_progress.json")


def save_progress(system, start, mono0, n_events):
    """Window so far, saved every 5 min: if the Mac loses power the night isn't lost
    (soak-score uses it as an unfinished window)."""
    os.makedirs(soak_dir(), exist_ok=True)
    with open(progress_path(), "w") as f:
        json.dump({"system": system, "start": iso(start), "end": iso(now()),
                   "awake_hours": round((time.monotonic() - mono0) / 3600, 3), "events": n_events,
                   "note": "unfinished (soak stopped without saving; window up to the last 5-min save)"}, f)


def soak_windows():
    """Finished windows, plus an unfinished one left by a soak that died."""
    windows = load_manifest(os.path.join(soak_dir(), "windows.csv"))
    if os.path.exists(progress_path()):
        with open(progress_path()) as f:
            windows.append({k: str(v) for k, v in json.load(f).items()})
    return windows


def cmd_soak(args):
    system = args.system
    if system not in SYSTEMS:
        sys.exit(f"unknown system {system}")
    signal.signal(signal.SIGTERM, on_sigterm)
    check_sleep()
    caffeinate = keep_awake()
    windows = os.path.join(soak_dir(), "windows.csv")
    events_csv = os.path.join(soak_dir(), "events.csv")
    start = None
    n_events, load_until, note = 0, None, ""
    try:
        wait_gap(args.gap)
        if switch_system(system):
            log(f"waiting {SETTLE_AFTER_SWITCH}s for the switch to settle")
            time.sleep(SETTLE_AFTER_SWITCH)
        wait_until_ready(system)
        start, wall0, mono0 = now(), time.time(), time.monotonic()
        log(f"soak {system}: no faults for {args.hours} h{' with events every %d min' % args.every if args.events else ''}")
        next_event = time.monotonic() + args.every * 60
        next_save = 0
        while time.monotonic() - mono0 < args.hours * 3600:
            time.sleep(10)
            if time.monotonic() >= next_save:
                save_progress(system, start, mono0, n_events)
                next_save = time.monotonic() + 300
            if load_until and time.monotonic() >= load_until:
                set_load(LOAD_DEFAULT)
                log(f"soak: load back to {LOAD_DEFAULT} users")
                load_until = None
            if args.events and time.monotonic() >= next_event and not load_until:
                event = SOAK_EVENTS[n_events % len(SOAK_EVENTS)]
                at = now()
                detail, lasts = do_event(event)
                n_events += 1
                load_until = time.monotonic() + lasts if lasts else None
                append_csv(events_csv, EVENT_FIELDS, {"window_start": iso(start), "at": iso(at), "event": event[0],
                                                       "detail": detail, "until": iso(at + lasts)})
                log(f"soak event {n_events}: {detail}")
                next_event = time.monotonic() + args.every * 60
        log(f"soak {system}: done")
    except Abort as e:
        note = f"stopped: {e}"
        log(f"STOPPED: {e}")
    except KeyboardInterrupt:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        note = "interrupted"
        log("soak interrupted; the window so far is kept")
    finally:
        if load_until:
            try:
                set_load(LOAD_DEFAULT)
            except Abort as e:
                log(str(e))
        if start is not None:
            awake = (time.monotonic() - mono0) / 3600
            if slept(wall0, mono0, slack=60):
                note = (note + "; " if note else "") + "Mac slept during the soak (awake_hours excludes it)"
            append_csv(windows, WINDOW_FIELDS, {"system": system, "start": iso(start), "end": iso(now()),
                                                "awake_hours": round(awake, 3), "events": n_events, "note": note})
            try:
                os.remove(progress_path())
            except FileNotFoundError:
                pass
        restore_default()
        if caffeinate:
            caffeinate.terminate()
    if note.startswith("stopped"):
        sys.exit(1)


def load_incident_summaries(db_path):
    """incident_id -> {opened, sources, services, first plan, executed actions}, from the incident store."""
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = db.execute("SELECT type, incident_id, body FROM messages WHERE incident_id IS NOT NULL ORDER BY id").fetchall()
    db.close()
    out = {}
    for type_, iid, body in rows:
        msg = json.loads(body)
        inc = out.setdefault(iid, {"incident_id": iid, "opened": None, "sources": set(), "services": set(),
                                   "plan": None, "executed": []})
        if type_ == "incident":
            if inc["opened"] is None and msg.get("opened_at"):
                inc["opened"] = ts(msg["opened_at"])
            inc["sources"].update(msg.get("sources") or [])
            inc["services"].update(msg.get("services") or [])
        elif type_ == "response_plan" and inc["plan"] is None:
            rec = msg.get("recommended_action") or {}
            inc["plan"] = f'{msg.get("source")}:{rec.get("type")}/{rec.get("target")}'
        elif type_ == "action" and msg.get("status") == "executed":
            act = msg.get("action") or {}
            inc["executed"].append(f'{act.get("type")}/{act.get("target")}')
    return {k: v for k, v in out.items() if v["opened"] is not None}


def soak_report(windows, events, incidents):
    """False alarms per soak window, attributed to the harmless events."""
    report = []
    for w in windows:
        lo, hi = ts(w["start"]), ts(w["end"])
        evs = [e for e in events if e["window_start"] == w["start"]]
        found = []
        for inc in sorted(incidents.values(), key=lambda i: i["opened"]):
            if not lo <= inc["opened"] <= hi:
                continue
            cause = next((e["detail"] for e in evs
                          if ts(e["at"]) <= inc["opened"] <= ts(e["until"]) + EVENT_ATTRIBUTION), None)
            found.append({"incident_id": inc["incident_id"], "opened": iso(inc["opened"]),
                          "sources": "+".join(sorted(inc["sources"])), "services": "+".join(sorted(inc["services"])),
                          "first_plan": inc["plan"], "executed": ";".join(inc["executed"]), "after_event": cause})
        hours = float(w["awake_hours"] or 0)
        report.append({
            "system": w["system"], "start": w["start"], "end": w["end"], "awake_hours": hours,
            "events": int(w["events"] or 0), "note": w.get("note", ""),
            "false_alarms": len(found),
            "per_hour": round(len(found) / hours, 3) if hours else None,
            "after_event": sum(1 for f in found if f["after_event"]),
            "without_event": sum(1 for f in found if not f["after_event"]),
            "by_source": {s: sum(1 for f in found if f["sources"] == s) for s in sorted({f["sources"] for f in found})},
            "actions_executed": sum(len(f["executed"].split(";")) for f in found if f["executed"]),
            "incidents": found,
        })
    return report


def cmd_soak_score(args):
    windows = soak_windows()
    if not windows:
        sys.exit("no soak windows yet (run `soak` first)")
    events = load_manifest(os.path.join(soak_dir(), "events.csv"))
    report = soak_report(windows, events, load_incident_summaries(args.db))
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, "soak_summary.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    for w in report:
        print(f"{w['system']} {w['start']} -> {w['end']}: {w['awake_hours']:.2f} awake h, {w['events']} events, "
              f"{w['false_alarms']} false alarms ({w['per_hour']}/h; {w['after_event']} after an event), "
              f"{w['actions_executed']} actions executed {w['by_source']} {w['note']}")
        for i in w["incidents"]:
            print(f"    {i['opened']} {i['incident_id']} {i['sources']:<8} {i['services']:<22} "
                  f"plan={i['first_plan']} executed={i['executed'] or '-'} after={i['after_event'] or '-'}")
    print(f"-> {os.path.relpath(path, ROOT)}")


# -----------------------------
# Status, void, score
# -----------------------------

def cmd_status(args):
    use_suite(args.suite)
    manifest = load_manifest()
    done = done_slots(manifest)
    voided = sum(r["status"] == "void" for r in manifest)
    print(f"suite {SUITE}\n{'stage':6} " + "  ".join(f"{s:>12}" for s in cells()))
    for stage, rounds in stages().items():
        row = []
        for s, ids in cells().items():
            n = sum(1 for (sys_, rnd, _) in done if sys_ == s and rnd <= rounds)
            row.append(f"{n:>5}/{rounds * len(ids):<6}")
        print(f"{stage:<6} " + "  ".join(row))
    left = len(todo(manifest, args.stage, list(cells())))
    print(f"\nstage {args.stage}: {left} runs left (~{left * (DURATION / 2 + GAP) / 3600:.1f} h); "
          f"{voided} voided run(s)")
    prev = last_end(manifest)
    if prev:
        print(f"last run ended {iso(prev)}")


def cmd_void(args):
    use_suite(args.suite)
    manifest = load_manifest()
    hits = [r for r in manifest if r["run_id"] == args.run_id and r["status"] == "done"]
    if not hits:
        sys.exit(f"no finished run {args.run_id} in {runs_csv()}")
    r = hits[-1]
    append_manifest({**r, "status": "void", "note": args.reason})
    # Rewrite so the voided run no longer counts as done
    rows = [x for x in load_manifest() if not (x["run_id"] == args.run_id and x["status"] == "done")]
    with open(runs_csv(), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RUN_FIELDS)
        w.writeheader()
        w.writerows(rows)
    log(f"voided {args.run_id} ({SUITE} {r['system']} round {r['round']} scenario {r['scenario']}): {args.reason}")


def scored_runs(manifest, system, stage):
    """run_ids of finished, non-voided runs of `system` in the first rounds of `stage`."""
    return {r["run_id"] for r in manifest
            if r["system"] == system and r["status"] == "done" and int(r["round"]) <= stages()[stage]}


def by_scenario(system, per_run):
    """One row per scenario: counts of the outcomes that matter for the extra set."""
    out = []
    for sid in sorted({r["scenario"] for r in per_run}, key=int):
        rr = [r for r in per_run if r["scenario"] == sid]
        det = [r for r in rr if r["detected"]]

        def mean(key):
            vals = [r[key] for r in rr if r[key] is not None]
            return round(statistics.mean(vals), 1) if vals else None
        out.append({
            "system": system, "scenario": sid, "name": rr[0]["name"], "runs": len(rr),
            "detected": len(det),
            "root_cause_ok": sum(r["root_cause_ok"] for r in det),
            "plan_action_ok": sum(r["plan_action_ok"] for r in det),
            "executed_action_ok": sum(r["executed_action_ok"] for r in det),
            "approval_requested": sum(r["approval_requested"] for r in det),
            "escalated": sum(r["escalated"] for r in det),
            "auto_resolved": sum(r["auto_resolved"] for r in rr),
            "llm_fallbacks": sum(1 for r in det if r["fallback_reason"] and r["fallback_reason"] != "mode=runbook"),
            "mttd_mean_s": mean("mttd_s"), "mttr_mean_s": mean("mttr_s"),
        })
    return out


def cmd_score(args):
    import score  # needs pyyaml
    use_suite(args.suite)
    prefix = f"eval_stage{args.stage}" if SUITE == "core" else f"eval_{SUITE}_stage{args.stage}"
    manifest = load_manifest()
    os.makedirs(RESULTS_DIR, exist_ok=True)
    summaries, scenario_rows = {}, []
    for system in parse_systems(args.systems):
        keep = scored_runs(manifest, system, args.stage)
        if not keep:
            continue
        with open(gt_path(system), newline="") as f:
            reader = csv.DictReader(f)
            rows = [r for r in reader if r["run_id"] in keep]
            fields = reader.fieldnames
        tmp = os.path.join(suite_dir(), f".gt_{system}_scored.csv")
        with open(tmp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        per_run, summary = score.score(tmp, args.db, args.policies, max_gap=MAX_GAP)
        os.remove(tmp)
        out = os.path.join(RESULTS_DIR, f"{prefix}_{system}_runs.csv")
        with open(out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(per_run[0]))
            w.writeheader()
            w.writerows(per_run)
        summaries[system] = summary
        scenario_rows += by_scenario(system, per_run)
        print(f"{system}: {len(per_run)} runs -> {os.path.relpath(out, ROOT)}")
    if not summaries:
        sys.exit("nothing to score")
    path = os.path.join(RESULTS_DIR, f"{prefix}_summary.json")
    with open(path, "w") as f:
        json.dump(summaries, f, indent=2)
    spath = os.path.join(RESULTS_DIR, f"{prefix}_by_scenario.csv")
    with open(spath, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(scenario_rows[0]))
        w.writeheader()
        w.writerows(scenario_rows)
    print(f"summary -> {os.path.relpath(path, ROOT)}, per scenario -> {os.path.relpath(spath, ROOT)}\n")
    keys = ["runs", "recall_pct", "false_positive_incidents", "mttd_s", "root_cause_accuracy_pct",
            "executed_action_accuracy_pct", "unsafe_actions_executed", "auto_resolved_pct", "mttr_s",
            "verified_pct", "escalated_pct", "approval_requested_pct", "avg_attempts", "llm_plans_pct",
            "plan_latency_ms", "prompt_tokens_per_incident", "completion_tokens_per_incident"]
    print(f"{'':32}" + "".join(f"{s:>16}" for s in summaries))
    for k in keys:
        vals = [summaries[s].get(k) for s in summaries]
        vals = [v["mean"] if isinstance(v, dict) else v for v in vals]
        label = k + (" (mean)" if isinstance(summaries[next(iter(summaries))].get(k), dict) else "")
        print(f"{label:32}" + "".join(f"{'' if v is None else v:>16}" for v in vals))
    if SUITE != "core":
        cols = ["runs", "detected", "root_cause_ok", "plan_action_ok", "executed_action_ok",
                "approval_requested", "escalated", "auto_resolved", "llm_fallbacks"]
        print(f"\n{'system':7}{'scenario':26}" + "".join(f"{c:>19}" for c in cols))
        for r in scenario_rows:
            print(f"{r['system']:7}{r['scenario'] + ' ' + r['name']:26}" + "".join(f"{r[c]:>19}" for c in cols))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    all_stages = sorted({s for suite in SUITES.values() for s in suite["stages"]})

    def suite_arg(p):
        p.add_argument("--suite", choices=sorted(SUITES), default="core")

    p = sub.add_parser("run", help="run the missing rounds of a stage")
    suite_arg(p)
    p.add_argument("--stage", type=int, choices=all_stages, required=True)
    p.add_argument("--systems", help="comma list (default: every system of the suite)")
    p.add_argument("--rounds", type=int, help="at most this many rounds per system in this block")
    p.add_argument("--hours", type=float, help="don't start a new run after this many hours")
    p.add_argument("--gap", type=int, default=GAP, help="s between runs (>= the 300 s cooldown)")
    p.add_argument("--no-restore", action="store_true", help="leave the stack in the last system's config")
    p.add_argument("--dry-run", action="store_true", help="only list the runs")
    p = sub.add_parser("status", help="runs done per stage and system")
    suite_arg(p)
    p.add_argument("--stage", type=int, choices=all_stages, default=1)
    p = sub.add_parser("void", help="mark a spoiled run so it is redone")
    suite_arg(p)
    p.add_argument("run_id")
    p.add_argument("--reason", required=True)
    p = sub.add_parser("score", help="score each system's runs of a stage")
    suite_arg(p)
    p.add_argument("--stage", type=int, choices=all_stages, required=True)
    p.add_argument("--systems", help="comma list (default: every system of the suite)")
    p.add_argument("--db", default=os.path.join(HERE, "incidents.db"))
    p.add_argument("--policies", default=os.path.join(ROOT, "responder", "policies.yaml"))
    p = sub.add_parser("soak", help="no faults for a while: every incident is a false alarm")
    p.add_argument("--hours", type=float, required=True)
    p.add_argument("--system", default="S")
    p.add_argument("--events", action="store_true", help="harmless restarts and load changes")
    p.add_argument("--every", type=int, default=30, help="minutes between events")
    p.add_argument("--gap", type=int, default=GAP)
    p = sub.add_parser("soak-score", help="false alarms per soak window")
    p.add_argument("--db", default=os.path.join(HERE, "incidents.db"))
    args = ap.parse_args(argv)
    {"run": cmd_run, "status": cmd_status, "void": cmd_void, "score": cmd_score,
     "soak": cmd_soak, "soak-score": cmd_soak_score}[args.cmd](args)


if __name__ == "__main__":
    main()
