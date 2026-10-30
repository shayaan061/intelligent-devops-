"""Counts the responder's live policy decisions per system, from the gateway's message store.

    python3 experiments/guard_decisions.py [--out experiments/results/guard_decisions_long_run.csv]

Source: experiments/results/incident_store_long_run_19-22oct.jsonl (core rounds 5-20 and extra rounds
2-10; earlier rounds are in other store files), joined to the stage-3 run scores by incident_id.
Every `action` message is one decision; it is put in exactly one category below.
"""
import argparse
import collections
import csv
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")
STORE = os.path.join(RESULTS, "incident_store_long_run_19-22oct.jsonl")
RUNS = [("B1", "eval_stage3_B1_runs.csv"), ("B2", "eval_stage3_B2_runs.csv"), ("S", "eval_stage3_S_runs.csv"),
        ("B1", "eval_extra_stage3_B1_runs.csv"), ("B2", "eval_extra_stage3_B2_runs.csv"),
        ("S", "eval_extra_stage3_S_runs.csv"), ("SF", "eval_extra_stage3_SF_runs.csv")]
CATEGORIES = [
    "recommended action executed",
    "fallback executed (recommended action in cooldown)",
    "escalated: recommended and fallback blocked by cooldown",
    "escalated: recommended action in cooldown, fallback is escalate",
    "escalated by the plan itself",
    "escalated after 3 attempts",
    "skipped by the pre-check (already cleared)",
    "blocked by allowlist, target or confidence, or sent for approval",
]


def category(body):
    status, reason = body.get("status"), body.get("reason", "")
    if status == "executed":
        return CATEGORIES[1] if "fallback action passed" in reason else CATEGORIES[0]
    if status == "skipped":
        return CATEGORIES[6]
    if status == "escalated":
        if "no action passed validation" in reason and reason.count("cooldown") >= 2:
            return CATEGORIES[2]
        if "cooldown" in reason and "fallback: escalate" in reason:
            return CATEGORIES[3]
        if reason.startswith("recommended: escalate"):
            return CATEGORIES[4]
        if "after 3 attempts" in reason:
            return CATEGORIES[5]
        return CATEGORIES[7]
    if status in ("blocked", "approval_requested", "pending_approval", "rejected"):
        return CATEGORIES[7]
    return None          # verified / unresolved are verification results, not decisions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    args = ap.parse_args()
    system_of, suite_of = {}, {}
    for system, name in RUNS:
        with open(os.path.join(RESULTS, name), newline="") as f:
            for r in csv.DictReader(f):
                if r["incident_id"]:
                    system_of[r["incident_id"]] = system
                    suite_of[r["incident_id"]] = "extra" if "extra" in name else "core"
    counts = collections.defaultdict(collections.Counter)
    incidents = collections.defaultdict(set)
    unknown = collections.Counter()
    with open(STORE) as f:
        for line in f:
            m = json.loads(line)
            if m.get("type") != "action" or m.get("incident_id") not in system_of:
                continue
            system = system_of[m["incident_id"]]
            incidents[system].add(m["incident_id"])
            c = category(m["body"])
            if c is None:
                continue
            if c == CATEGORIES[7]:
                unknown[(m["body"].get("status"), m["body"].get("reason", "")[:80])] += 1
            counts[system][c] += 1
    systems = ["B1", "B2", "S", "SF"]
    rows = [{"decision": "incidents in the store", **{s: len(incidents[s]) for s in systems}}]
    rows += [{"decision": c, **{s: counts[s][c] for s in systems}} for c in CATEGORIES]
    print("\t".join(["decision"] + systems))
    for r in rows:
        print("\t".join([r["decision"]] + [str(r[s]) for s in systems]))
    if unknown:
        print("uncategorized:", dict(unknown))
    if args.out:
        with open(args.out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["decision"] + systems)
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    main()
