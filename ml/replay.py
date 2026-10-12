"""Replay the ML detector offline over recorded metrics (§10 detection metrics).

Input: a `record_baseline.py --keep-all` export covering injected runs, the
trained model, and ground_truth.csv. The detector (same Detector class, same
sustain rule) is stepped through every 15 s sample in time order.

Per injected run: detected by ML? (an anomaly on any service of the chain
between `start` and `end` + GRACE), the delay from `start`, and whether the
target service was among the anomalous ones. Anomalies outside every run
window (± GRACE) are false-positive episodes (consecutive anomalous samples
of one service count once).

This measures the detector alone. The live system's MTTD still comes from
experiments/score.py (incident store vs. ground truth).

Usage:
  python ml/replay.py experiments/replay_<stamp>.csv --since 2026-10-09T12:30:00Z
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone

import joblib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from detector import Detector  # noqa: E402

GRACE = 60  # seconds after a run's end that still count as that run


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def replay(rows, models, sustain=2):
    """Yields (t, anomaly) for every sample the detector would POST."""
    det = Detector(models, sustain=sustain)
    for r in sorted(rows, key=lambda r: (r["timestamp"], r["service"])):
        if r["service"] in models:
            out = det.step(r["service"], r)
            if out:
                yield ts(r["timestamp"]), out


def evaluate(rows, models, runs, sustain=2):
    events = list(replay(rows, models, sustain))
    t0, t1 = ts(min(r["timestamp"] for r in rows)), ts(max(r["timestamp"] for r in rows))
    per_run = []
    for run in runs:
        start = ts(run["start"])
        end = ts(run["end"] or run["planned_end"])
        if start < t0 or start > t1:
            continue
        hits = [(t, a) for t, a in events if start <= t <= end + GRACE]
        first = hits[0] if hits else None
        per_run.append({
            "run_id": run["run_id"], "scenario": int(run["scenario"]), "name": run["name"],
            "target": run["target_service"], "end_reason": run["end_reason"],
            "detected": bool(hits),
            "delay_s": round(first[0] - start) if first else None,
            "first_service": first[1]["service"] if first else None,
            "first_features": first[1]["top_features"] if first else None,
            "target_flagged": any(a["service"] == run["target_service"] for _, a in hits),
        })
    windows = [(ts(r["start"]) - GRACE, ts(r["end"] or r["planned_end"]) + GRACE) for r in runs]
    fp, last = [], {}
    for t, a in events:
        if any(lo <= t <= hi for lo, hi in windows):
            continue
        svc = a["service"]
        if svc not in last or t - last[svc] > 30:  # new episode
            fp.append({"t": datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"), "service": svc,
                       "features": a["top_features"]})
        last[svc] = t
    hours = (t1 - t0) / 3600
    return {"per_run": per_run, "false_positive_episodes": fp,
            "window": [rows[0]["timestamp"], rows[-1]["timestamp"]], "hours": round(hours, 2)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv")
    ap.add_argument("--model", default=os.path.join(HERE, "models", "detector.joblib"))
    ap.add_argument("--ground-truth", default=os.path.join(HERE, "..", "experiments", "ground_truth.csv"))
    ap.add_argument("--since", help="ignore runs before this ISO time")
    ap.add_argument("--json", help="write the full result here")
    args = ap.parse_args(argv)

    with open(args.csv, newline="") as f:
        rows = list(csv.DictReader(f))
    with open(args.ground_truth, newline="") as f:
        runs = [r for r in csv.DictReader(f) if not args.since or ts(r["start"]) >= ts(args.since)]
    bundle = joblib.load(args.model)
    res = evaluate(rows, bundle["models"], runs, bundle["report"].get("sustain", 2))

    print(f"{'scen':>4} {'name':<20} {'ML':<4} {'delay':>6}  first anomaly")
    for r in res["per_run"]:
        print(f"{r['scenario']:>4} {r['name']:<20} {'yes' if r['detected'] else 'no':<4} "
              f"{r['delay_s'] if r['delay_s'] is not None else '-':>6}  "
              f"{r['first_service'] or ''} {r['first_features'] or ''}")
    n = len(res["per_run"])
    print(f"\nrecall {sum(r['detected'] for r in res['per_run'])}/{n}; "
          f"false-positive episodes {len(res['false_positive_episodes'])} in {res['hours']} h")
    for e in res["false_positive_episodes"]:
        print(f"  FP {e['t']} {e['service']} {e['features']}")
    if args.json:
        with open(args.json, "w") as f:
            json.dump(res, f, indent=2)


if __name__ == "__main__":
    main()
