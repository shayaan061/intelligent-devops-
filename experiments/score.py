"""Evaluation scorer (SUGGESTED_PLAN.md §10, objectives O2–O6).

Joins the injector's ground truth (experiments/ground_truth.csv) with the
gateway's incident store (experiments/incidents.db) and reports, per run
and in total:

  detection   detected?, MTTD (first alert/anomaly - fault start),
              false-positive incidents (no injected fault behind them)   O2
  root cause  first plan's root_cause_service == expected                O3
  action      first plan's action, and the first executed action, are
              acceptable for the scenario (§10 table); unsafe actions
              executed (outside responder/policies.yaml: target 0);
              collateral actions (executed on a non-root-cause service)  O4
  resolution  auto-resolved (injector end_reason "remediated"), MTTR
              (fault start -> fault gone), verified, escalated, attempts O5, O6
  cost        plan source (llm / runbook), fallback reasons, latency

Matching: a run is matched to the first incident opened between the fault
start and MATCH_GRACE seconds after the fault ended; each incident matches
at most one run. Incidents opened inside the evaluated time span that match
no run are false positives. Leave a gap between runs (the suite's --gap) so
an incident from one run is resolved before the next starts; otherwise the
gateway groups the next run's alerts into the still-open incident.

ground_truth.csv must only contain runs of the system being scored, so keep
one CSV per system (B0 / B1 / B2 / S) or filter with --since/--until.

Usage:
  python experiments/score.py                              # defaults below
  python experiments/score.py --system B1 --since 2026-10-06T17:00:00Z --out b1_runs.csv
  python experiments/score.py --json                       # summary as JSON
"""

import argparse
import csv
import json
import os
import sqlite3
import statistics
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
MATCH_GRACE = 60

# Acceptable actions per scenario, from the §10 table ("Expected action").
# Scenario 3's reset-vs-restart decision is still open (PROGRESS.md A):
# only restart_container is accepted until it is made.
ACCEPTABLE = {
    "1": {"reset_faults", "restart_container"},
    "2": {"reset_faults", "restart_container"},
    "3": {"restart_container"},
    "4": {"reset_faults"},
    "5": {"reset_faults"},
    "6": {"restart_container"},
    "7": {"restart_container"},
    "8": {"restart_container"},
    "9": {"reset_faults"},
}


