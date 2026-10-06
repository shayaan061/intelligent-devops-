"""Export normal-traffic training data for the ML detector (§6.2, Phase 7).

Leave the stack running under Locust with no faults for 1-2 hours, then run
this. It pulls the detector's features per service from Prometheus at a
15 s step and writes one CSV row per (timestamp, service).

The features are the gateway's context queries (gateway/context.py), so the
detector trains on exactly what the system sees at runtime, and the same
import-time guard keeps fault_* ground truth out. Any sample within
--margin seconds of an injected run in ground_truth.csv is dropped, so the
data is "normal" only. Manual faults (curl /inject, the injector UI's demo
buttons) aren't in ground_truth.csv, so samples within --margin of any
pending or firing alert (Prometheus ALERTS, i.e. rule output, not the
fault_* ground truth) are dropped too.

Prometheus in compose has no volume: recreating the container loses its
history. Export before `docker compose down` or a rebuild of prometheus.
Prometheus caps a range query at 11,000 points, so long windows are
fetched in chunks.

Usage:
  python experiments/record_baseline.py --last 2h
  python experiments/record_baseline.py --start 2026-10-06T18:00:00Z --end 2026-10-06T20:00:00Z
"""

import argparse
import csv
import math
import os
import sys
import time
from datetime import datetime, timezone

import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "gateway"))

from context import SERVICE_QUERIES, clean  # noqa: E402  (asserts: no fault_* query)

STEP = 15
CHUNK = 2000 * STEP  # seconds per range query, well under Prometheus's 11k-point cap


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_last(s):
    units = {"s": 1, "m": 60, "h": 3600}
    return float(s[:-1]) * units[s[-1]] if s and s[-1] in units else float(s)


def fault_windows(path, margin):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        start = ts(r["start"])
        end = ts(r["end"]) if r.get("end") else ts(r["planned_end"])
        out.append((start - margin, end + margin))
    return out


def in_fault(t, windows):
    return any(lo <= t <= hi for lo, hi in windows)


def fetch(client, prom, query, start, end):
    """{timestamp: value} over [start, end], chunked."""
    points = {}
    t = start
    while t <= end:
        stop = min(t + CHUNK, end)
        r = client.get(f"{prom}/api/v1/query_range",
                       params={"query": query, "start": t, "end": stop, "step": STEP})
        r.raise_for_status()
        result = r.json()["data"]["result"]
        if result:
            for when, v in result[0]["values"]:
                points[round(float(when))] = clean(v)
        t = stop + STEP
    return points


def export(prom, start, end, out, ground_truth, margin):
    start = math.floor(start / STEP) * STEP
    windows = fault_windows(ground_truth, margin)
    features = sorted({m for qs in SERVICE_QUERIES.values() for m in qs})
    rows, dropped = [], 0
    with httpx.Client(timeout=30) as client:
        alerting = fetch(client, prom, "count(ALERTS)", start - margin, end + margin)
        windows += [(t - margin, t + margin) for t, v in alerting.items() if v]
        for svc, queries in SERVICE_QUERIES.items():
            series = {m: fetch(client, prom, q.format(s=svc), start, end) for m, q in queries.items()}
            t = start
            while t <= end:
                if in_fault(t, windows):
                    dropped += 1
                else:
                    rows.append({"timestamp": iso(t), "service": svc,
                                 **{m: series[m].get(t) if m in series else None for m in features}})
                t += STEP
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "service"] + features)
        w.writeheader()
        w.writerows(rows)
    return len(rows), dropped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prometheus", default=os.environ.get("PROMETHEUS_URL", "http://localhost:9090"))
    ap.add_argument("--last", help="window ending now, e.g. 2h, 90m")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--ground-truth", default=os.path.join(HERE, "ground_truth.csv"))
    ap.add_argument("--margin", type=float, default=120, help="seconds dropped around each injected run")
    ap.add_argument("--out")
    args = ap.parse_args(argv)

    if args.last:
        end = time.time()
        start = end - parse_last(args.last)
    elif args.start:
        start, end = ts(args.start), ts(args.end) if args.end else time.time()
    else:
        ap.error("give --last or --start")
    out = args.out or os.path.join(HERE, f"baseline_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")
    n, dropped = export(args.prometheus, start, end, out, args.ground_truth, args.margin)
    print(f"{n} rows -> {out} ({dropped} samples dropped near injected faults or alerts)")


if __name__ == "__main__":
    main()
