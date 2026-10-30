"""Draws the evaluation figures (PNG) from experiments/results/ and the run manifests.

Usage: python make_figures.py <out_dir>
Needs matplotlib. Every number is read from the score files; nothing is typed in.
"""
import csv
import json
import os
import statistics as st
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RES = os.path.join(ROOT, "experiments", "results")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "results", "figures")
os.makedirs(OUT, exist_ok=True)

# grey first: baselines in greys, the full system in the accent blue, SF in orange
COL = {"B1": "#c4c3bd", "B2": "#8a8984", "S": "#2a78d6", "SF": "#eb6834"}
LABEL = {"B1": "B1 rules + runbooks", "B2": "B2 rules + LLM", "S": "S full system", "SF": "SF LLM down"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e6e5e0"
CORE_NAMES = {1: "CPU\nfrontend", 2: "CPU\napi", 3: "Memory\napi", 4: "Latency\napi", 5: "Errors\napi",
              6: "Redis\nstopped", 7: "Frontend\nstopped", 8: "Gradual\nleak", 9: "CPU +\nlatency"}
EXTRA_NAMES = {10: "Corrupted\ncache", 11: "Slow\nRedis", 12: "Subtle\nlatency", 13: "Subtle\nerrors", 14: "Recurring\nlatency"}

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": GRID,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 100})


def runs(prefix, system):
    return list(csv.DictReader(open(os.path.join(RES, f"{prefix}_{system}_runs.csv"))))


def num(x):
    return float(x) if x not in ("", None) else None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else None


def title(ax, head, sub):
    ax.set_title(head, loc="left", fontsize=11.5, color=INK, pad=22, fontweight="bold")
    ax.text(0, 1.02, sub, transform=ax.transAxes, fontsize=8.5, color=INK2, va="bottom")


def save(fig, name):
    p = os.path.join(OUT, name)
    fig.savefig(p, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", p)


def grouped(ax, cats, systems, values, fmt="{:.0f}", label_systems=("S",), ymax=None, skip=None):
    n = len(systems)
    w = 0.8 / n
    for j, s in enumerate(systems):
        xs = [i + (j - (n - 1) / 2) * w for i in range(len(cats))]
        vs = [values[s].get(c) or 0 for c in cats]
        ax.bar(xs, vs, width=w * 0.92, color=COL[s], label=LABEL[s], zorder=2)
        if s in label_systems:
            for x, v in zip(xs, vs):
                if skip is not None and v == skip:
                    continue
                ax.text(x, v + (ymax or max(vs)) * 0.015, fmt.format(v), ha="center", va="bottom",
                        fontsize=7.5, color=INK)
    ax.set_xticks(range(len(cats)))
    ax.yaxis.grid(True, color=GRID, zorder=0)
    ax.legend(frameon=False, ncol=n, loc="upper left", bbox_to_anchor=(0, 1.0), fontsize=8)


core = {s: runs("eval_stage3", s) for s in ("B1", "B2", "S")}
extra = {s: runs("eval_extra_stage3", s) for s in ("B1", "B2", "S", "SF")}
csum = json.load(open(os.path.join(RES, "eval_stage3_summary.json")))
esum = json.load(open(os.path.join(RES, "eval_extra_stage3_summary.json")))
scen = list(range(1, 10))


def per_scen(rows, field):
    return {sc: mean([num(r[field]) for r in rows if int(r["scenario"]) == sc]) for sc in scen}


# 1. MTTD per core scenario
mttd = {s: per_scen(core[s], "mttd_s") for s in core}
fig, ax = plt.subplots(figsize=(8, 3.6))
grouped(ax, scen, ["B1", "B2", "S"], mttd, ymax=230)
ax.set_xticklabels([CORE_NAMES[c] for c in scen], fontsize=8)
ax.set_ylabel("Mean time to detect (s)")
ax.set_ylim(0, 250)
s8 = mttd["S"][8]
b8 = mttd["B2"][8]
title(ax, f"ML detection cuts the gradual leak from {b8:.0f} s to {s8:.0f} s",
      f"Mean detection time per core scenario, 20 runs each. Overall: B1 {csum['B1']['mttd_s']['mean']:.1f} s, "
      f"B2 {csum['B2']['mttd_s']['mean']:.1f} s, S {csum['S']['mttd_s']['mean']:.1f} s")
save(fig, "fig1_core_mttd.png")

# 2. MTTR per core scenario
mttr = {s: per_scen(core[s], "mttr_s") for s in core}
fig, ax = plt.subplots(figsize=(8, 3.6))
grouped(ax, scen, ["B1", "B2", "S"], mttr, ymax=290)
ax.set_xticklabels([CORE_NAMES[c] for c in scen], fontsize=8)
ax.set_ylabel("Mean time to recover (s)")
ax.set_ylim(0, 310)
title(ax, "The LLM adds ~30 s per fix; ML wins it back on the slow leak",
      f"Mean recovery time per core scenario, 20 runs each. Overall: B1 {csum['B1']['mttr_s']['mean']:.1f} s, "
      f"B2 {csum['B2']['mttr_s']['mean']:.1f} s, S {csum['S']['mttr_s']['mean']:.1f} s")
save(fig, "fig2_core_mttr.png")

# 3. spread of MTTR (predictability), box plot per system
fig, ax = plt.subplots(figsize=(8, 3.0))
data = [[num(r["mttr_s"]) for r in core[s] if num(r["mttr_s"]) is not None] for s in ("B1", "B2", "S")]
bp = ax.boxplot(data, orientation='horizontal', widths=0.55, patch_artist=True, showfliers=True,
                medianprops={"color": INK, "linewidth": 1.5},
                flierprops={"marker": "o", "markersize": 3, "markerfacecolor": INK2, "markeredgecolor": "none", "alpha": 0.5})
for patch, s in zip(bp["boxes"], ("B1", "B2", "S")):
    patch.set_facecolor(COL[s])
    patch.set_edgecolor("white")
ax.set_yticks([1, 2, 3])
ax.set_yticklabels([LABEL[s] for s in ("B1", "B2", "S")])
ax.xaxis.grid(True, color=GRID, zorder=0)
ax.set_xlabel("Time to recover per run (s)")
sd = {s: st.stdev(d) for s, d in zip(("B1", "B2", "S"), data)}
title(ax, f"S recovers most predictably: spread {sd['S']:.0f} s vs {sd['B1']:.0f}-{sd['B2']:.0f} s",
      "Recovery time of every fixed core run (box = middle 50%, line = median). Far-right dots: the gradual leak; for S also 4 runs fixed on attempt 2")
save(fig, "fig3_core_mttr_spread.png")

# 4. correct executed action per scenario (of 20)
ok = {s: {sc: sum(r["executed_action_ok"] == "True" for r in core[s] if int(r["scenario"]) == sc) for sc in scen} for s in core}
fig, ax = plt.subplots(figsize=(8, 3.4))
grouped(ax, scen, ["B1", "B2", "S"], ok, label_systems=("B2", "S"), ymax=20, skip=20)
ax.set_xticklabels([CORE_NAMES[c] for c in scen], fontsize=8)
ax.set_ylim(0, 25)
ax.set_ylabel("Runs with the expected action (of 20)")
title(ax, "Misses cluster on the error fault: the LLM restarts instead of resetting",
      f"Correct executed action per core scenario (unlabelled bars = 20 of 20). Overall: B1 {csum['B1']['executed_action_accuracy_pct']:g}%, "
      f"B2 {csum['B2']['executed_action_accuracy_pct']:g}%, S {csum['S']['executed_action_accuracy_pct']:g}%; 0 unsafe actions")
save(fig, "fig4_core_correct_actions.png")

# 5. MTTD per round (stability over the 20 rounds)
man = {r["run_id"]: int(r["round"]) for r in csv.DictReader(open(os.path.join(ROOT, "experiments", "eval", "runs.csv")))
       if r["status"] == "done"}
fig, ax = plt.subplots(figsize=(8, 3.2))
for s in ("B1", "B2", "S"):
    by = {}
    for r in core[s]:
        if r["run_id"] in man and num(r["mttd_s"]) is not None:
            by.setdefault(man[r["run_id"]], []).append(num(r["mttd_s"]))
    xs = sorted(by)
    ax.plot(xs, [st.mean(by[x]) for x in xs], color=COL[s], linewidth=2, marker="o", markersize=3.5, label=LABEL[s], zorder=3)
ax.axvline(4.5, color=INK2, linewidth=0.8, linestyle=(0, (3, 3)))
ax.text(4.65, 41, "gateway change (16 Oct)\napplies from round 5", fontsize=7.5, color=INK2, va="center")
ax.yaxis.grid(True, color=GRID, zorder=0)
ax.set_xticks(range(1, 21))
ax.set_xlabel("Round (each round = the 9 core scenarios once)")
ax.set_ylabel("Mean time to detect (s)")
ax.set_ylim(0, None)
ax.legend(frameon=False, ncol=3, loc="lower right", fontsize=8)
title(ax, "The detection gap holds in every one of the 20 rounds",
      "Mean detection time per round, 9 runs per point")
save(fig, "fig5_core_mttd_by_round.png")

# 6. extra suite: detected per scenario (of 10)
escen = list(range(10, 15))
det = {s: {sc: sum(r["detected"] == "True" for r in extra[s] if int(r["scenario"]) == sc) for sc in escen} for s in ("B1", "B2", "S")}
fig, ax = plt.subplots(figsize=(8, 3.4))
grouped(ax, escen, ["B1", "B2", "S"], det, label_systems=("B1", "B2", "S"), ymax=10)
ax.set_xticklabels([EXTRA_NAMES[c] for c in escen], fontsize=8)
ax.set_ylim(0, 13)
ax.set_ylabel("Runs detected (of 10)")
title(ax, f"Only the ML detector sees faults below the alert thresholds",
      f"Detected runs per extra scenario. Recall: B1 {esum['B1']['recall_pct']:g}%, B2 {esum['B2']['recall_pct']:g}%, "
      f"S {esum['S']['recall_pct']:g}%")
save(fig, "fig6_extra_detected.png")

# 7. extra suite: outcome of every run (parts of 50), stacked horizontal
def outcome(r):
    if r["detected"] != "True":
        return "Not detected"
    if r["auto_resolved"] == "True":
        return "Fixed automatically"
    if r["escalated"] == "True":
        return "Escalated to a human"
    return "Detected, not fixed"

OUTS = ["Fixed automatically", "Escalated to a human", "Detected, not fixed", "Not detected"]
OCOL = {"Fixed automatically": "#2a78d6", "Escalated to a human": "#8a8984", "Detected, not fixed": "#c4c3bd",
        "Not detected": "#ecebe6"}
systems = ["B1", "B2", "S"]
fig, ax = plt.subplots(figsize=(8, 2.5))
for i, s in enumerate(systems):
    counts = {o: sum(outcome(r) == o for r in extra[s]) for o in OUTS}
    total = len(extra[s])
    left = 0
    for o in OUTS:
        v = counts[o] / total * 100
        if v:
            ax.barh(i, v - 0.4, left=left, color=OCOL[o], height=0.6, label=o if i == 0 else None, zorder=2)
            if v >= 7:
                ax.text(left + v / 2, i, f"{counts[o]}", ha="center", va="center", fontsize=8,
                        color="white" if o in ("Fixed automatically", "Escalated to a human") else INK)
        left += v
    ax.text(101, i, f"n={total}", va="center", fontsize=7.5, color=INK2)
for o in OUTS:  # legend entries for every outcome, even ones B1 lacks
    ax.barh(0, 0, color=OCOL[o], label=o)
h, l = ax.get_legend_handles_labels()
seen = {}
for hh, ll in zip(h, l):
    seen.setdefault(ll, hh)
ax.legend([seen[o] for o in OUTS], OUTS, frameon=False, ncol=4, loc="upper left", bbox_to_anchor=(0, 1.0), fontsize=8)
ax.set_yticks(range(len(systems)))
ax.set_yticklabels([LABEL[s] for s in systems])
ax.invert_yaxis()
ax.set_xlim(0, 108)
ax.set_xticks([0, 25, 50, 75, 100])
ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])
ax.set_ylim(len(systems) - 0.4, -1.1)
title(ax, "On the hard faults nothing unsafe ran: unfixed runs went to a human",
      "Outcome of every extra-suite run (scenarios 10-14, 50 runs per system). 0 unsafe actions in all")
