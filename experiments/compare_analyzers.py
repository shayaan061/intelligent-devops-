"""Offline B1 vs B2: runbooks vs LLM on the hand-written incident samples.

Runs every analyzer/samples/scenario*.json through analyze() in runbook
mode (baseline B1) and in llm mode (B2, Ollama with runbook fallback), and
scores root cause and recommended action with the same rules as
experiments/score.py (§10 accepted actions). LLM plans that fell back to a
runbook are marked, so the LLM's own accuracy is reported separately from
the system's.

These are 9 hand-written samples, one of which (scenario 4) has the same
shape as a few-shot example in the prompt. Use it to compare prompt or
model changes quickly; the §10 evaluation on real runs is what counts.

Usage:
  OLLAMA_URL=http://localhost:11434 python experiments/compare_analyzers.py
  ... --model llama3.2:3b --repeat 3 --out compare.csv
"""

import argparse
import csv
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "analyzer"))
sys.path.insert(0, HERE)

from score import ACCEPTABLE  # noqa: E402

# Expected root cause per scenario (injector/injector.py SCENARIOS, §10)
EXPECTED_ROOT = {"1": "frontend", "2": "api-service", "3": "api-service", "4": "api-service",
                 "5": "api-service", "6": "redis", "7": "frontend", "8": "api-service", "9": "api-service"}


def judge(scenario, plan):
    a = plan["recommended_action"] or {}
    root_ok = plan["root_cause_service"] == EXPECTED_ROOT[scenario]
    action_ok = a.get("type") in ACCEPTABLE[scenario] and a.get("target") == EXPECTED_ROOT[scenario]
    return root_ok, action_ok


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--samples", default=os.path.join(HERE, "..", "analyzer", "samples"))
    ap.add_argument("--model", help="override OLLAMA_MODEL")
    ap.add_argument("--repeat", type=int, default=1, help="LLM runs per sample (checks consistency)")
    ap.add_argument("--out", help="write per-run rows to this CSV")
    args = ap.parse_args(argv)
    if args.model:
        os.environ["OLLAMA_MODEL"] = args.model

    import analyzer  # after OLLAMA_MODEL is set: llm.py reads it at import
    runbooks = analyzer.load_runbooks()

    rows = []
    paths = sorted(glob.glob(os.path.join(args.samples, "scenario*.json")),
                   key=lambda p: int(re.search(r"(\d+)", os.path.basename(p)).group(1)))
    for path in paths:
        scenario = re.search(r"(\d+)", os.path.basename(path)).group(1)
        incident = json.load(open(path))
        runs = [("runbook", 1)] + [("llm", i + 1) for i in range(args.repeat)]
        for mode, rep in runs:
            plan = analyzer.analyze(incident, mode=mode, runbooks=runbooks).model_dump()
            root_ok, action_ok = judge(scenario, plan)
            a = plan["recommended_action"] or {}
            rows.append({"scenario": scenario, "mode": mode, "rep": rep, "source": plan["source"],
                         "fallback_reason": plan["fallback_reason"] or "",
                         "root": plan["root_cause_service"], "root_ok": root_ok,
                         "action": f'{a.get("type")}/{a.get("target")}', "action_ok": action_ok,
                         "confidence": plan["confidence"], "latency_s": round(plan["latency_ms"] / 1000, 1)})
            r = rows[-1]
            print(f'scenario {scenario} {mode:7} rep {rep}  source={r["source"]:7} root={r["root"]} '
                  f'({"ok" if root_ok else "WRONG"})  action={r["action"]} ({"ok" if action_ok else "WRONG"})  '
                  f'conf={r["confidence"]}  {r["latency_s"]}s {r["fallback_reason"]}', flush=True)

    def pct(xs):
        return f"{100 * sum(xs) / len(xs):.0f}% ({sum(xs)}/{len(xs)})" if xs else "n/a"

    print()
    for mode in ("runbook", "llm"):
        sel = [r for r in rows if r["mode"] == mode]
        print(f"{mode:8} root cause {pct([r['root_ok'] for r in sel]):14} action {pct([r['action_ok'] for r in sel])}")
    own = [r for r in rows if r["mode"] == "llm" and r["source"] == "llm"]
    print(f"llm own  root cause {pct([r['root_ok'] for r in own]):14} action {pct([r['action_ok'] for r in own])}"
          f"  (plans the LLM produced itself; {len(own)} of {sum(r['mode'] == 'llm' for r in rows)}, rest fell back)")
    lat = [r["latency_s"] for r in own]
    if lat:
        print(f"llm latency: mean {sum(lat) / len(lat):.1f}s, max {max(lat)}s")
    if args.out:
        with open(args.out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    main()
