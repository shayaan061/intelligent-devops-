"""Builds Evaluation_Results.docx: every evaluation figure with its reading, plus summary tables.

Usage: python build_doc.py   (after make_figures.py; needs python-docx)
Numbers come from experiments/results/*summary.json and soak_1_summary.json.
"""
import json
import os

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
RES = os.path.join(ROOT, "experiments", "results")
FIG = os.path.join(HERE, "figures")
OUT = os.path.join(HERE, "Evaluation_Results.docx")

c = json.load(open(os.path.join(RES, "eval_stage3_summary.json")))
e = json.load(open(os.path.join(RES, "eval_extra_stage3_summary.json")))
soaks = []  # one real window per soak test (the 18 s restarted window is skipped)
for name in ("soak_1_summary.json", "soak_2_summary.json"):
    path = os.path.join(RES, name)
    if os.path.exists(path):
        for w in json.load(open(path)):
            if w["awake_hours"] >= 1 and w["start"] not in [x["start"] for x in soaks]:
                soaks.append(w)

GREY = RGBColor(0x52, 0x51, 0x4E)
doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
for side in ("left_margin", "right_margin"):
    setattr(sec, side, Cm(2.0))
sec.top_margin = sec.bottom_margin = Cm(2.0)
style = doc.styles["Normal"]
style.font.name = "Calibri"
style.font.size = Pt(10.5)

fig_no = [0]


def shade(cell, hexcolor):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hexcolor)
    tcPr.append(shd)


def para(text, bold_lead=None, size=None, color=None, italic=False, space_after=6):
    p = doc.add_paragraph()
    if bold_lead:
        r = p.add_run(bold_lead)
        r.bold = True
    r = p.add_run(text)
    r.italic = italic
    if size:
        r.font.size = Pt(size)
    if color:
        r.font.color.rgb = color
    p.paragraph_format.space_after = Pt(space_after)
    return p


def table(header, rows, widths_cm, bold_col=None):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(header):
        cell = t.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(h)
        run.bold = True
        run.font.size = Pt(9.5)
        shade(cell, "EDECE7")
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            run = cells[i].paragraphs[0].add_run(str(v))
            run.font.size = Pt(9.5)
            if bold_col is not None and i == bold_col:
                run.bold = True
    for row in t.rows:
        for i, w in enumerate(widths_cm):
            row.cells[i].width = Cm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def figure(name, reading):
    fig_no[0] += 1
    doc.add_picture(os.path.join(FIG, name), width=Cm(17.0))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap = doc.add_paragraph()
    r = cap.add_run(f"Figure {fig_no[0]}. ")
    r.bold = True
    r.font.size = Pt(9)
    r = cap.add_run(reading)
    r.font.size = Pt(9)
    r.font.color.rgb = GREY
    cap.paragraph_format.space_after = Pt(12)


def pct(x):
    return f"{x:g}%"


def sec_(x):
    return f"{x:.1f} s"


# ---------------------------------------------------------------- title
h = doc.add_heading("Evaluation Results: Intelligent DevOps Monitoring & Incident Response", level=0)
para("Final results of the §10 evaluation, 11-22 Oct 2026. Generated 23 Oct 2026 from experiments/results/.",
     color=GREY, size=9.5)

para(f"The full system (S) detected every core fault in {c['S']['mttd_s']['mean']:.1f} s on average, against "
     f"{c['B1']['mttd_s']['mean']:.1f} s for the rule-based baselines, and recovered in {c['S']['mttr_s']['mean']:.1f} s. "
     f"Across {c['B1']['runs'] + c['B2']['runs'] + c['S']['runs'] + e['B1']['runs'] + e['B2']['runs'] + e['S']['runs'] + e['SF']['runs']} "
     "runs no system executed an unsafe action or raised a false alarm.", bold_lead="Headline. ")

# ---------------------------------------------------------------- setup
doc.add_heading("1. What was tested", level=1)
para("Faults were injected into a 3-service demo app (frontend → api-service → Redis) on one Mac with Docker Compose, "
     "under steady load (Locust, 5 users). Four variants of the system were compared; every action went through the "
     "same policy validator, was verified after 45 s and escalated after 3 attempts.")
