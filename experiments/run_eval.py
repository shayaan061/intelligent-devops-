"""Evaluation runner (SUGGESTED_PLAN.md §10): runs the scenarios for B1, B2 and S
in resumable blocks and scores them.

A round is one pass of all 9 scenarios for one system, in a shuffled order
fixed by (system, round). Stage N asks for STAGES[N] rounds per system
(stage 1: 3, stage 2: 10, stage 3: 20). `run` does the missing rounds,
interleaving the systems (round 1 of B1, B2, S, then round 2, ...), and can be
stopped at any time (Ctrl+C undoes the active fault; that run is redone on
the next `run`). Finished runs are never redone unless voided.

Systems (the stack is switched before each block and restored at the end):
  B1  rules + YAML runbooks (ANALYZER_MODE=runbook), ml-detector stopped
  B2  rules + LLM (ANALYZER_MODE=llm), ml-detector stopped
  S   rules + ML + LLM + runbook fallback (full system)
B0 (fixed by hand) is not automated.

Each run is `docker compose run --rm injector run <n>` with a ground-truth
file per system (experiments/eval/gt_<system>.csv); experiments/eval/runs.csv
records which (system, round, scenario) each run_id belongs to. Before every
run the stack must be healthy and quiet (no firing alerts, no open incident),
and at least --gap seconds (default 300 = the responder's cooldown) must have
passed since the previous run ended, whichever system it belonged to.

Usage:
  python experiments/run_eval.py status
  python experiments/run_eval.py run --stage 1                 # all missing rounds of stage 1
  python experiments/run_eval.py run --stage 1 --rounds 1      # one round per system (~3.5 h)
  python experiments/run_eval.py run --stage 1 --systems B2 --hours 2
  python experiments/run_eval.py void <run_id> --reason "Docker VM stalled"
  python experiments/run_eval.py score --stage 1               # needs pyyaml

`run` keeps the Mac awake with caffeinate -i (screen may turn off). Closing
the lid still sleeps the Mac unless `sudo pmset -a disablesleep 1` is set;
`run` warns if it isn't. Don't run builds or pip installs during a block.
`run` uses only the standard library; `score` needs pyyaml (score.py).
"""

import argparse
import csv
import json
import os
import random
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EVAL_DIR = os.path.join(HERE, "eval")
RUNS_CSV = os.path.join(EVAL_DIR, "runs.csv")
LOG_PATH = os.path.join(EVAL_DIR, "run_eval.log")
RESULTS_DIR = os.path.join(HERE, "results")

SYSTEMS = {
    "B1": {"analyzer_mode": "runbook", "ml": False},
    "B2": {"analyzer_mode": "llm", "ml": False},
    "S": {"analyzer_mode": "llm", "ml": True},
}
STAGES = {1: 3, 2: 10, 3: 20}
SCENARIO_IDS = list(range(1, 10))
DURATION = 180
GAP = 300
MAX_GAP = 900              # score.py --max-gap: blocks of one system are split by other systems' blocks
QUIET_TIMEOUT = 600        # wait at most this long for alerts/incidents to clear before a run
SETTLE_AFTER_SWITCH = 60

GATEWAY = os.environ.get("GATEWAY_URL", "http://localhost:8000")
RESPONDER = os.environ.get("RESPONDER_URL", "http://localhost:8001")
ALERTMANAGER = os.environ.get("ALERTMANAGER_URL", "http://localhost:9093")
PROMETHEUS = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
OLLAMA = os.environ.get("OLLAMA_HOST_URL", "http://localhost:11434")

STACK = ["frontend", "api-service", "redis", "redis-exporter", "cadvisor", "prometheus", "alertmanager",
         "gateway", "analyzer", "responder", "load"]
RUN_FIELDS = ["system", "round", "slot", "scenario", "run_id", "status", "started", "ended", "end_reason", "note"]


class Abort(Exception):
    """The stack isn't fit to run on; stop the block (finished runs are kept)."""


def now():
    return time.time()


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log(msg):
    line = f"{iso(now())} {msg}"
    print(line, flush=True)
    os.makedirs(EVAL_DIR, exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def gt_path(system):
    return os.path.join(EVAL_DIR, f"gt_{system}.csv")


def order(system, rnd):
    """Scenario order of a round: shuffled, but the same every time it's asked."""
    ids = list(SCENARIO_IDS)
    random.Random(f"{system}-{rnd}").shuffle(ids)
    return ids


# -----------------------------
# Manifest (experiments/eval/runs.csv)
# -----------------------------

def load_manifest(path=None):
    path = path or RUNS_CSV
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def append_manifest(row, path=None):
    path = path or RUNS_CSV
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RUN_FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in RUN_FIELDS})


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
    for rnd in range(1, STAGES[stage] + 1):
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
    return max(datetime.fromisoformat(e.replace("Z", "+00:00")).timestamp() for e in ends)


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


