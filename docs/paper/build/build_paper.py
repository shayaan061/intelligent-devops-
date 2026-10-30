"""Builds the EmergIN 2027 paper (.docx) from the conference's IEEE Word template.

The text is below (CONTENT); every number comes from the score files that
`run_eval.py score` writes, so the paper is rebuilt with the final numbers by
running this again on the final files. Numbers and sentences that still depend
on the unfinished evaluation are highlighted in yellow while --provisional is set.

    python3 docs/paper/build/build_paper.py \
        --core  <dir with eval_stage3_{summary.json,by_scenario.csv,B1/B2/S_runs.csv}> \
        --extra <eval_extra_*_by_scenario.csv> [--extra-summary <eval_extra_*_summary.json>] \
        --out docs/paper/EmergIN2027_paper.docx [--provisional]

Template: docs/paper/template/conference-template2027.docx (Strict OOXML; its
styles number the headings, captions, table heads and references).
"""
import argparse
import csv
import json
import os
import re
import shutil
import statistics
import subprocess
import tempfile
import zipfile
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
PAPER = os.path.dirname(HERE)
TEMPLATE = os.path.join(PAPER, "template", "conference-template2027.docx")
FIGS = os.path.join(PAPER, "figures")

TITLE = "Policy-Guarded Remediation of Microservice Incidents Using a Local Large Language Model"

AUTHORS = [  # name, email, highlight; order and emails as in the invention disclosure ("Particulars of Inventors")
    ("Muhammad Shayaan Ali", "2023433557.muhammad@ug.sharda.ac.in", False),
    ("Riddhima Sharma", "2023567320.riddhima@ug.sharda.ac.in", False),
    ("Shruti Tyagi", "2023566902.shruti@ug.sharda.ac.in", False),
    ("Aliza Rana", "aliza.rana@sharda.ac.in", False),   # guide (Assistant Professor)
]
DEPT, ORG, CITY = "Dept. of Computer Science and Engineering", "Sharda University", "Greater Noida, India"

COL_WIDTH_IN = 3.38          # one column of the template (243 pt)
EMU = 914400

# ------------------------------------------------------------------ numbers