table(["System", "Detection", "Analysis", "Runs"],
      [["B1", "Prometheus rules", "YAML runbooks", f"{c['B1']['runs']} core + {e['B1']['runs']} extra"],
       ["B2", "Prometheus rules", "LLM (llama3.1:8b)", f"{c['B2']['runs']} core + {e['B2']['runs']} extra"],
       ["S (full system)", "Rules + ML detector", "LLM with runbook fallback", f"{c['S']['runs']} core + {e['S']['runs']} extra"],
       ["SF (LLM down)", "Rules + ML detector", "Runbooks only (LLM unreachable)", f"{e['SF']['runs']} (core scenarios 3, 4, 6, 8)"]],
      [3.4, 3.8, 4.8, 5.0], bold_col=0)
para("Core suite: 9 faults the runbooks cover (CPU, memory, latency, errors, stopped containers, gradual leak, "
     "CPU + latency), 20 runs per scenario per system. Extra suite: 5 harder faults (corrupted cache and slow Redis, "
     "which mislead towards api-service; 0.6 s latency and 5% errors, below the alert thresholds; a fault that recurs "
     "after every fix), 10 runs each.")

# ---------------------------------------------------------------- core
doc.add_heading("2. Core suite: 540 runs", level=1)
table(["Metric", "B1 runbooks", "B2 LLM", "S full system"],
      [["Faults detected", pct(c['B1']['recall_pct']), pct(c['B2']['recall_pct']), pct(c['S']['recall_pct'])],
       ["False-positive incidents", c['B1']['false_positive_incidents'], c['B2']['false_positive_incidents'], c['S']['false_positive_incidents']],
       ["Unsafe actions executed", c['B1']['unsafe_actions_executed'], c['B2']['unsafe_actions_executed'], c['S']['unsafe_actions_executed']],
       ["Root cause correct (first plan)", pct(c['B1']['root_cause_accuracy_pct']), pct(c['B2']['root_cause_accuracy_pct']), pct(c['S']['root_cause_accuracy_pct'])],
       ["Correct action executed", pct(c['B1']['executed_action_accuracy_pct']), pct(c['B2']['executed_action_accuracy_pct']), pct(c['S']['executed_action_accuracy_pct'])],
       ["Fixed automatically", pct(c['B1']['auto_resolved_pct']), pct(c['B2']['auto_resolved_pct']), pct(c['S']['auto_resolved_pct'])],
       ["MTTD mean / median", f"{sec_(c['B1']['mttd_s']['mean'])} / {sec_(c['B1']['mttd_s']['median'])}",
        f"{sec_(c['B2']['mttd_s']['mean'])} / {sec_(c['B2']['mttd_s']['median'])}", f"{sec_(c['S']['mttd_s']['mean'])} / {sec_(c['S']['mttd_s']['median'])}"],
       ["MTTR mean / median", f"{sec_(c['B1']['mttr_s']['mean'])} / {sec_(c['B1']['mttr_s']['median'])}",
        f"{sec_(c['B2']['mttr_s']['mean'])} / {sec_(c['B2']['mttr_s']['median'])}", f"{sec_(c['S']['mttr_s']['mean'])} / {sec_(c['S']['mttr_s']['median'])}"],
       ["Escalated to a human", pct(c['B1']['escalated_pct']), pct(c['B2']['escalated_pct']), pct(c['S']['escalated_pct'])]],
      [5.6, 3.8, 3.8, 3.8], bold_col=0)
para("MTTD = fault start → incident opened. MTTR = fault start → fault gone. n = 180 runs per system.", size=9, color=GREY)

figure("fig1_core_mttd.png",
       "Detection time per core scenario. The ML detector halves detection on the CPU faults (~46 s → ~30 s) and "
       "catches the gradual memory leak before the memory alert, 225 s → 51 s. On the other faults the alert rules "
       "are about as fast.")