def switch_system(system):
    """Bring the stack into the configuration of `system`. Returns True if anything changed."""
    cfg = SYSTEMS[system]
    changed = False
    if container_env("analyzer").get("ANALYZER_MODE") != cfg["analyzer_mode"]:
        log(f"analyzer -> ANALYZER_MODE={cfg['analyzer_mode']}")
        out = sh(["docker", "compose", "up", "-d", "--no-deps", "analyzer"],
                 env={"ANALYZER_MODE": cfg["analyzer_mode"]}, timeout=180)
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
    want = set(STACK) | ({"ml-detector"} if SYSTEMS[system]["ml"] else set())
    up = running_containers()
    missing = sorted(want - up)
    if missing:
        problems.append(f"not running: {', '.join(missing)}")
    if not SYSTEMS[system]["ml"] and "ml-detector" in up:
        problems.append("ml-detector running in a no-ML system")
    if container_env("analyzer").get("ANALYZER_MODE") != SYSTEMS[system]["analyzer_mode"]:
        problems.append("analyzer in the wrong mode")
    if container_env("responder").get("RESPONDER_MODE", "auto") != "auto":
        problems.append("responder not in auto mode")
    checks = [("gateway", f"{GATEWAY}/health"), ("responder", f"{RESPONDER}/health")]
    if SYSTEMS[system]["analyzer_mode"] == "llm":
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


# -----------------------------
# Running
# -----------------------------

def injector(args, system, timeout=None):
    cmd = ["docker", "compose", "run", "--rm", "-T",
           "-e", f"GROUND_TRUTH_PATH=/experiments/eval/gt_{system}.csv", "injector", *args]
    return subprocess.run(cmd, cwd=ROOT, timeout=timeout)


def find_row(system, started):
    """The ground-truth row the injector wrote for a run that started at `started`."""
    path = gt_path(system)
    if not os.path.exists(path):
        return None
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    for r in reversed(rows):
        t = datetime.fromisoformat(r["start"].replace("Z", "+00:00")).timestamp()
        if t >= started - 5:
            return r
    return None


def run_one(system, rnd, slot, sid):
    started = now()
    log(f"{system} round {rnd} slot {slot}/9: scenario {sid}")
    try:
        proc = injector(["run", str(sid), "--duration", str(DURATION)], system, timeout=DURATION + 900)
    except subprocess.TimeoutExpired:
        cleanup_injector(system)
        raise Abort(f"scenario {sid} timed out; it will be redone")
    row = find_row(system, started)
    if proc.returncode != 0 or row is None:
        raise Abort(f"scenario {sid} did not finish (exit {proc.returncode}); it will be redone")
    append_manifest({"system": system, "round": rnd, "slot": slot, "scenario": sid, "run_id": row["run_id"],
                     "status": "done", "started": row["start"], "ended": iso(now()),
                     "end_reason": row["end_reason"]})
    log(f"{system} round {rnd} scenario {sid}: run {row['run_id']} {row['end_reason']}")


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
    """Sleep until `gap` s have passed since the last finished run (any system)."""
    prev = last_end(load_manifest())
    if prev and now() - prev < gap:
        wait = gap - (now() - prev)
        log(f"waiting {wait:.0f}s (gap since the previous run)")
        time.sleep(wait)


def cmd_run(args):
    systems = args.systems.split(",")
    for s in systems:
        if s not in SYSTEMS:
            sys.exit(f"unknown system {s} (choose from {', '.join(SYSTEMS)})")
    plan = todo(load_manifest(), args.stage, systems, args.rounds)
    if not plan:
        log(f"stage {args.stage}: nothing left to run for {', '.join(systems)}")
        return
    hours = len(plan) * (DURATION / 2 + args.gap) / 3600
    log(f"stage {args.stage}: {len(plan)} runs to do for {', '.join(systems)} (~{hours:.1f} h)")
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
            log(f"stage {args.stage}: done for {', '.join(systems)}")
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
# Status, void, score
# -----------------------------

def cmd_status(args):
    manifest = load_manifest()
    done = done_slots(manifest)
    voided = sum(r["status"] == "void" for r in manifest)
    print(f"{'stage':6} " + "  ".join(f"{s:>12}" for s in SYSTEMS))
    for stage, rounds in STAGES.items():
        cells = []
        for s in SYSTEMS:
            n = sum(1 for (sys_, rnd, _) in done if sys_ == s and rnd <= rounds)
            cells.append(f"{n:>5}/{rounds * len(SCENARIO_IDS):<6}")
        print(f"{stage:<6} " + "  ".join(cells))
    left = len(todo(manifest, args.stage, list(SYSTEMS)))
    print(f"\nstage {args.stage}: {left} runs left (~{left * (DURATION / 2 + GAP) / 3600:.1f} h); "
          f"{voided} voided run(s)")
    prev = last_end(manifest)
    if prev:
        print(f"last run ended {iso(prev)}")


