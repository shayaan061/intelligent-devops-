"""Train the ML detector on normal traffic (SUGGESTED_PLAN.md §6.2, Phase 7).

Input: one or more CSVs from experiments/record_baseline.py (normal traffic
only: samples near injected faults or alerts are already dropped).

Each service's rows are split in time order: the first 80% train a
throwaway model and the last 20% measure its false-positive rate (how often
a normal sample, or two in a row as the detector requires, gets flagged).
The saved model is then refit on all rows.

Usage:
  python ml/train.py experiments/baseline_20261009_1500.csv [more.csv ...]
  python ml/train.py baseline.csv --out ml/models/detector.joblib --z 4
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone

import joblib
import sklearn

from model import FEATURES, fit_all, ServiceModel

HERE = os.path.dirname(os.path.abspath(__file__))
SUSTAIN = 2


def load(paths):
    rows = []
    for p in paths:
        with open(p, newline="") as f:
            rows += list(csv.DictReader(f))
    rows.sort(key=lambda r: r["timestamp"])
    return rows


def holdout(rows, z, z_soft, quantile, split=0.8):
    """Per service: false-positive rate on the last 20% (single and sustained)."""
    out = {}
    for svc in FEATURES:
        svc_rows = [r for r in rows if r["service"] == svc]
        cut = int(len(svc_rows) * split)
        m = ServiceModel(svc, z_threshold=z, z_soft=z_soft, if_quantile=quantile).fit(svc_rows[:cut])
        flags = [m.score(r)["anomalous"] for r in svc_rows[cut:]]
        run, sustained = 0, 0
        for f in flags:
            run = run + 1 if f else 0
            sustained += run >= SUSTAIN
        n = len(flags)
        out[svc] = {"holdout_samples": n, "flagged": sum(flags), "flagged_sustained": sustained,
                    "fp_rate": round(sum(flags) / n, 4) if n else None,
                    "fp_rate_sustained": round(sustained / n, 4) if n else None}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--out", default=os.path.join(HERE, "models", "detector.joblib"))
    ap.add_argument("--z", type=float, default=4.0, help="z-score threshold for a HIGH_IS_BAD metric")
    ap.add_argument("--z-soft", type=float, default=2.0, help="z gate for the Isolation Forest path")
    ap.add_argument("--quantile", type=float, default=0.995, help="Isolation Forest threshold quantile")
    args = ap.parse_args(argv)

    rows = load(args.csv)
    report = {"trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "sources": [os.path.basename(p) for p in args.csv],
              "window": [rows[0]["timestamp"], rows[-1]["timestamp"]] if rows else None,
              "z_threshold": args.z, "z_soft": args.z_soft, "if_quantile": args.quantile, "sustain": SUSTAIN,
              "sklearn": sklearn.__version__,
              "holdout": holdout(rows, args.z, args.z_soft, args.quantile)}
    models = fit_all(rows, z_threshold=args.z, z_soft=args.z_soft, if_quantile=args.quantile)
    report["models"] = {svc: m.summary() for svc, m in models.items()}

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    joblib.dump({"models": models, "report": report}, args.out)
    with open(os.path.splitext(args.out)[0] + "_report.json", "w") as f:
        json.dump(report, f, indent=2)
    json.dump(report["holdout"], sys.stdout, indent=2)
    print(f"\nsaved -> {args.out}")


if __name__ == "__main__":
    main()