figure("fig2_core_mttr.png",
       "Recovery time per core scenario. Asking the LLM adds about 30 s to every fix (B1 → B2). S gets that time back "
       "only on the gradual leak, so its overall mean (74.1 s) equals the runbooks' (75.3 s); without the leak the "
       "runbooks are faster (53.0 s vs 70.8 s).")
figure("fig3_core_mttr_spread.png",
       "Spread of recovery times. S is the most predictable system: its recovery time varies by 15 s (standard "
       "deviation) against about 64 s for the baselines, whose gradual-leak runs take over 4 minutes.")
figure("fig4_core_correct_actions.png",
       "Correct executed action per scenario. The runbooks never miss. Almost all LLM misses are on the error fault, "
       "where it restarts the container instead of resetting the fault (the restart also clears the fault, so it is not "
       "harmful). S's 4 misdiagnoses (latency and Redis) were all fixed on the second attempt by the verify loop.")
figure("fig5_core_mttd_by_round.png",
       "Detection time round by round. The gap between S and the baselines is stable across all 20 rounds, including "
       "after the 16 Oct gateway change (round 5 onwards), so pooling all rounds is justified.")

# ---------------------------------------------------------------- extra
doc.add_heading("3. Extra suite: harder faults (190 runs)", level=1)
para("Scenarios 10-14, 10 runs each, on B1, B2 and S (the LLM-down system SF ran different, easier faults; see the "
     "next table).")
table(["Metric", "B1", "B2", "S"],
      [["Runs", e['B1']['runs'], e['B2']['runs'], e['S']['runs']],
       ["Faults detected (of all runs)", pct(e['B1']['recall_pct']), pct(e['B2']['recall_pct']), pct(e['S']['recall_pct'])],
       ["Fixed automatically (of all runs)", pct(e['B1']['auto_resolved_pct']), pct(e['B2']['auto_resolved_pct']), pct(e['S']['auto_resolved_pct'])],
       ["Escalated to a human (of detected runs)", pct(e['B1']['escalated_pct']), pct(e['B2']['escalated_pct']), pct(e['S']['escalated_pct'])],
       ["Unsafe actions executed", e['B1']['unsafe_actions_executed'], e['B2']['unsafe_actions_executed'], e['S']['unsafe_actions_executed']],
       ["False-positive incidents", e['B1']['false_positive_incidents'], e['B2']['false_positive_incidents'], e['S']['false_positive_incidents']]],
      [6.6, 3.4, 3.4, 3.4], bold_col=0)

# SF against S on the same four core scenarios
import csv as _csv
import statistics as _st


def _rows(prefix, s):
    return list(_csv.DictReader(open(os.path.join(RES, f"{prefix}_{s}_runs.csv"))))


_S, _SF = _rows("eval_stage3", "S"), _rows("eval_extra_stage3", "SF")
_names = {3: "Memory", 4: "Latency", 6: "Redis stopped", 8: "Gradual leak"}


def _cell(rows, sc):
    g = [r for r in rows if int(r["scenario"]) == sc]
    fixed = sum(r["auto_resolved"] == "True" for r in g)
    t = [float(r["mttr_s"]) for r in g if r["mttr_s"]]
    return f"{fixed}/{len(g)} fixed, {_st.mean(t):.0f} s" if t else f"{fixed}/{len(g)} fixed"


def _total(rows):
    g = [r for r in rows if int(r["scenario"]) in _names]
    return f"{sum(r['auto_resolved'] == 'True' for r in g) / len(g) * 100:.0f}% fixed"


para("Losing the LLM: S and SF on the same four core faults. SF is about 30 s faster when it works (no LLM call) "
     "but fixes fewer faults, because the runbooks have no plan for a latency incident the ML detector opens before "
     "the alert fires.")
table(["Scenario", "S (LLM up), 20 runs", "SF (LLM down), 10 runs"],
      [[_names[sc], _cell(_S, sc), _cell(_SF, sc)] for sc in _names] + [["Overall", _total(_S), _total(_SF)]],
      [4.6, 5.6, 5.6], bold_col=0)