def cmd_void(args):
    manifest = load_manifest()
    hits = [r for r in manifest if r["run_id"] == args.run_id and r["status"] == "done"]
    if not hits:
        sys.exit(f"no finished run {args.run_id} in {RUNS_CSV}")
    r = hits[-1]
    append_manifest({**r, "status": "void", "note": args.reason})
    # Rewrite so the voided run no longer counts as done
    rows = [x for x in load_manifest() if not (x["run_id"] == args.run_id and x["status"] == "done")]
    with open(RUNS_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RUN_FIELDS)
        w.writeheader()
        w.writerows(rows)
    log(f"voided {args.run_id} ({r['system']} round {r['round']} scenario {r['scenario']}): {args.reason}")


def scored_runs(manifest, system, stage):
    """run_ids of finished, non-voided runs of `system` in the first STAGES[stage] rounds."""
    return {r["run_id"] for r in manifest
            if r["system"] == system and r["status"] == "done" and int(r["round"]) <= STAGES[stage]}


def cmd_score(args):
    import score  # needs pyyaml
    manifest = load_manifest()
    os.makedirs(RESULTS_DIR, exist_ok=True)
    summaries = {}
    for system in args.systems.split(","):
        keep = scored_runs(manifest, system, args.stage)
        if not keep:
            continue
        with open(gt_path(system), newline="") as f:
            reader = csv.DictReader(f)
            rows = [r for r in reader if r["run_id"] in keep]
            fields = reader.fieldnames
        tmp = os.path.join(EVAL_DIR, f".gt_{system}_scored.csv")
        with open(tmp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        per_run, summary = score.score(tmp, args.db, args.policies, max_gap=MAX_GAP)
        os.remove(tmp)
        out = os.path.join(RESULTS_DIR, f"eval_stage{args.stage}_{system}_runs.csv")
        with open(out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(per_run[0]))
            w.writeheader()
            w.writerows(per_run)
        summaries[system] = summary
        print(f"{system}: {len(per_run)} runs -> {os.path.relpath(out, ROOT)}")
    if not summaries:
        sys.exit("nothing to score")
    path = os.path.join(RESULTS_DIR, f"eval_stage{args.stage}_summary.json")
    with open(path, "w") as f:
        json.dump(summaries, f, indent=2)
    print(f"summary -> {os.path.relpath(path, ROOT)}\n")
    keys = ["runs", "recall_pct", "false_positive_incidents", "mttd_s", "root_cause_accuracy_pct",
            "executed_action_accuracy_pct", "unsafe_actions_executed", "auto_resolved_pct", "mttr_s",
            "verified_pct", "escalated_pct", "avg_attempts", "llm_plans_pct", "plan_latency_ms",
            "prompt_tokens_per_incident", "completion_tokens_per_incident"]
    print(f"{'':32}" + "".join(f"{s:>16}" for s in summaries))
    for k in keys:
        vals = [summaries[s].get(k) for s in summaries]
        vals = [v["mean"] if isinstance(v, dict) else v for v in vals]
        label = k + (" (mean)" if isinstance(summaries[next(iter(summaries))].get(k), dict) else "")
        print(f"{label:32}" + "".join(f"{'' if v is None else v:>16}" for v in vals))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run", help="run the missing rounds of a stage")
    p.add_argument("--stage", type=int, choices=sorted(STAGES), required=True)
    p.add_argument("--systems", default="B1,B2,S")
    p.add_argument("--rounds", type=int, help="at most this many rounds per system in this block")
    p.add_argument("--hours", type=float, help="don't start a new run after this many hours")
    p.add_argument("--gap", type=int, default=GAP, help="s between runs (>= the 300 s cooldown)")
    p.add_argument("--no-restore", action="store_true", help="leave the stack in the last system's config")
    p.add_argument("--dry-run", action="store_true", help="only list the runs")
    p = sub.add_parser("status", help="runs done per stage and system")
    p.add_argument("--stage", type=int, choices=sorted(STAGES), default=1)
    p = sub.add_parser("void", help="mark a spoiled run so it is redone")
    p.add_argument("run_id")
    p.add_argument("--reason", required=True)
    p = sub.add_parser("score", help="score each system's runs of a stage")
    p.add_argument("--stage", type=int, choices=sorted(STAGES), required=True)
    p.add_argument("--systems", default="B1,B2,S")
    p.add_argument("--db", default=os.path.join(HERE, "incidents.db"))
    p.add_argument("--policies", default=os.path.join(ROOT, "responder", "policies.yaml"))
    args = ap.parse_args(argv)
    {"run": cmd_run, "status": cmd_status, "void": cmd_void, "score": cmd_score}[args.cmd](args)


if __name__ == "__main__":
    main()