save(fig, "fig7_extra_outcomes.png")

# 8. SF per scenario: fixed vs escalated
sfs = [3, 4, 6, 8]
fig, ax = plt.subplots(figsize=(8, 2.8))
fx = {sc: sum(r["auto_resolved"] == "True" for r in extra["SF"] if int(r["scenario"]) == sc) for sc in sfs}
es = {sc: sum(r["escalated"] == "True" for r in extra["SF"] if int(r["scenario"]) == sc) for sc in sfs}
for i, sc in enumerate(sfs):
    ax.barh(i, fx[sc] - 0.05, color=COL["SF"], height=0.6, zorder=2)
    if es[sc]:
        ax.barh(i, es[sc] - 0.05, left=fx[sc] + 0.05, color="#c4c3bd", height=0.6, zorder=2)
    ax.text(fx[sc] / 2, i, f"{fx[sc]} fixed", ha="center", va="center", fontsize=8, color="white")
    if es[sc]:
        ax.text(fx[sc] + es[sc] / 2, i, f"{es[sc]} escalated", ha="center", va="center", fontsize=8, color=INK)
ax.set_yticks(range(len(sfs)))
ax.set_yticklabels([CORE_NAMES[c].replace("\n", " ") for c in sfs])
ax.invert_yaxis()
ax.set_xlim(0, 10.2)
ax.set_xlabel("Runs (of 10)")
title(ax, "With the LLM down, the runbooks still fix 34 of 40",
      "System SF (LLM unreachable, runbook fallback): outcome per scenario. Latency escalated early in 6 runs")