para("Mean recovery time of the fixed runs. SF shows that the system keeps working, safely, when the LLM is "
     "unreachable; it is not a better system.", size=9, color=GREY)
figure("fig6_extra_detected.png",
       "Detection per extra scenario. Faults below the alert thresholds are invisible to the rules: B1 and B2 detect "
       "0 of 20. S detects the 0.6 s latency in all 10 runs and fixes it every time; the 5% error rate is detected in "
       "only 5 of 10 runs, late (160 s on average), and the responder skipped those plans as 'already cleared'.")
figure("fig7_extra_outcomes.png",
       "Outcome of every extra run. No variant traced the misleading Redis faults (corrupted cache, slow Redis) to Redis: "
       "all blamed api-service, tried reset and restart, and escalated after 3 attempts. The recurring fault was "
       "escalated in all 30 runs, as designed. Nothing unsafe was executed: what the system could not fix went to a human.")
figure("fig8_sf_fallback.png",
       "With the LLM unreachable, the runbook fallback still fixes memory, Redis-stopped and gradual-leak faults in every "
       "run, faster than S (no ~30 s LLM call). Latency is the gap: when the ML detector opens the incident before the "
       "latency alert fires, no runbook matches, and 6 of 10 runs were escalated early.")

# ---------------------------------------------------------------- cost
doc.add_heading("4. Cost of the LLM", level=1)
figure("fig9_llm_cost.png",
       "Each LLM plan takes about 27-32 s with llama3.1:8b on this Mac, against under 1 ms for a runbook. Hard faults "
       "need several attempts, so the prompt tokens per incident rise from about 3-4k to 6-7k.")

# ---------------------------------------------------------------- soak
doc.add_heading("5. False alarms with no faults (soak test)", level=1)
hours = sum(w["awake_hours"] for w in soaks)
events = sum(w["events"] for w in soaks)
alarms = sum(w["false_alarms"] for w in soaks)
para(f"System S ran with no faults for {hours:.0f} hours over {len(soaks)} nights, with {events} harmless events "
     f"(a container restart or a load change between 2 and 10 users every 30 minutes). It raised {alarms} false alarms "
     "and executed no actions.")
table(["Soak", "Window (UTC)", "Hours", "Events", "False alarms", "Actions"],
      [[i + 1, f"{w['start'][:16].replace('T', ' ')} → {w['end'][5:16].replace('T', ' ')}", f"{w['awake_hours']:.0f}",
        w["events"], w["false_alarms"], w["actions_executed"]] for i, w in enumerate(soaks)],
      [1.4, 6.4, 1.8, 2.0, 2.6, 2.0])

# ---------------------------------------------------------------- caveats
doc.add_heading("6. Limits of these results", level=1)
for t in ["One machine and one model (llama3.1:8b): LLM latency depends on this Mac.",
          "All core faults are ones the runbooks were written for; the extra suite covers faults they were not.",
          "The ML detector was trained at the same load (5 users) as the evaluation.",
          "B0 (a human fixing the faults by hand) was not run, so the claim 'faster than a human' (O6) is not measured.",
          "No plan ever proposed a risky action, so the human-approval path was tested by the safety suite and a live "
          "round trip, not by these runs.",
          "Extra suite: 10 runs per cell. Scenarios 10 and 11 are designed to mislead."]:
    doc.add_paragraph(t, style="List Bullet")

doc.add_heading("Sources", level=1)
for t in ["experiments/results/eval_stage3_{B1,B2,S}_runs.csv, eval_stage3_summary.json (core, RESULTS.md §18a)",
          "experiments/results/eval_extra_stage3_{B1,B2,S,SF}_runs.csv, eval_extra_stage3_summary.json (extra, §18b)",
          "experiments/results/soak_1_summary.json, soak_2_summary.json (soak tests, §16 and §19)",
          "Figures: docs/results/make_figures.py; this document: docs/results/build_doc.py"]:
    doc.add_paragraph(t, style="List Bullet")

doc.save(OUT)
print("wrote", OUT)
