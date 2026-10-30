"""Mann-Whitney U test on MTTR between two systems of the core evaluation (per scenario and pooled).

    python3 experiments/mttr_significance.py [--a B1] [--b B2] [--out experiments/results/mttr_mwu_B1_B2.csv]

Reads experiments/results/eval_stage3_<system>_runs.csv (remediated runs with an mttr_s). Two-sided,
normal approximation with tie correction and continuity correction (adequate for n >= 20 per group),
no SciPy needed. Also reports the Hodges-Lehmann shift (median of all pairwise differences b - a).
"""
import argparse
import csv
import math
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")


def mttr(system):
    out = {}
    with open(os.path.join(RESULTS, f"eval_stage3_{system}_runs.csv"), newline="") as f:
        for r in csv.DictReader(f):
            if r["mttr_s"]:
                out.setdefault(r["scenario"], []).append(float(r["mttr_s"]))
    return out


def mann_whitney(a, b):
    """Returns U (for a), z and the two-sided p-value."""
    n1, n2 = len(a), len(b)
    pooled = sorted((v, g) for g, xs in ((0, a), (1, b)) for v in xs)
    ranks, ties, i = [0.0] * len(pooled), [], 0
    while i < len(pooled):
        j = i
        while j + 1 < len(pooled) and pooled[j + 1][0] == pooled[i][0]:
            j += 1
        for k in range(i, j + 1):
            ranks[k] = (i + j) / 2 + 1
        ties.append(j - i + 1)
        i = j + 1
    r1 = sum(rk for rk, (_, g) in zip(ranks, pooled) if g == 0)
    u1 = r1 - n1 * (n1 + 1) / 2
    n = n1 + n2
    mu = n1 * n2 / 2
    sigma = math.sqrt(n1 * n2 / 12 * ((n + 1) - sum(t ** 3 - t for t in ties) / (n * (n - 1))))
    if sigma == 0:
        return u1, 0.0, 1.0
    z = (u1 - mu - math.copysign(0.5, u1 - mu)) / sigma if u1 != mu else 0.0
    p = math.erfc(abs(z) / math.sqrt(2))
    return u1, z, p


def hodges_lehmann(a, b):
    return statistics.median(y - x for x in a for y in b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="B1")
    ap.add_argument("--b", default="B2")
    ap.add_argument("--out")
    args = ap.parse_args()
    A, B = mttr(args.a), mttr(args.b)
    rows = []
    groups = [(s, A.get(s, []), B.get(s, [])) for s in sorted(set(A) | set(B), key=int)]
    groups.append(("all except 8", [v for s, xs in A.items() if s != "8" for v in xs],
                   [v for s, xs in B.items() if s != "8" for v in xs]))
    for name, a, b in groups:
        u, z, p = mann_whitney(a, b)
        rows.append({"scenario": name, f"n_{args.a}": len(a), f"n_{args.b}": len(b),
                     f"median_{args.a}": round(statistics.median(a), 1),
                     f"median_{args.b}": round(statistics.median(b), 1),
                     "hl_shift_s": round(hodges_lehmann(a, b), 1),
                     "U": round(u, 1), "z": round(z, 2), "p": f"{p:.2g}"})
    keys = list(rows[0])
    print("\t".join(keys))
    for r in rows:
        print("\t".join(str(r[k]) for k in keys))
    if args.out:
        with open(args.out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    main()