def load_numbers(core_dir, extra_csv, extra_summary):
    v = {}
    summ = json.load(open(os.path.join(core_dir, "eval_stage3_summary.json")))
    by = list(csv.DictReader(open(os.path.join(core_dir, "eval_stage3_by_scenario.csv"))))
    systems = ["B1", "B2", "S"]

    def f1(x):
        return f"{x:.1f}"

    def pct(x):
        return f"{x:.1f}".rstrip("0").rstrip(".") + "%"

    for s in systems:
        d = summ[s]
        v[f"n_{s}"] = str(d["runs"])
        v[f"recall_{s}"] = pct(d["recall_pct"])
        v[f"fp_{s}"] = str(d["false_positive_incidents"])
        v[f"mttd_{s}"] = f1(d["mttd_s"]["mean"])
        v[f"mttdmed_{s}"] = f1(d["mttd_s"]["median"])
        v[f"rc_{s}"] = pct(d["root_cause_accuracy_pct"])
        v[f"act_{s}"] = pct(d["executed_action_accuracy_pct"])
        v[f"unsafe_{s}"] = str(d["unsafe_actions_executed"])
        v[f"auto_{s}"] = pct(d["auto_resolved_pct"])
        v[f"mttr_{s}"] = f1(d["mttr_s"]["mean"])
        v[f"esc_{s}"] = pct(d["escalated_pct"])
        lat = d["plan_latency_ms"]["mean"] / 1000
        v[f"lat_{s}"] = f"{lat:.1f}" if lat >= 0.1 else "<0.1"
        calls = d.get("llm_calls_per_incident") or {}
        v[f"calls_{s}"] = f1(calls["mean"]) if calls.get("mean") else "0"
        tin = d.get("prompt_tokens_per_incident") or {}
        tout = d.get("completion_tokens_per_incident") or {}
        v[f"tok_{s}"] = f"{tin['mean']:.0f} / {tout['mean']:.0f}" if tin.get("mean") else "–"
        runs = list(csv.DictReader(open(os.path.join(core_dir, f"eval_stage3_{s}_runs.csv"))))
        x8 = [float(r["mttr_s"]) for r in runs if r["scenario"] != "8" and r["mttr_s"]]
        allm = sorted(float(r["mttr_s"]) for r in runs if r["mttr_s"])
        v[f"mttrp90_{s}"] = f1(allm[min(len(allm) - 1, int(0.9 * len(allm)))])   # nearest rank
        v[f"mttrmax_{s}"] = f1(allm[-1])
        v[f"mttrx8_{s}"] = f1(statistics.mean(x8))
        row8 = next(r for r in by if r["system"] == s and r["scenario"] == "8")
        v[f"mttd8_{s}"] = f"{float(row8['mttd_mean_s']):.0f}"
        v[f"mttr8_{s}"] = f"{float(row8['mttr_mean_s']):.0f}"
        cpu = [float(r["mttd_mean_s"]) for r in by if r["system"] == s and r["scenario"] in ("1", "2")]
        v[f"mttdcpu_{s}"] = f"{statistics.mean(cpu):.0f}"
        r5 = next(r for r in by if r["system"] == s and r["scenario"] == "5")
        v[f"act5_{s}"] = f"{r5['executed_action_ok']}/{r5['runs']}"
    v["n_core"] = str(sum(summ[s]["runs"] for s in systems))
    v["rounds_min"] = str(min(summ[s]["runs"] for s in systems) // 9)
    v["lead8"] = f"{(float(v['mttd8_B1']) + float(v['mttd8_B2'])) / 2 - float(v['mttd8_S']):.0f}"
    v["mttd_cut"] = f"{100 * (1 - float(v['mttd_S']) / float(v['mttd_B2'])):.0f}"
    v["llm_cost"] = f"{float(v['mttrx8_B2']) - float(v['mttrx8_B1']):.0f}"
    v["unsafe_core"] = str(sum(summ[s]["unsafe_actions_executed"] for s in systems))

    ex = list(csv.DictReader(open(extra_csv)))
    cell = {}
    for r in ex:
        cell[(r["system"], r["scenario"])] = r
    v["_extra"] = cell
    v["n_extra"] = str(sum(int(r["runs"]) for r in ex))
    for sid in ("12", "13"):
        for s in systems:
            r = cell.get((s, sid))
            v[f"det{sid}_{s}"] = f"{r['detected']}/{r['runs']}" if r else "–"
    for sid in ("10", "11", "14"):
        for s in systems:
            r = cell.get((s, sid))
            v[f"esc{sid}_{s}"] = f"{r['escalated']}/{r['runs']}" if r else "–"
    sf = [r for r in ex if r["system"] == "SF"]
    v["sf_runs"] = str(sum(int(r["runs"]) for r in sf))
    v["sf_fixed"] = str(sum(int(r["auto_resolved"]) for r in sf))
    v["n_total"] = str(int(v["n_core"]) + int(v["n_extra"]))

    # Paper A: verify loop, collateral actions, extra-set outcomes
    v["llm_wrong_word"] = f"{100 - summ['B2']['executed_action_accuracy_pct']:.1f}"
    for s in systems:
        runs_s = list(csv.DictReader(open(os.path.join(core_dir, f"eval_stage3_{s}_runs.csv"))))
        v[f"att2_{s}"] = str(sum(1 for r in runs_s if r["attempts"] and int(r["attempts"]) >= 2))
        wrong = [r for r in runs_s if r["root_cause_ok"] == "False"]
        v[f"rcwrong_{s}"] = str(len(wrong))
        rep = [float(r["mttr_s"]) for r in wrong if r["auto_resolved"] == "True" and r["mttr_s"]]
        v[f"repaired_{s}"] = str(len(rep))
        if rep:
            v["rep_min"], v["rep_max"] = f"{min(rep):.0f}", f"{max(rep):.0f}"
    xsum = json.load(open(extra_summary))
    for s in systems:
        v[f"coll_{s}"] = str(xsum[s]["collateral_actions_executed"])
    tin, tout = xsum["S"]["prompt_tokens_per_incident"], xsum["S"]["completion_tokens_per_incident"]
    v["tokxin_S"], v["tokxout_S"] = f"{tin['mean']:.0f}", f"{tout['mean']:.0f}"
    cin, cout = summ["S"]["prompt_tokens_per_incident"], summ["S"]["completion_tokens_per_incident"]
    v["tokin_S"], v["tokout_S"] = f"{cin['mean']:.0f}", f"{cout['mean']:.0f}"
    v["esc1011"] = str(sum(int(cell[(s, k)]["escalated"]) for s in systems for k in ("10", "11")))
    v["esc14"] = str(sum(int(cell[(s, "14")]["escalated"]) for s in systems))
    v["res12_S"] = f"{cell[('S', '12')]['auto_resolved']} of {cell[('S', '12')]['runs']}"
    v["sf4_esc"] = cell[("SF", "4")]["escalated"]

    # live policy decisions (experiments/guard_decisions.py) and MTTR test (experiments/mttr_significance.py)
    res = os.path.dirname(extra_csv)
    guard = list(csv.DictReader(open(os.path.join(res, "guard_decisions_long_run.csv"))))
    v["_guard"] = guard
    g = {r["decision"]: r for r in guard}
    for s_ in ("B2", "S"):
        v[f"cd_{s_}"] = str(sum(int(r[s_]) for k, r in g.items() if "cooldown" in k))
    v["guard_incidents"] = str(sum(int(g["incidents in the store"][s_]) for s_ in ("B1", "B2", "S", "SF")))
    mwu = list(csv.DictReader(open(os.path.join(res, "mttr_mwu_B1_B2.csv"))))
    per = [r for r in mwu if r["scenario"] != "all except 8"]
    pooled = next(r for r in mwu if r["scenario"] == "all except 8")
    assert all(float(r["U"]) == 0 for r in per), "text assumes complete separation in every scenario"
    import math
    exp = math.floor(math.log10(max(float(r["p"]) for r in per))) + 1      # p < 10^exp
    sup = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")
    v["mwu_pmax"] = "10" + str(exp).translate(sup)
    v["hl_min"] = f"{min(float(r['hl_shift_s']) for r in per):.0f}"
    v["hl_max"] = f"{max(float(r['hl_shift_s']) for r in per):.0f}"
    v["hl_pooled"] = f"{float(pooled['hl_shift_s']):.0f}"
    return v


# ------------------------------------------------------------------ XML helpers

PROVISIONAL = False


def runs(text, values, size=None, italic=False, bold=False, highlight=False):
    """Inline markup: **bold**, *italic*, {key} (a number), [[...]] (provisional text)."""
    out = []
    for tok in re.split(r"(\[\[.+?\]\]|\*\*.+?\*\*|\*.+?\*|\{[a-zA-Z0-9_]+\})", text):
        if not tok:
            continue
        if tok.startswith("[["):
            out.append(runs(tok[2:-2], values, size, italic, bold, highlight or PROVISIONAL))
            continue
        b, i, h, t = bold, italic, highlight, tok
        if tok.startswith("**"):
            b, t = True, tok[2:-2]
        elif tok.startswith("*") and len(tok) > 1:
            i, t = True, tok[1:-1]
        elif tok.startswith("{"):
            t, h = values[tok[1:-1]], highlight or PROVISIONAL
        rpr = ("<w:b/>" if b else "") + ("<w:i/><w:iCs/>" if i else "")
        if size:
            rpr += f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
        if h:
            rpr += '<w:highlight w:val="yellow"/>'
        rpr = f"<w:rPr>{rpr}</w:rPr>" if rpr else ""
        out.append(f'<w:r>{rpr}<w:t xml:space="preserve">{escape(t)}</w:t></w:r>')
    return "".join(out)


def para(style, text="", values=None, ppr_extra="", inner=None, **kw):
    body = inner if inner is not None else runs(text, values or {}, **kw)
    return f'<w:p><w:pPr><w:pStyle w:val="{style}"/>{ppr_extra}</w:pPr>{body}</w:p>'


# explicit single spacing in cells: Pages otherwise pads each row to about two lines
CELL_SPACING = '<w:spacing w:before="0pt" w:after="0pt" w:line="240" w:lineRule="auto"/>'


def table(widths_pt, header, rows, values, caption):
    grid = "".join(f'<w:gridCol w:w="{int(w * 20)}"/>' for w in widths_pt)
    border = '<w:{0} w:val="single" w:sz="2" w:space="0" w:color="auto"/>'
    borders = "".join(border.format(b) for b in ("top", "start", "bottom", "end", "insideH", "insideV"))
    out = [para("tablehead", caption, values, ppr_extra="<w:keepNext/><w:suppressAutoHyphens/>")]
    out.append(f'<w:tbl><w:tblPr><w:tblW w:w="0pt" w:type="dxa"/><w:jc w:val="center"/>'
               f'<w:tblBorders>{borders}</w:tblBorders><w:tblLayout w:type="fixed"/>'
               f'<w:tblCellMar><w:top w:w="1pt" w:type="dxa"/><w:start w:w="2.5pt" w:type="dxa"/>'
               f'<w:bottom w:w="1pt" w:type="dxa"/><w:end w:w="2.5pt" w:type="dxa"/></w:tblCellMar>'
               f'</w:tblPr><w:tblGrid>{grid}</w:tblGrid>')

    def row(cells, style, head=False, keep=True):
        tr = '<w:tr><w:trPr><w:cantSplit/>' + ('<w:tblHeader/>' if head else "") + '<w:jc w:val="center"/></w:trPr>'
        for k, (c, w) in enumerate(zip(cells, widths_pt)):
            jc = '<w:jc w:val="start"/>' if k == 0 or not head and k == 1 and len(widths_pt) == 3 else '<w:jc w:val="center"/>'
            if style == "tablecopy" and k > 0 and len(widths_pt) != 3:
                jc = '<w:jc w:val="center"/>'
            if len(widths_pt) == 2 and k == 1:
                jc = '<w:jc w:val="start"/>'
            tr += (f'<w:tc><w:tcPr><w:tcW w:w="{w}pt" w:type="dxa"/><w:vAlign w:val="center"/></w:tcPr>'
                   f'{para(style, c, values, ppr_extra=("<w:keepNext/>" if keep else "") + "<w:suppressAutoHyphens/>" + CELL_SPACING + jc)}</w:tc>')
        return tr + "</w:tr>"

    out.append(row(header, "tablecolhead", head=True))
    for k, r in enumerate(rows):
        out.append(row(r, "tablecopy", keep=k < len(rows) - 1))
    out.append("</w:tbl>")
    return "".join(out)


# Figures sit in a frame without fill or line, as the IEEE template advises ("use a text box to
# insert a graphic"); the template's own boxed note is a frame too. Both paragraphs (picture and
# caption) carry the same framePr, so Word treats them as one frame.
FRAME = ('<w:framePr w:w="243pt" w:wrap="notBeside" w:vAnchor="text" w:hAnchor="text" '
         'w:xAlign="center"/>')
USE_FRAMES = True       # off for the Pages PDF build: Pages draws the caption above a framed figure


class Images:
    def __init__(self):
        self.items = []

    def add(self, png, values, caption):
        import struct
        with open(png, "rb") as f:
            w, h = struct.unpack(">II", f.read(24)[16:24])
        n = len(self.items) + 1
        rid = f"rIdFig{n}"
        self.items.append((rid, os.path.basename(png), png))
        cx = int(COL_WIDTH_IN * EMU)
        cy = int(cx * h / w)
        a = "http://purl.oclc.org/ooxml/drawingml/main"
        pic = "http://purl.oclc.org/ooxml/drawingml/picture"
        drawing = (
            f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
            f'<wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{100 + n}" name="Figure {n}"/>'
            f'<wp:cNvGraphicFramePr><a:graphicFrameLocks xmlns:a="{a}" noChangeAspect="1"/></wp:cNvGraphicFramePr>'
            f'<a:graphic xmlns:a="{a}"><a:graphicData uri="{pic}"><pic:pic xmlns:pic="{pic}">'
            f'<pic:nvPicPr><pic:cNvPr id="{100 + n}" name="{os.path.basename(png)}"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>'
            f'</wp:inline></w:drawing></w:r>')
        frame = FRAME if USE_FRAMES else ""
        fig = (f'<w:p><w:pPr><w:keepNext/>{frame}<w:spacing w:before="6pt" w:after="0pt"/><w:jc w:val="center"/></w:pPr>'
               f'{drawing}</w:p>')
        return fig + para("figurecaption", caption, values, ppr_extra=frame)


def author_para(name, email, flag, values, sect="", last=False):
    hl = flag and PROVISIONAL or flag

    def r(t, italic=False, br=True, size=18):
        rpr = ("<w:i/>" if italic else "") + f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
        rpr += '<w:highlight w:val="yellow"/>' if hl else ""
        return (f'<w:r><w:rPr>{rpr}</w:rPr><w:t xml:space="preserve">{escape(t)}</w:t></w:r>'
                + (f'<w:r><w:rPr>{rpr}</w:rPr><w:br/></w:r>' if br else ""))
    inner = (r(name, size=22) + r(DEPT, italic=True) + r(ORG, italic=True) + r(CITY)
             + r(email, br=False, size=16))
    # the guide's row follows a section break that already adds a line, so no space before it
    before, after = ("0pt", "12pt") if last else ("6pt", "0pt")
    return (f'<w:p><w:pPr><w:pStyle w:val="Author"/><w:suppressAutoHyphens/><w:spacing w:before="{before}" w:after="{after}"/>'
            f'{sect}</w:pPr>{inner}</w:p>')


# ------------------------------------------------------------------ content

class Cites:
    """[@key] or [@a,@b] in the text -> IEEE numbers in order of first citation."""

    def __init__(self):
        self.order = []

    def __call__(self, text):
        def num(m):
            out = []
            for key in m.group(1).split(","):
                key = key.strip().lstrip("@")
                if key not in self.order:
                    self.order.append(key)
                out.append(f"[{self.order.index(key) + 1}]")
            return ", ".join(out)
        return re.sub(r"\[(@[a-z0-9]+(?:,\s*@[a-z0-9]+)*)\]", num, text)


def content(v, img):
    cite = Cites()
    P = lambda t: para("BodyText", cite(t), v)
    H1 = lambda t: para("Heading1", t, v)
    H2 = lambda t: para("Heading2", t, v)
    out = []

    # The template forbids symbols and math in the abstract: no %, no ~.
    out.append(para("Abstract", "", v, ppr_extra='<w:spacing w:before="10pt"/>', inner=runs("*Abstract*—", v) + runs(
        "Large language models (LLMs) can read monitoring data and propose fixes for failing "
        "services, but executing their output on a live system is risky, because a plan can name "
        "the wrong service, invent an action or be malformed. This paper presents a closed-loop "
        "incident response system for microservices in which a locally hosted LLM only recommends "
        "actions and a deterministic policy validator alone decides what may run. The validator "
        "restricts actions to an allowlist and known targets, enforces a confidence threshold, a "
        "cooldown and a per-incident action limit, and sends destructive actions to a human for "
        "approval. Every executed fix is verified and re-analyzed at most three times before the "
        "incident is escalated. On a three-service containerized application we compare rule-based "
        "runbooks, the LLM and the full system over {n_total} fault-injection runs covering 14 "
        "scenarios, and test the validator with 29 adversarial plans. No unsafe action was executed "
        "in any run or adversarial case. On faults covered by runbooks, the LLM identified the same "
        "root causes but chose a less suitable action in {llm_wrong_word} percent of runs and added "
        "about {llm_cost} seconds to recovery. On misleading faults it blamed the symptomatic "
        "service, and the policy layer bounded the response and escalated. The results favor "
        "runbooks for known faults, the LLM where no runbook applies, and the same guard for both.",
        v)))
    out.append(para("Keywords", "Keywords—incident response, large language models, AIOps, "
                    "automated remediation, safety, microservices", v))

    # I
    out.append(H1("Introduction"))
    out.append(P(
        "Modern web applications are built from many small services, and a fault in one of them "
        "spreads to the others. When a database slows down, the service that calls it shows high "
        "latency and the front end returns errors, so the alert that fires first is often not the "
        "cause. Incidents are still handled by an on-call engineer who receives an alert, studies "
        "dashboards, consults a written runbook and applies a fix such as a restart or a rollback "
        "[@sre]. Detection tools are mature and simple fixes are routinely scripted, but the step in "
        "between, deciding what is wrong and which fix is safe, remains manual and slow."))
    out.append(P(
        "AIOps (artificial intelligence for IT operations) applies machine learning to operational data to detect anomalies and group alerts "
        "[@dang], and recent studies show that large language models (LLMs) can propose root causes "
        "and mitigation steps for cloud incidents [@ahmed, @rcacopilot]. Open-source assistants "
        "such as k8sgpt [@k8sgpt] and HolmesGPT [@holmes] explain cluster problems in natural "
        "language. These tools mostly recommend; when they are allowed to act, the safety of the "
        "action rests on the model output being correct. An LLM can name a service that does not "
        "exist, invent an action, return a confidence that is not a number, or repeat a fix that "
        "has already failed. Executing such output directly can turn a small incident into an "
        "outage."))
    out.append(P(
        "This paper asks whether the remediation step can be handed to an LLM if the model is "
        "treated as an untrusted advisor inside a closed control loop. The LLM recommends a plan, a "
        "separate policy validator that does not trust the plan decides whether it may run, every "
        "fix is verified, and the loop stops after a bounded number of attempts and hands the "
        "incident to a human. We study three questions. RQ1 (safety): can such a loop run on live "
        "containers without an unsafe action, even when plans are malformed or malicious? RQ2 "
        "(value): given the same detection, does the LLM diagnose and act better than rule-based "
        "runbooks? RQ3 (robustness): what happens when the diagnosis is wrong, the fault is outside "
        "the runbooks or keeps returning, or the LLM is unavailable? The contributions are:"))
    for t in [
        "1) A closed-loop architecture (monitor, detect, analyze, decide, respond, verify) in which "
        "the LLM has no access to the system and a policy validator, the only path to execution, "
        "enforces an action allowlist, known targets, a confidence threshold, a cross-incident "
        "cooldown, per-incident limits, human approval for destructive actions and bounded "
        "re-analysis followed by escalation.",
        "2) An adversarial suite of 29 hallucinated, malformed and malicious plans run against the "
        "real responder, which exposed four input-handling defects in the responder and the gateway, "
        "fixed before the evaluation.",
        "3) An evaluation on real containers with {n_total} fault-injection runs over 14 scenarios, "
        "including misleading, below-threshold and recurring faults, and four system variants, "
        "among them one in which the LLM is unavailable.",
        "4) A comparison of the LLM with runbooks under the same guard, showing where the "
        "LLM falls short and what the guard contributes."]:
        out.append(P(t))
    out.append(P(
        "The system runs on a single laptop with a locally hosted 8-billion-parameter model, so "
        "operational data never leave the machine and no cloud inference is needed. A small local model "
        "also keeps the compute and energy cost of automated operations low, in line with the "
        "sustainability theme of this conference. Section II reviews related work, "
        "Section III describes the architecture and Section IV the safety design. Sections V and VI "
        "present the evaluation, Section VII discusses limitations and Section VIII concludes."))

    # II
    out.append(H1("Related Work"))
    out.append(P(
        "*AIOps and root-cause localization.* Machine learning on metrics, logs and traces is used "
        "to detect anomalies, correlate alerts and localize faults [@dang]. In microservices a fault "
        "in one service produces symptoms in its callers; MicroRCA [@microrca] ranks candidate "
        "causes on a graph of services and hosts. We use a simpler signal: each service records the "
        "time it waits for its downstream service, which both the runbooks and the LLM receive."))
    out.append(P(
        "*LLMs for incident management.* Ahmed et al. [@ahmed] showed that fine-tuned LLMs can "
        "recommend root causes and mitigation steps for production cloud incidents, and RCACopilot "
        "[@rcacopilot] combines collected diagnostic data with an LLM to predict root-cause "
        "categories. AIOpsLab [@aiopslab] provides an environment in which LLM agents detect, "
        "diagnose and mitigate injected faults, and measures how often they succeed. These works "
        "evaluate the quality of the diagnosis or the success of the agent; they do not study how "
        "to bound the damage when a wrong recommendation is executed."))
    out.append(P(
        "*Guarding LLM output.* Guardrail toolkits such as NeMo Guardrails [@nemo] constrain what a "
        "conversational model may say or which tools it may call. Remediation needs checks that "
        "depend on the state of the system: whether the same action ran minutes ago, how many "
        "actions an incident has already used, and whether the alert is still active. Site "
        "reliability practice [@sre] encodes such rules in runbooks, graded escalation and review, "
        "and chaos engineering [@basiri] injects faults to test them. We turn these rules into a "
        "validator that every action must pass, test it with adversarial plans, and evaluate the "
        "whole loop end to end on real containers."))

    # III
    out.append(H1("System Architecture"))
    out.append(P(
        "The proposed system is organized as a closed control loop, illustrated in Fig. 1. "
        "Monitoring data flow through detection, the event "
        "gateway, analysis and the policy validator to the executor; the verifier closes the loop "
        "by sending unresolved incidents back for re-analysis."))
    out.append(img.add(os.path.join(FIGS, "fig1_architecture.png"), v,
                       "Architecture of the proposed system. Blue: monitoring and gateway; orange: "
                       "analysis; green: guarded execution and verification."))
    out.append(H2("Monitored Application and Detection"))
    out.append(P(
        "The target is a three-tier web application: a frontend service calls an api-service, "
        "which reads and increments a counter in Redis. Both Python services expose request "
        "counts, latency histograms and an upstream-latency histogram; container CPU and memory "
        "come from cAdvisor, and Prometheus [@prometheus] scrapes all targets every 5 s. Prometheus "
        "alert rules for high CPU, memory, latency, error rate and service unavailability use 30 s "
        "windows with a 20 s hold. A per-service anomaly detector, robust z-scores [@mad] and an "
        "Isolation Forest [@iforest] trained on fault-free traffic, adds early signals for faults "
        "that grow slowly or stay below the thresholds. Each service also has a fault-injection "
        "endpoint for the evaluation; its fault-state gauges are removed from every input of the "
        "system and used only for scoring."))
    out.append(H2("Event Gateway"))
    out.append(P(
        "Alerts arrive from Alertmanager by webhook and anomalies from the detector. Signals within "
        "60 s on services of the same call chain form one incident, so a Redis failure and the "
        "resulting API and frontend alerts are handled together. After a 10 s settle period the "
        "gateway builds the incident context: for each service the current values and ten-minute "
        "trends of CPU, memory, latency, error rate and upstream latency, the container status, the "
        "topology and the actions already tried. The incident is broadcast over a WebSocket and "
        "stored in SQLite."))
    out.append(H2("Analyzer"))
    out.append(P(
        "The analyzer turns each incident into a response plan: root-cause service, incident type, "
        "severity, evidence, confidence, a recommended and a fallback action, and an explanation. "
        "It prompts Llama 3.1 8B [@llama], served locally by Ollama at temperature 0, with a system "
        "prompt, few-shot examples and the incident, and constrains the answer with a JSON schema. "
        "The answer is then validated with strict types; a confidence given as text or as a Boolean, "
        "for example, is rejected. If the model is unreachable, times out, returns invalid output or "
        "reports a confidence below 0.7, the analyzer falls back to YAML runbooks, deterministic "
        "rules that map alert and anomaly patterns to a plan. The analyzer only recommends; it has "
        "no access to the containers."))
    out.append(H2("Responder and Verifier"))
    out.append(P(
        "The responder is the only component that executes actions. For each plan it re-checks "
        "that the incident is still active, passes the plan to the policy validator, executes the "
        "permitted action through the service's reset endpoint or the Docker API, and after 45 s "
        "checks whether the alerts have cleared and no anomaly is still active. If the incident "
        "persists it asks the gateway to re-analyze it with the attempt number and the actions "
        "already tried; after the third attempt it escalates to a human. Every outcome is reported "
        "back to the gateway, so the dashboard and the store show the full timeline."))

    # IV
    out.append(H1("Safety Design"))
    out.append(P(
        "The analyzer output is treated as untrusted input: any client can post a plan to the "
        "gateway, and the responder does not rely on the analyzer's schema. The policy validator "
        "applies the checks in Table I to the recommended action and then to the fallback action; "
        "the first that passes is used, otherwise the incident is escalated. We call an action "
        "unsafe if it is outside the allowlist, targets a component not permitted for it, or runs "
        "without a required approval."))
    out.append(table([52, 124, 66], ["Check", "Rule", "On failure"], [
        ["Allowlist", "reset faults, restart container, flush cache, update resources, escalate", "fallback, then escalate"],
        ["Target", "known service allowed for the action (no reset on Redis)", "fallback, then escalate"],
        ["Confidence", "a number in [0, 1] and at least 0.7", "human approval"],
        ["Risk", "flush cache, update resources", "human approval"],
        ["Cooldown", "same action and target not within 300 s, across incidents", "fallback, then escalate"],
        ["Action limit", "at most 3 executed actions per incident", "escalate"],
        ["Attempts", "at most 3 analyze, act and verify cycles", "escalate"],
    ], v, "Policy Checks Applied to Every Plan"))
    out.append(P(
        "This gives three levels of autonomy: safe and reversible actions run automatically, "
        "destructive or uncertain ones wait in an approval queue, and everything else goes to a "
        "human together with the incident context and the actions already tried. The executor "
        "implements exactly the allowlisted actions, so there is no path from model text to a "
        "shell command. A pre-check prevents acting on alerts that cleared while the plan was "
        "being produced, and the cooldown stops restart loops when a fault keeps returning."))
    out.append(P(
        "To test this layer we built an adversarial suite of 29 plans that pass through the real "
        "responder with a recording executor: invented action types, shell text in fields, targets "
        "outside the application, wrong types (lists, null, Booleans), confidences that are "
        "missing, NaN, infinite or out of range, extra command fields, a valid action in cooldown "
        "with a malicious fallback, and exhausted action limits. Five of these plans would have "
        "passed the analyzer's own output schema, so only the responder's checks stop them. "
        "Table II groups the cases; its last column counts those the analyzer's output schema "
        "would already reject. Building the suite exposed four input-handling defects in the "
        "responder and the gateway, which were then fixed; for instance, a NaN "
        "confidence passed the threshold test because NaN < 0.7 is false, and a Boolean true was "
        "read as a confidence of 1.0. After the fixes all 29 cases behave as specified: the "
        "control case runs, and every adversarial plan is blocked, reduced to its safe part or "
        "sent to a human."))

    out.append(table([100, 32, 62, 48], ["Adversarial case", "Cases", "Outcome", "Schema rejects"], [
        ["Invented or malformed action type", "5", "blocked", "5"],
        ["Target outside the allowed set", "7", "blocked", "7"],
        ["Missing, NaN, infinite, Boolean, text or >1 confidence", "6", "human approval", "6"],
        ["Low confidence", "1", "human approval", "0"],
        ["Destructive action", "2", "human approval", "0"],
        ["Extra command field", "1", "field ignored", "1"],
        ["Repeat in cooldown, malicious fallback", "1", "blocked", "1"],
        ["Action limit reached", "1", "blocked", "0"],
        ["Malformed incident fields or empty plan", "4", "blocked", "3"],
        ["Control: valid plan", "1", "executed", "–"],
    ], v, "Adversarial Plan Suite"))

    # V
    out.append(H1("Evaluation Setup"))
    out.append(H2("Testbed and Fault Scenarios"))
    out.append(P(
        "All experiments run on one laptop (Apple M4, 10 cores, 16 GB) with Docker Desktop; the LLM "
        "runs on the host. A Locust load generator sends about five requests per second. A fault "
        "injector starts each fault, logs its start and planned end, and polls the target until the "
        "fault is gone. A run counts as remediated if the fault disappears before its planned end, "
        "which only happens if the system fixed it. Table III lists the scenarios. Scenarios 1 to 9 "
        "form the core set, faults the runbooks were written for, lasting 180 s (300 s for the "
        "leak). Scenarios 10 to 14 form an extra set of misleading, below-threshold and recurring "
        "faults lasting 300 s (480 s for scenario 14)."))
    out.append(table([14, 107, 14, 107], ["#", "Fault (expected action)", "#", "Fault (expected action)"], [
        ["1", "CPU load, frontend (reset or restart)", "8", "Memory leak, 440 MB over 240 s (restart)"],
        ["2", "CPU load, API (reset or restart)", "9", "CPU and latency, API (reset)"],
        ["3", "Memory 420 MB, API (restart)", "10", "Corrupted cache value (flush, approval)"],
        ["4", "Latency 5 s, API (reset)", "11", "Slow Redis writes (restart Redis)"],
        ["5", "All requests fail, API (reset)", "12", "Latency 0.6 s, API (reset)"],
        ["6", "Redis stopped (restart Redis)", "13", "5% of requests fail, API (reset)"],
        ["7", "Frontend stopped (restart)", "14", "Latency that returns after every fix (escalate)"],
    ], v, "Fault Scenarios"))
    out.append(H2("Systems Compared"))
    out.append(P(
        "*B1*: alert rules and runbooks, without the LLM or the anomaly detector. *B2*: alert rules "
        "and the LLM with runbook fallback, without the anomaly detector. B1 and B2 receive the same "
        "signals, so their difference isolates the analysis step. *S*: the full system. *SF*: the "
        "full system with the LLM unreachable, run on scenarios 3, 4, 6 and 8 to test graceful "
        "degradation. All variants share the same responder and policies."))
    out.append(H2("Protocol and Metrics"))
    out.append(P(
        "Each round runs every scenario once per system in a shuffled order fixed by a seed, with "
        "rounds interleaved across systems, and consecutive runs are 300 s apart so the cooldown "
        "never carries over. The core set ran for {rounds_min} rounds ({n_B1} runs per system) and "
        "the extra set for 10 rounds, {n_extra} runs in all; a run the laptop slept through was "
        "voided and repeated. We report root-cause accuracy of the first plan; action correctness "
        "against the expected action; unsafe actions; collateral actions, permitted actions on a "
        "service that was not the cause; the auto-resolution rate; the mean time to recover (MTTR, "
        "fault start to fault gone, for remediated runs); the share of runs needing a second "
        "attempt; the escalation rate; and the LLM cost as plan latency and tokens per incident."))

    # VI
    out.append(H1("Results"))
    out.append(H2("Safety (RQ1)"))
    out.append(P(
        "No unsafe action was executed in any of the {n_total} runs of the four variants, and no "
        "run opened a false incident. Safety did not come for free: on the misleading faults of the "
        "extra set the variants executed {coll_B1}, {coll_B2} and {coll_S} collateral actions (B1, "
        "B2, S), resets and restarts of a healthy service that the policy permits. The cooldown and "
        "the action limit capped these at three per incident. No plan in the live runs proposed a "
        "destructive action, so the approval path was exercised only by the adversarial suite."))
    out.append(P(
        "To see how the policy behaved in practice, we counted its decisions in the "
        "{guard_incidents} incidents recorded by the incident store (core rounds 5 to 20, extra "
        "rounds 2 to 10); Table IV lists them. The allowlist, target and "
        "confidence checks never had to block a live plan: every recommendation named a permitted "
        "action and target with a valid confidence, so the evidence for these checks is the "
        "adversarial suite. The guard intervened through the cooldown. On the extra set the LLM "
        "variants recommended {cd_B2} (B2) and {cd_S} (S) times to repeat a reset or restart that had "
        "just failed; each time the cooldown blocked it, and the responder ran the fallback action "
        "or escalated. The runbooks never did this, because their plans for unmatched incidents "
        "escalate directly."))
    out.append(table([102, 35, 35, 35, 35], ["Decision", "B1", "B2", "S", "SF"], guard_rows(v), v,
                     "Live Policy Decisions (Core Rounds 5 to 20, Extra Rounds 2 to 10)"))
    out.append(H2("LLM Versus Runbooks (RQ2)"))
    out.append(P(
        "On the core scenarios, summarized in Table V, every variant detected every fault. B1 and B2 found the "
        "root cause in every run, but the executed action was correct in {act_B1} of runs for B1 and "
        "{act_B2} for B2. All of B2's wrong actions were on scenario 5 ({act5_B2} correct), where the "
        "LLM named the right service but restarted it instead of resetting its fault; the restart "
        "also removed the fault, so the error cost time rather than safety."))
    out.append(table([96, 49, 49, 48], ["Metric", "B1", "B2", "S"], [
        ["Runs", "{n_B1}", "{n_B2}", "{n_S}"],
        ["Detected", "{recall_B1}", "{recall_B2}", "{recall_S}"],
        ["Root cause correct", "{rc_B1}", "{rc_B2}", "{rc_S}"],
        ["Executed action correct", "{act_B1}", "{act_B2}", "{act_S}"],
        ["Unsafe actions executed", "{unsafe_B1}", "{unsafe_B2}", "{unsafe_S}"],
        ["Auto-resolved", "{auto_B1}", "{auto_B2}", "{auto_S}"],
        ["MTTR mean (s)", "{mttr_B1}", "{mttr_B2}", "{mttr_S}"],
        ["MTTR without scenario 8 (s)", "{mttrx8_B1}", "{mttrx8_B2}", "{mttrx8_S}"],
        ["MTTR 90th percentile (s)", "{mttrp90_B1}", "{mttrp90_B2}", "{mttrp90_S}"],
        ["MTTR worst run (s)", "{mttrmax_B1}", "{mttrmax_B2}", "{mttrmax_S}"],
        ["Runs needing a 2nd attempt", "{att2_B1}", "{att2_B2}", "{att2_S}"],
        ["Escalated", "{esc_B1}", "{esc_B2}", "{esc_S}"],
        ["Plan latency mean (s)", "{lat_B1}", "{lat_B2}", "{lat_S}"],
        ["Tokens per incident (in / out)", "{tok_B1}", "{tok_B2}", "{tok_S}"],
    ], v, "Results on the Core Scenarios"))
    out.append(P(
        "The LLM was also slower: a runbook plan takes milliseconds, while the LLM needed "
        "{lat_B2} s per plan on this laptop. Fig. 2 illustrates the effect on recovery: it plots "
        "the mean time to recover of B1, B2 and S in each of the nine core scenarios, and the B2 "
        "bar is above the B1 bar in every one. Without scenario 8, mean MTTR was {mttrx8_B1} s for "
        "B1 and {mttrx8_B2} s for B2, about {llm_cost} s more per incident. The gap is systematic: in each of the nine core "
        "scenarios every B2 run took longer than every B1 run (Mann-Whitney U = 0, p < {mwu_pmax} "
        "per scenario), with a median shift of {hl_min} to {hl_max} s (Hodges-Lehmann; {hl_pooled} s "
        "over scenarios 1 to 7 and 9). On faults the runbooks were written for, the runbooks were "
        "therefore both more accurate and faster."))
    out.append(img.add(os.path.join(FIGS, "fig2_mttr.png"), v,
                       "Mean time to recover per core scenario (20 runs per bar)."))
    out.append(P(
        "S reached the lowest mean MTTR ({mttr_S} s) only because of scenario 8, a gradual memory "
        "leak that its anomaly detector reports long before the memory alert fires ({mttr8_S} s "
        "against {mttr8_B2} s for B2). That gain comes from detection, not from the analysis step; "
        "without scenario 8, S ({mttrx8_S} s) lies between B1 and B2. S also had the most "
        "predictable recovery: 90 percent of its runs recovered within {mttrp90_S} s and its "
        "slowest run took {mttrmax_S} s, against {mttrp90_B1} s and {mttrmax_B1} s for B1, because "
        "no fault in S waited for a slow alert before the loop could act."))
    out.append(H2("Wrong Diagnoses and the Verify Loop (RQ3)"))
    out.append(P(
        "S named the wrong root cause in {rcwrong_S} of {n_S} first plans. Its incidents often open "
        "on an early anomaly, before the alerts show the full picture, so the first plan works "
        "with less evidence; this is the price of acting earlier. The verify loop "
        "repaired {repaired_S} of these: in scenario 6 the first plan blamed the api-service for the "
        "Redis failure, and in scenario 4 the frontend for the API latency. The fix did not clear the "
        "fault, the verifier sent the incident back with the failed action in its history, and the "
        "second plan acted on the right service. These runs recovered in {rep_min} to {rep_max} s "
        "instead of about 70 s, without harm. In the remaining run an early runbook plan escalated "
        "the incident seconds before a correct LLM plan arrived, which the responder then ignored. "
        "In all, {att2_S} S runs needed a second attempt; B1 and B2 never did."))
    out.append(P(
        "To illustrate the verify loop, Table VI traces one of the repaired runs. The first plan blamed the api-service although "
        "its own evidence listed Redis as down. A restart of a known service is permitted, so the "
        "validator let it run; the guard is not meant to judge the diagnosis. A corrected plan "
        "arrived five seconds later and was ignored, because the responder acts on one plan per "
        "attempt. The verifier found the alerts still firing and asked for a second analysis with "
        "the failed restart in the history, and the second plan restarted Redis."))
    # run 1ffdf0ca, incident inc-261020-082452-155; times from the incident store (RESULTS.md 20)
    out.append(table([30, 212], ["t (s)", "Event (scenario 6, Redis stopped; system S)"], [
        ["0", "Redis container stopped"],
        ["17", "Anomaly on frontend errors: first detection"],
        ["27", "Incident opened after the 10 s settle; RedisDown alert joins at 41 s"],
        ["52", "Plan 1 (LLM): root cause api-service, restart api-service, confidence 0.95"],
        ["62", "Validator: all checks pass; api-service restarted"],
        ["67", "Plan for the updated incident (restart Redis) ignored: attempt 1 is acting"],
        ["108", "Verifier: still firing; re-analysis with the failed restart in the history"],
        ["122", "Plan 2 (LLM): root cause Redis, restart Redis; executed"],
        ["124", "Fault gone (time to recover)"],
        ["167", "Verifier: alerts cleared, no anomaly; incident resolved"],
    ], v, "Timeline of One Repaired Misdiagnosis (Times from Fault Start)"))
    out.append(H2("Faults Outside the Runbooks (RQ3)"))
    out.append(P(
        "The results for the extra set are summarized in Table VII. In the misleading Redis faults (10 and 11) Redis stays up "
        "while the api-service shows the errors or latency. Every variant, the LLM included, blamed "
        "the api-service (one S run blamed the frontend); no plan proposed flushing the cache or restarting Redis. The cooldown, "
        "fallback and action limit bounded the response, and all {esc1011} of these runs were "
        "escalated to a human with the actions already tried. The recurring fault (14) was escalated "
        "in all {esc14} runs after the reset and the restart failed, as intended. The "
        "below-threshold faults (12 and 13) fired no alert, so B1 and B2 never responded; through its "
        "anomaly detector S detected scenario 12 in {det12_S} and scenario 13 in {det13_S} runs, and "
        "resolved scenario 12 in {res12_S} runs. In scenario "
        "13 the intermittent anomaly was older than the responder's freshness window when four LLM "
        "plans arrived, and the pre-check skipped them as already cleared; the fifth detected run "
        "was escalated by a runbook plan."))
    out.append(table([92, 50, 50, 50], ["Scenario", "B1", "B2", "S"], extra_rows(v), v,
                     "Extra Scenarios: Detected / Resolved / Escalated Runs of 10"))
    out.append(H2("LLM Unavailable (RQ3)"))
    out.append(P(
        "With the LLM unreachable, SF fell back to the runbooks and resolved {sf_fixed} of "
        "{sf_runs} runs, the memory, Redis and leak faults in every run and faster than S, since no "
        "LLM call was made. In {sf4_esc} of 10 latency runs (scenario 4) the incident opened on an "
        "anomaly before the latency alert fired, no runbook matched an anomaly-only latency "
        "incident, and the fallback plan escalated it early."))
    out.append(H2("Cost"))
    out.append(P(
        "An incident in S used {calls_S} LLM calls on average, with about {tokin_S} prompt and "
        "{tokout_S} completion tokens on the core set and {tokxin_S} and {tokxout_S} on the extra "
        "set, where incidents went through more attempts. With a local model this costs time rather than money: about {lat_S} s per plan."))

    # VII
    out.append(H1("Discussion and Limitations"))
    out.append(P(
        "*What the guard contributes.* The LLM's mistakes were of the kinds the guard was built "
        "for: a weaker action on a known fault, the symptom service blamed on a misleading fault, "
        "and a failed action recommended again on re-analysis ({cd_S} times in S) although the "
        "incident history listed it. In "
        "each case the outcome was bounded by the policy layer and the verify loop, not by the "
        "model. Safety therefore did not depend on the quality of the model, which matters because "
        "an operator cannot verify each recommendation of a model in advance."))
    out.append(P(
        "*Where the LLM helps.* On known faults it added latency and no accuracy; on the misleading "
        "faults it failed like the runbooks. Its value in this design is coverage of situations "
        "without a matching runbook and a readable explanation for the operator. Our scenarios "
        "test that coverage only partly, so a deployment should let runbooks handle known patterns, "
        "call the LLM only when no runbook applies, and keep the same guard for both."))
    out.append(P(
        "*Interaction effects.* Combining sources creates races: an early plan for a partial signal "
        "can pre-empt a better one, and a fault that is detected late can be skipped by the "
        "pre-check. Both argue for treating plans from incomplete evidence as provisional."))
    out.append(P(
        "*Validity.* Faults are injected through an endpoint, so the reset action stands in for "
        "real-world rollbacks or feature-flag switches. The testbed is one laptop with three "
        "services, synthetic load and one 8-billion-parameter model; a larger model may diagnose "
        "the misleading faults better. A manual baseline in which an engineer handles the same "
        "faults is needed to quantify the time saved against current practice. Future work includes "
        "error logs and deployment events in the incident context, rollback as an action, a memory "
        "of past incidents, and larger Kubernetes deployments."))

    # VIII
    out.append(H1("Conclusion"))
    out.append(P(
        "We presented a closed-loop incident response system in which a policy layer, not the LLM, "
        "decides what runs. On real containers no unsafe action was executed in {n_total} runs or 29 "
        "adversarial plans, the verify loop repaired wrong first diagnoses, and misleading or "
        "recurring faults were escalated after a bounded number of attempts. The LLM matched the "
        "runbooks on diagnosis but not on action choice or speed. Bounded, verified automation with "
        "graded human approval lets operators use LLMs where runbooks end, without trusting them."))

    # References (the style numbers them), in order of first citation
    out.append(para("Heading5", "References", v, ppr_extra="<w:keepNext/>"))
    missing = set(cite.order) - set(REFERENCES)
    assert not missing, f"no reference entry for {missing}"
    for key in cite.order:
        out.append(para("references", REFERENCES[key], v, ppr_extra='<w:suppressAutoHyphens/><w:ind w:start="17.70pt" w:hanging="17.70pt"/><w:jc w:val="start"/>'))
    return out


def guard_rows(v):
    labels = {
        "incidents in the store": "Incidents",
        "recommended action executed": "Recommended action executed",
        "fallback executed (recommended action in cooldown)": "Fallback executed (cooldown)",
        "escalated: recommended and fallback blocked by cooldown": "Escalated: both in cooldown",
        "escalated: recommended action in cooldown, fallback is escalate": "Escalated: cooldown, fallback escalate",
        "escalated by the plan itself": "Escalated by the plan",
        "escalated after 3 attempts": "Escalated after 3 attempts",
        "skipped by the pre-check (already cleared)": "Skipped by the pre-check",
        "blocked by allowlist, target or confidence, or sent for approval": "Blocked by allowlist, target or confidence",
    }
    return [[labels[r["decision"]], r["B1"], r["B2"], r["S"], r["SF"]] for r in v["_guard"]]


def extra_rows(v):
    names = {"10": "10 Corrupted cache", "11": "11 Slow Redis", "12": "12 Latency 0.6 s",
             "13": "13 5% errors", "14": "14 Recurring latency"}
    rows = []
    for sid, label in names.items():
        row = [label]
        for s in ("B1", "B2", "S"):
            r = v["_extra"].get((s, sid))
            row.append("{x_%s_%s}" % (s, sid) if r else "–")
            if r:
                v[f"x_{s}_{sid}"] = f"{r['detected']} / {r['auto_resolved']} / {r['escalated']}"
        rows.append(row)
    return rows


# Verify every entry (venue, year, pages) before submission.
REFERENCES = {
    "sre": "B. Beyer, C. Jones, J. Petoff, and N. R. Murphy, Eds., *Site Reliability Engineering: How Google Runs Production Systems*. Sebastopol, CA, USA: O’Reilly Media, 2016.",
    "dang": "Y. Dang, Q. Lin, and P. Huang, “AIOps: Real-world challenges and research innovations,” in *Proc. IEEE/ACM Int. Conf. Software Engineering: Companion (ICSE-Companion)*, 2019.",
    "ahmed": "T. Ahmed, S. Ghosh, C. Bansal, T. Zimmermann, X. Zhang, and S. Rajmohan, “Recommending root-cause and mitigation steps for cloud incidents using large language models,” in *Proc. IEEE/ACM Int. Conf. Software Engineering (ICSE)*, 2023.",
    "rcacopilot": "Y. Chen et al., “Automatic root cause analysis via large language models for cloud incidents,” in *Proc. European Conf. Computer Systems (EuroSys)*, 2024.",
    "k8sgpt": "k8sgpt-ai, “k8sgpt: Giving Kubernetes superpowers to everyone,” GitHub repository. Accessed: Oct. 26, 2026. [Online]. Available: https://github.com/k8sgpt-ai/k8sgpt",
    "holmes": "Robusta, “HolmesGPT,” GitHub repository. Accessed: Oct. 26, 2026. [Online]. Available: https://github.com/robusta-dev/holmesgpt",
    "microrca": "L. Wu, J. Tordsson, E. Elmroth, and O. Kao, “MicroRCA: Root cause localization of performance issues in microservices,” in *Proc. IEEE/IFIP Network Operations and Management Symp. (NOMS)*, 2020.",
    "aiopslab": "Y. Chen et al., “AIOpsLab: A holistic framework to evaluate AI agents for enabling autonomous clouds,” 2025, arXiv:2501.06706. [Online]. Available: https://arxiv.org/abs/2501.06706",
    "nemo": "T. Rebedea, R. Dinu, M. Sreedhar, C. Parisien, and J. Cohen, “NeMo Guardrails: A toolkit for controllable and safe LLM applications with programmable rails,” in *Proc. Conf. Empirical Methods in Natural Language Processing: System Demonstrations (EMNLP)*, 2023.",
    "basiri": "A. Basiri et al., “Chaos engineering,” *IEEE Software*, vol. 33, no. 3, pp. 35–41, 2016.",
    "prometheus": "Prometheus Authors, “Prometheus documentation.” Accessed: Oct. 26, 2026. [Online]. Available: https://prometheus.io/docs/",
    "mad": "P. J. Rousseeuw and C. Croux, “Alternatives to the median absolute deviation,” *J. American Statistical Association*, vol. 88, no. 424, pp. 1273–1283, 1993.",
    "iforest": "F. T. Liu, K. M. Ting, and Z.-H. Zhou, “Isolation forest,” in *Proc. IEEE Int. Conf. Data Mining (ICDM)*, 2008, pp. 413–422.",
    "llama": "A. Grattafiori et al., “The Llama 3 herd of models,” 2024, arXiv:2407.21783. [Online]. Available: https://arxiv.org/abs/2407.21783",
}


# ------------------------------------------------------------------ assembly

def to_text(xml):
    """Plain-text rendering of the body XML, numbered the way the template's styles number it."""
    import html
    import textwrap
    roman = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]
    n = {"h1": 0, "h2": 0, "tab": 0, "fig": 0, "ref": 0}
    out = []

    def text_of(p):
        p = re.sub(r"<w:br/>", "\n", p)
        return html.unescape("".join(re.findall(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", p.replace("\n", "<w:t>\n</w:t>"), re.S)))

    for m in re.finditer(r"<w:tbl>.*?</w:tbl>|<w:p>.*?</w:p>", xml, re.S):
        el = m.group(0)
        if el.startswith("<w:tbl>"):
            for tr in re.findall(r"<w:tr>.*?</w:tr>", el, re.S):
                out.append("  " + " | ".join(text_of(tc) for tc in re.findall(r"<w:tc>.*?</w:tc>", tr, re.S)))
            out.append("")
            continue
        style = (re.findall(r'<w:pStyle w:val="([^"]+)"', el) or [""])[0]
        t = text_of(el).strip()
        if style == "Heading1":
            n["h1"] += 1
            n["h2"] = 0
            out += ["", f"{roman[n['h1'] - 1]}. {t.upper()}", ""]
        elif style == "Heading2":
            n["h2"] += 1
            out += [f"{chr(64 + n['h2'])}. {t}", ""]
        elif style == "Heading5":
            out += ["", t.upper(), ""]
        elif style == "tablehead":
            n["tab"] += 1
            out += [f"TABLE {roman[n['tab'] - 1]}. {t.upper()}"]
        elif style == "figurecaption":
            n["fig"] += 1
            out += [f"[Figure {n['fig']} appears here in the PDF]", f"Fig. {n['fig']}. {t}", ""]
        elif style == "references":
            n["ref"] += 1
            out += textwrap.wrap(f"[{n['ref']}] {t}", 100, subsequent_indent="     ")
        elif style == "Author":
            out += [t, ""]
        elif t:
            out += textwrap.wrap(t, 100) + [""]
    return "\n".join(out).replace("\n\n\n", "\n\n") + "\n"


def literal_numbers(xml):
    """Writes heading, caption and reference numbers into the text and switches off the styles'
    automatic numbering. For PDF export with apps (e.g. Pages) that ignore Word list numbering;
    the submission .docx keeps the template's own numbering."""
    roman = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]
    n = {"Heading1": 0, "Heading2": 0, "tablehead": 0, "figurecaption": 0, "references": 0}
    nonum = '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="0"/></w:numPr>'

    def label(style):
        n[style] += 1
        if style == "Heading1":
            n["Heading2"] = 0
            return f"{roman[n[style] - 1]}. "
        if style == "Heading2":
            return f"{chr(64 + n[style])}. "
        if style == "tablehead":
            return f"TABLE {roman[n[style] - 1]}"
        if style == "figurecaption":
            return f"Fig. {n[style]}. "
        return f"[{n[style]}]\t"

    def fix(m):
        p = m.group(0)
        style = re.search(r'<w:pStyle w:val="([^"]+)"/>', p)
        if not style or style.group(1) not in n:
            return p
        st = style.group(1)
        # numPr goes after pStyle/keepNext/keepLines (OOXML element order)
        p = re.sub(r'(<w:pStyle w:val="[^"]+"/>(?:<w:keepNext/>)?(?:<w:keepLines/>)?(?:<w:framePr [^>]*/>)?)', r"\1" + nonum, p, count=1)
        lab = label(st)
        if st == "tablehead":
            run = f'<w:r><w:t xml:space="preserve">{lab}</w:t></w:r><w:r><w:br/></w:r>'
        elif st == "references":
            run = f'<w:r><w:t xml:space="preserve">{lab.rstrip()}</w:t></w:r><w:r><w:tab/></w:r>'
        else:
            run = f'<w:r><w:t xml:space="preserve">{lab}</w:t></w:r>'
        return p.replace("</w:pPr>", "</w:pPr>" + run, 1)
    return re.sub(r"<w:p>.*?</w:p>", fix, xml, flags=re.S)


LATEX_HEAD = r"""\documentclass[conference,a4paper]{IEEEtran}
% IEEE conference template (Overleaf "IEEE Conference Template"); a4paper because
% EmergIN 2027's own template is A4. Generated by docs/paper/build/build_paper.py --latex.
\IEEEoverridecommandlockouts
\usepackage{cite}
\usepackage{amsmath,amssymb,amsfonts}
\usepackage{algorithmic}
\usepackage{graphicx}
\usepackage{textcomp}
\usepackage{xcolor}
\usepackage{array}
\usepackage{float}
\usepackage{url}
\usepackage{microtype}   % fewer stretched inter-word spaces in justified columns
\def\BibTeX{{\rm B\kern-.05em{\sc i\kern-.025em b}\kern-.08em
    T\kern-.1667em\lower.7ex\hbox{E}\kern-.125emX}}
% tables and figures stay right after the paragraph that cites them ([H]); ragged column
% bottoms keep LaTeX from stretching the space between paragraphs to fill a column
\raggedbottom
\begin{document}
"""


def to_latex(xml):
    """LaTeX body (IEEEtran conference) from the built body XML: same text as the .docx."""
    import html

    def esc(t):
        out = []
        for k, piece in enumerate(re.split(r"(https?://[^\s)]+[^\s).,])", t)):
            if k % 2:
                out.append(r"\url{" + piece + "}")
                continue
            piece = piece.replace("\\", r"\textbackslash{}")
            for a, b in [("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"), ("_", r"\_"),
                         ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\^{}"),
                         ("<", r"\textless{}"), (">", r"\textgreater{}"), ("“", "``"), ("”", "''"),
                         ("‘", "`"), ("’", "'"), ("—", "---"), ("–", "--"), ("·", r"\textperiodcentered{}"),
                         (" ", "~")]:
                piece = piece.replace(a, b)
            piece = re.sub(r"([⁻⁰¹²³⁴⁵⁶⁷⁸⁹]+)", lambda m: "$^{" + m.group(1).translate(
                str.maketrans("⁻⁰¹²³⁴⁵⁶⁷⁸⁹", "-0123456789")) + "}$", piece)
            out.append(piece)
        return "".join(out)

    def runs_tex(p, plain=False):
        out = []
        for r in re.findall(r"<w:r>.*?</w:r>|<w:r .*?</w:r>", p, re.S):
            t = html.unescape("".join(re.findall(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", r, re.S)))
            if "<w:br/>" in r and not t:
                out.append(r" \\ ")
                continue
            if not t:
                continue
            t = esc(t)
            if not plain:
                if "<w:i/>" in r:
                    t = r"\textit{" + t + "}"
                if "<w:b/>" in r:
                    t = r"\textbf{" + t + "}"
            out.append(t)
        text = "".join(out)

        def cites(m):
            return r"\cite{" + ",".join("b" + n for n in re.findall(r"\d+", m.group(0))) + "}"
        text = re.sub(r"\[\d+\](?:,\s*\[\d+\])*", cites, text)
        return text.replace("Fig. ", "Fig.~").strip()

    out, pending_img, pending_cap, in_refs, nref = [], None, None, False, 0
    for m in re.finditer(r"<w:tbl>.*?</w:tbl>|<w:p>.*?</w:p>", xml, re.S):
        el = m.group(0)
        if el.startswith("<w:tbl>"):
            widths = [int(w) / 20 for w in re.findall(r'<w:gridCol w:w="(\d+)"/>', el)]
            # fractions of 0.97 column width (room for the rules), at least 8% per column
            fr = [max(w / sum(widths), 0.08) for w in widths]
            fr = [0.97 * f / sum(fr) for f in fr]
            spec = "|".join(
                (r">{\raggedright\arraybackslash}" if k == 0 or len(fr) == 2 else r">{\centering\arraybackslash}")
                + f"p{{\\dimexpr{f:.3f}\\columnwidth-2\\tabcolsep\\relax}}" for k, f in enumerate(fr))
            rows = []
            for k, tr in enumerate(re.findall(r"<w:tr>.*?</w:tr>", el, re.S)):
                cells = [runs_tex(tc, plain=True) for tc in re.findall(r"<w:tc>.*?</w:tc>", tr, re.S)]
                if k == 0:
                    cells = [r"\textbf{" + c + "}" for c in cells]
                rows.append(" & ".join(cells) + r" \\ \hline")
            out += [r"\begin{table}[H]", r"\caption{" + pending_cap + "}", r"\centering",
                    r"\footnotesize", r"\renewcommand{\arraystretch}{1.15}", r"\setlength{\tabcolsep}{3pt}",
                    r"\begin{tabular}{|" + spec + "|}", r"\hline"] + rows + [r"\end{tabular}", r"\end{table}", ""]
            pending_cap = None
            continue
        style = (re.findall(r'<w:pStyle w:val="([^"]+)"', el) or [""])[0]
        img = re.search(r'<pic:cNvPr id="\d+" name="([^"]+)"', el)
        if img:
            pending_img = img.group(1)
            continue
        t = runs_tex(el)
        if style == "Abstract":
            out += [r"\begin{abstract}", re.sub(r"^\\textit\{Abstract\}---", "", t), r"\end{abstract}", ""]
        elif style == "Keywords":
            out += [r"\begin{IEEEkeywords}", re.sub(r"^Keywords---", "", t), r"\end{IEEEkeywords}", ""]
        elif style == "Heading1":
            out += [r"\section{" + t + "}", ""]
        elif style == "Heading2":
            out += [r"\subsection{" + t + "}", ""]
        elif style == "Heading5":
            in_refs = True
            out += [r"\begin{thebibliography}{00}"]
        elif style == "references":
            nref += 1
            out.append(rf"\bibitem{{b{nref}}} " + t)
        elif style == "tablehead":
            pending_cap = t
        elif style == "figurecaption":
            out += [r"\begin{figure}[H]", r"\centering",
                    rf"\includegraphics[width=\columnwidth]{{{pending_img}}}",
                    r"\caption{" + t + "}", r"\end{figure}", ""]
            pending_img = None
        elif t:
            out += [t, ""]
    if in_refs:
        out.append(r"\end{thebibliography}")
    return "\n".join(out)


LINEBREAKAND = r"""\makeatletter
\newcommand{\linebreakand}{\end{@IEEEauthorhalign}\hfill\mbox{}\par\mbox{}\hfill\begin{@IEEEauthorhalign}}
\makeatother
"""


def latex_document(body):
    # the email is braced: "\\ [guide's email]" would read [..] as \\'s optional spacing argument
    names = []
    for name, email, flag in AUTHORS:
        names.append(rf"\IEEEauthorblockN{{{name}}}" "\n"
                     rf"\IEEEauthorblockA{{\textit{{{DEPT}}} \\ \textit{{{ORG}}} \\ {CITY} \\ {{{email.replace('_', chr(92) + '_')}}}}}")
    # two authors per row (IEEEtran would put three on the first row and one on the second)
    rows = ["\n\\and\n".join(names[i:i + 2]) for i in range(0, len(names), 2)]
    return (LATEX_HEAD + LINEBREAKAND + rf"\title{{{TITLE}}}" + "\n\n" + r"\author{" + "\n\\linebreakand\n".join(rows) + "}\n\n"
            + r"\maketitle" + "\n\n" + body + "\n\\end{document}\n")


def build(values, out_path, txt_path=None, literal=False, latex_dir=None):
    tmp = tempfile.mkdtemp()
    with zipfile.ZipFile(TEMPLATE) as z:
        z.extractall(tmp)
    doc_path = os.path.join(tmp, "word", "document.xml")
    x = open(doc_path, encoding="utf-8").read()

    head = x[:x.index("<w:body>") + len("<w:body>")]
    sects = re.findall(r"<w:sectPr\b.*?</w:sectPr>", x, re.S)
    title_sect, author_sect, body_sect, final_sect = sects[0], sects[1], sects[-2], sects[-1]

    img = Images()
    parts = [
        '<w:p><w:pPr><w:pStyle w:val="papertitle"/><w:suppressAutoHyphens/><w:spacing w:before="0pt" w:after="6pt"/>' + title_sect + '</w:pPr>'
        + runs(TITLE, values) + '</w:p>',
    ]
    colbreak = '<w:r><w:br w:type="column"/></w:r>'
    # two authors per row in two-column sections (the template's three columns leave the fourth
    # author alone on a second row and wrap the department name)
    two_col = re.sub(r'<w:cols [^>]*/>', '<w:cols w:num="2" w:space="36pt"/>', author_sect)
    for k, (name, email, flag) in enumerate(AUTHORS):
        second = k % 2 == 1
        p = author_para(name, email, flag, values, sect=two_col if second or k == len(AUTHORS) - 1 else "",
                        last=k >= 2)
        # the break starts the paragraph: at the end it would leave an empty line on top of the next column
        parts.append(p.replace("</w:pPr>", "</w:pPr>" + colbreak, 1) if second else p)
    body = content(values, img)
    # the body's 2-column section ends at the last reference
    body[-1] = body[-1].replace("</w:pPr>", body_sect + "</w:pPr>", 1)
    parts += body
    if txt_path:
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(to_text("".join(parts)))
    body_xml = "".join(parts)
    if latex_dir:
        os.makedirs(latex_dir, exist_ok=True)
        # the body starts at the abstract; title and authors come from TITLE/AUTHORS
        start = body_xml.index('<w:pStyle w:val="Abstract"/>')
        start = body_xml.rindex("<w:p>", 0, start)
        with open(os.path.join(latex_dir, "main.tex"), "w", encoding="utf-8") as f:
            f.write(latex_document(to_latex(body_xml[start:])))
        for _, name, src in img.items:
            shutil.copy(src, os.path.join(latex_dir, name))
    if literal:
        body_xml = literal_numbers(body_xml)
    new = head + body_xml + final_sect + "</w:body></w:document>"
    # the template's first-page footer is placeholder text ("XXX-X-XXXX-XXXX-X/XX/$XX.00 ©20XX IEEE"):
    # IEEE adds the real copyright line at camera-ready, and template text must not be submitted
    new = re.sub(r'<w:footerReference w:type="first" [^>]*/>', "", new)
    new = new.replace("<w:titlePg/>", "")
    open(doc_path, "w", encoding="utf-8").write(new)

    # images: relationships and content type
    rels_path = os.path.join(tmp, "word", "_rels", "document.xml.rels")
    rels = open(rels_path, encoding="utf-8").read()
    os.makedirs(os.path.join(tmp, "word", "media"), exist_ok=True)
    for rid, name, src in img.items:
        tiff = os.path.splitext(name)[0] + ".tiff"
        subprocess.run(["sips", "-s", "format", "tiff", "-s", "formatOptions", "lzw", "-s", "dpiWidth", "600",
                        "-s", "dpiHeight", "600", src, "--out", os.path.join(tmp, "word", "media", tiff)],
                       check=True, capture_output=True)
        rels = rels.replace("</Relationships>",
                            f'<Relationship Id="{rid}" Type="http://purl.oclc.org/ooxml/officeDocument/'
                            f'relationships/image" Target="media/{tiff}"/></Relationships>')
    open(rels_path, "w", encoding="utf-8").write(rels)
    ct_path = os.path.join(tmp, "[Content_Types].xml")
    ct = open(ct_path, encoding="utf-8").read()
    if 'Extension="tiff"' not in ct:
        ct = ct.replace("<Default Extension=\"xml\"",
                        '<Default Extension="tiff" ContentType="image/tiff"/><Default Extension="xml"')
    open(ct_path, "w", encoding="utf-8").write(ct)

    # hyphenation
    set_path = os.path.join(tmp, "word", "settings.xml")
    st = open(set_path, encoding="utf-8").read()
    if "<w:autoHyphenation" not in st:
        st = re.sub(r"(<w:defaultTabStop [^>]*/>)", r"\1<w:autoHyphenation/>", st, count=1)
    open(set_path, "w", encoding="utf-8").write(st)

    # document properties
    core_path = os.path.join(tmp, "docProps", "core.xml")
    core = open(core_path, encoding="utf-8").read()
    core = re.sub(r"<dc:title>.*?</dc:title>|<dc:title/>", f"<dc:title>{escape(TITLE)}</dc:title>", core)
    core = re.sub(r"<dc:creator>.*?</dc:creator>|<dc:creator/>",
                  f"<dc:creator>{escape(', '.join(a[0] for a in AUTHORS))}</dc:creator>", core)
    open(core_path, "w", encoding="utf-8").write(core)

    if os.path.exists(out_path):
        os.remove(out_path)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        ct_first = "[Content_Types].xml"
        z.write(os.path.join(tmp, ct_first), ct_first)
        for root, _, files in os.walk(tmp):
            for f in files:
                full = os.path.join(root, f)
                arc = os.path.relpath(full, tmp)
                if arc != ct_first and not os.path.islink(full):
                    z.write(full, arc)
    shutil.rmtree(tmp)


def main():
    global PROVISIONAL
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", required=True)
    ap.add_argument("--extra", required=True)
    ap.add_argument("--out", default=os.path.join(PAPER, "EmergIN2027_paper.docx"))
    ap.add_argument("--extra-summary", help="default: <extra csv> with _summary.json")
    ap.add_argument("--txt", help="also write the text as plain text (for reading and similarity checks)")
    ap.add_argument("--latex", metavar="DIR", help="also write an IEEEtran (Overleaf IEEE conference template) "
                    "version: DIR/main.tex plus the figures")
    ap.add_argument("--literal-numbers", action="store_true",
                    help="write Fig./TABLE/[n]/heading numbers into the text (for PDF export with Pages)")
    ap.add_argument("--provisional", action="store_true")
    a = ap.parse_args()
    PROVISIONAL = a.provisional
    global USE_FRAMES
    USE_FRAMES = not a.literal_numbers
    xs = a.extra_summary or a.extra.replace("_by_scenario.csv", "_summary.json")
    values = load_numbers(a.core, a.extra, xs)
    build(values, a.out, a.txt, a.literal_numbers, a.latex)
    print("wrote", os.path.relpath(a.out))
    if a.txt:
        print("wrote", os.path.relpath(a.txt))


if __name__ == "__main__":
    main()