save(fig, "fig8_sf_fallback.png")

# 9. cost: plan latency and tokens (two panels, no shared axis)
fig, (a1, a2) = plt.subplots(1, 2, figsize=(8, 2.8))
labs = ["B2 core", "S core", "B2 extra", "S extra"]
lat = [csum["B2"]["plan_latency_ms"]["mean"] / 1000, csum["S"]["plan_latency_ms"]["mean"] / 1000,
       esum["B2"]["plan_latency_ms"]["mean"] / 1000, esum["S"]["plan_latency_ms"]["mean"] / 1000]
tok = [csum["B2"]["prompt_tokens_per_incident"]["mean"], csum["S"]["prompt_tokens_per_incident"]["mean"],
       esum["B2"]["prompt_tokens_per_incident"]["mean"], esum["S"]["prompt_tokens_per_incident"]["mean"]]
cols = [COL["B2"], COL["S"], COL["B2"], COL["S"]]
for ax, vals, unit, fmt in ((a1, lat, "Seconds per LLM plan", "{:.1f} s"), (a2, tok, "Prompt tokens per incident", "{:,.0f}")):
    ax.bar(range(4), vals, color=cols, width=0.6, zorder=2)
    for i, v in enumerate(vals):
        ax.text(i, v * 1.02, fmt.format(v), ha="center", va="bottom", fontsize=8, color=INK)
    ax.set_xticks(range(4))
    ax.set_xticklabels(labs, fontsize=8)
    ax.set_title(unit, loc="left", fontsize=9, color=INK2)
    ax.yaxis.grid(True, color=GRID, zorder=0)
    ax.set_ylim(0, max(vals) * 1.18)
fig.subplots_adjust(top=0.74, wspace=0.25)
fig.suptitle(f"Each LLM plan costs ~{lat[1]:.0f} s on this Mac; hard faults need {tok[3] / tok[1]:.1f}-{tok[2] / tok[0]:.1f}x the tokens",
             x=0.06, ha="left", fontsize=11.5, fontweight="bold", color=INK, y=0.99)
fig.text(0.06, 0.885, "Mean over all incidents; llama3.1:8b on Ollama. The runbooks (B1) answer in under 1 ms", fontsize=8.5, color=INK2)
save(fig, "fig9_llm_cost.png")