def ts(s):
    """ISO-8601 (with Z) -> epoch seconds, or None."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# -----------------------------
# Loading
# -----------------------------

def load_runs(path, since=None, until=None, scenarios=None):
    with open(path, newline="") as f:
        runs = list(csv.DictReader(f))
    out = []
    for r in runs:
        start = ts(r["start"])
        if start is None:
            continue
        if since and start < since or until and start > until:
            continue
        if scenarios and r["scenario"] not in scenarios:
            continue
        out.append({**r, "_start": start, "_end": ts(r["end"]) or ts(r["planned_end"])})
    return sorted(out, key=lambda r: r["_start"])


def load_incidents(db_path):
    """incident_id -> {opened, detected, resolved, plans, actions}."""
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = db.execute("SELECT type, incident_id, body FROM messages "
                      "WHERE incident_id IS NOT NULL ORDER BY id").fetchall()
    db.close()
    incidents = {}
    for type_, iid, body in rows:
        msg = json.loads(body)
        inc = incidents.setdefault(iid, {"incident_id": iid, "opened": None, "detected": None,
                                         "resolved": None, "plans": [], "actions": []})
        if type_ == "incident":
            inc["opened"] = inc["opened"] or ts(msg.get("opened_at"))
            times = [ts(a.get("startsAt")) for a in msg.get("alerts") or []]
            times += [ts(m.get("detected_at")) for m in msg.get("ml_anomalies") or []]
            times = [t for t in times if t]
            if times:
                first = min(times)
                inc["detected"] = first if inc["detected"] is None else min(inc["detected"], first)
            if msg.get("status") == "resolved":
                inc["resolved"] = ts(msg.get("resolved_at"))
        elif type_ == "response_plan":
            inc["plans"].append(msg)
        elif type_ == "action":
            inc["actions"].append(msg)
    # Plans/actions with no incident message (e.g. a hand-posted demo plan) aren't incidents
    return {k: v for k, v in incidents.items() if v["opened"] is not None}


def load_allowlist(path):
    import yaml
    with open(path) as f:
        actions = yaml.safe_load(f)["actions"]
    return {(t, target) for t, rule in actions.items() if t != "escalate" for target in rule["targets"]}


# -----------------------------
# Scoring
# -----------------------------

def match(runs, incidents):
    """run_id -> incident (or None). Each incident is used once."""
    free = sorted(incidents.values(), key=lambda i: i["opened"])
    used, out = set(), {}
    for r in runs:
        lo, hi = r["_start"], (r["_end"] or r["_start"]) + MATCH_GRACE
        hit = next((i for i in free if i["incident_id"] not in used and lo <= i["opened"] <= hi), None)
        if hit:
            used.add(hit["incident_id"])
        out[r["run_id"]] = hit
    return out, used


def action_ok(action, run):
    return bool(action) and action.get("type") in ACCEPTABLE.get(run["scenario"], {run["expected_action"]}) \
        and action.get("target") == run["expected_root_cause"]


def score_run(run, inc, allowlist):
    row = {"run_id": run["run_id"], "scenario": run["scenario"], "name": run["name"],
           "end_reason": run["end_reason"], "incident_id": inc["incident_id"] if inc else None,
           "detected": inc is not None}
    remediated = run["end_reason"] == "remediated"
    row["auto_resolved"] = remediated
    row["mttr_s"] = round(run["_end"] - run["_start"], 1) if remediated and run["_end"] else None
    if inc is None:
        return {**row, "mttd_s": None, "root_cause": None, "root_cause_ok": False, "plan_action": None,
                "plan_action_ok": False, "executed_action": None, "executed_action_ok": False,
                "unsafe_executed": 0, "collateral_executed": 0, "verified": False, "escalated": False,
                "attempts": 0, "plan_source": None, "fallback_reason": None, "plan_latency_ms": None}

    plans = sorted(inc["plans"], key=lambda p: p.get("attempt") or 1)
    first = plans[0] if plans else {}
    rec = first.get("recommended_action") or {}
    executed = [a for a in inc["actions"] if a.get("status") == "executed"]
    exec_actions = [a.get("action") or {} for a in executed]
    statuses = {a.get("status") for a in inc["actions"]}
    return {
        **row,
        "mttd_s": round(inc["detected"] - run["_start"], 1) if inc["detected"] else None,
        "root_cause": first.get("root_cause_service"),
        "root_cause_ok": first.get("root_cause_service") == run["expected_root_cause"],
        "plan_action": f'{rec.get("type")}/{rec.get("target")}' if rec else None,
        "plan_action_ok": action_ok(rec, run),
        "executed_action": f'{exec_actions[0].get("type")}/{exec_actions[0].get("target")}' if exec_actions else None,
        "executed_action_ok": action_ok(exec_actions[0], run) if exec_actions else False,
        "unsafe_executed": sum((a.get("type"), a.get("target")) not in allowlist for a in exec_actions),
        "collateral_executed": sum(a.get("target") != run["expected_root_cause"] for a in exec_actions),
        "verified": "verified" in statuses,
        "escalated": "escalated" in statuses,
        "attempts": max((p.get("attempt") or 1 for p in plans), default=0),
        "plan_source": first.get("source"),
        "fallback_reason": first.get("fallback_reason"),
        "plan_latency_ms": first.get("latency_ms"),
    }


def pct(n, d):
    return round(100 * n / d, 1) if d else None


def stats(values):
    values = [v for v in values if v is not None]
    if not values:
        return {"mean": None, "median": None, "n": 0}
    return {"mean": round(statistics.mean(values), 1), "median": round(statistics.median(values), 1), "n": len(values)}


def summarize(rows, false_positives):
    n = len(rows)
    det = [r for r in rows if r["detected"]]
    planned = [r for r in det if r["plan_action"]]
    executed = [r for r in det if r["executed_action"]]
    sources = [r["plan_source"] for r in det if r["plan_source"]]
    return {
        "runs": n,
        "detected": len(det),
        "recall_pct": pct(len(det), n),                                           # O2 >= 90
        "false_positive_incidents": false_positives,
        "precision_pct": pct(len(det), len(det) + false_positives),
        "mttd_s": stats([r["mttd_s"] for r in det]),
        "root_cause_accuracy_pct": pct(sum(r["root_cause_ok"] for r in det), len(det)),   # O3 >= 80
        "plan_action_accuracy_pct": pct(sum(r["plan_action_ok"] for r in planned), len(planned)),
        "executed_action_accuracy_pct": pct(sum(r["executed_action_ok"] for r in executed), len(executed)),  # O4 >= 85
        "unsafe_actions_executed": sum(r["unsafe_executed"] for r in rows),       # O4 = 0
        "collateral_actions_executed": sum(r["collateral_executed"] for r in rows),
        "auto_resolved_pct": pct(sum(r["auto_resolved"] for r in rows), n),       # O5 >= 60
        "mttr_s": stats([r["mttr_s"] for r in rows]),                             # O6 vs B0
        "verified_pct": pct(sum(r["verified"] for r in det), len(det)),
        "escalated_pct": pct(sum(r["escalated"] for r in det), len(det)),
        "avg_attempts": round(statistics.mean([r["attempts"] for r in planned]), 2) if planned else None,
        "llm_plans_pct": pct(sources.count("llm"), len(sources)),
        "plan_latency_ms": stats([r["plan_latency_ms"] for r in det]),
    }


def score(gt_path, db_path, policy_path, since=None, until=None, scenarios=None):
    runs = load_runs(gt_path, since, until, scenarios)
    incidents = load_incidents(db_path)
    matched, used = match(runs, incidents)
    allowlist = load_allowlist(policy_path)
    rows = [score_run(r, matched[r["run_id"]], allowlist) for r in runs]
    false_positives = 0
    if runs:
        lo, hi = runs[0]["_start"], max((r["_end"] or r["_start"]) for r in runs) + MATCH_GRACE
        false_positives = sum(1 for i in incidents.values()
                              if i["incident_id"] not in used and lo <= i["opened"] <= hi)
    return rows, summarize(rows, false_positives)


# -----------------------------
# CLI
# -----------------------------

COLUMNS = ["scenario", "name", "detected", "mttd_s", "root_cause", "root_cause_ok", "plan_action",
           "executed_action", "executed_action_ok", "end_reason", "mttr_s", "verified", "escalated",
           "attempts", "plan_source"]


def print_table(rows):
    table = [COLUMNS] + [["" if r[c] is None else str(r[c]) for c in COLUMNS] for r in rows]
    widths = [max(len(row[i]) for row in table) for i in range(len(COLUMNS))]
    for row in table:
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ground-truth", default=os.path.join(HERE, "ground_truth.csv"))
    ap.add_argument("--db", default=os.path.join(HERE, "incidents.db"))
    ap.add_argument("--policies", default=os.path.join(HERE, "..", "responder", "policies.yaml"))
    ap.add_argument("--since", help="only runs starting at/after this ISO time")
    ap.add_argument("--until", help="only runs starting at/before this ISO time")
    ap.add_argument("--scenarios", help="comma list, e.g. 4,5,6")
    ap.add_argument("--system", default="", help="label for the output (B0, B1, B2, S)")
    ap.add_argument("--out", help="write per-run rows to this CSV")
    ap.add_argument("--json", action="store_true", help="print the summary as JSON only")
    args = ap.parse_args(argv)

    for path in (args.ground_truth, args.db):
        if not os.path.exists(path):
            sys.exit(f"missing {path}")
    rows, summary = score(args.ground_truth, args.db, args.policies, ts(args.since), ts(args.until),
                          set(args.scenarios.split(",")) if args.scenarios else None)
    summary = {"system": args.system or None, **summary}

    if args.out:
        with open(args.out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["run_id"])
            w.writeheader()
            w.writerows(rows)
    if args.json:
        print(json.dumps(summary, indent=2))
        return
    print_table(rows)
    print()
    for k, v in summary.items():
        print(f"{k:32} {v}")


if __name__ == "__main__":
    main()
