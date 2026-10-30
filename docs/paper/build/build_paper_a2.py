"""Builds Paper A2: the EmergIN paper extended with the unknown-fault (novel) suite.

Same template, layout code, figures and references as build_paper.py (imported); only the
title, the text and the numbers differ. Paper A (build_paper.py) is left unchanged.

    python3 docs/paper/build/build_paper_a2.py --core experiments/results \
        --extra experiments/results/eval_extra_stage3_by_scenario.csv \
        --novel experiments/results --out docs/paper/EmergIN2027_paperA2.docx \
        [--txt docs/paper/EmergIN2027_paperA2.txt] [--latex docs/paper/latex_ieee_a2] [--literal-numbers]

Novel numbers: experiments/results/eval_novel_stage3_{summary.json,by_scenario.csv,<system>_runs.csv}
(RESULTS.md section 22).
"""
import argparse
import csv
import json
import os

import a2_text
import build_paper as bp
from build_paper import FIGS, para, runs, table, guard_rows, extra_rows, REFERENCES, Cites

EDITED = True     # body text from a2_text.py (the authors' reworded chunks, corrected); False: original wording
TITLE = ("Policy-Guarded Remediation of Known and Unknown Microservice Faults "
         "Using a Local Large Language Model")
NOVEL_SYSTEMS = ["B1", "B2", "S", "SF"]


def load_novel(v, novel_dir):
    summ = json.load(open(os.path.join(novel_dir, "eval_novel_stage3_summary.json")))
    by = {(r["system"], r["scenario"]): r
          for r in csv.DictReader(open(os.path.join(novel_dir, "eval_novel_stage3_by_scenario.csv")))}
    v["_novel"] = by
    runs = {s: list(csv.DictReader(open(os.path.join(novel_dir, f"eval_novel_stage3_{s}_runs.csv"))))
            for s in NOVEL_SYSTEMS}
    v["n_novel"] = str(sum(summ[s]["runs"] for s in NOVEL_SYSTEMS))
    v["nrun"] = str(summ["S"]["runs"])
    for s in NOVEL_SYSTEMS:
        d = summ[s]
        auto = round(d["auto_resolved_pct"] * d["runs"] / 100)
        v[f"nauto_{s}"] = str(auto)
        v[f"nautopct_{s}"] = f"{d['auto_resolved_pct']:.0f}"
        v[f"nrecall_{s}"] = f"{d['recall_pct']:.1f}".rstrip("0").rstrip(".") + "%"
        v[f"nunsafe_{s}"] = str(d["unsafe_actions_executed"])
        v[f"ncoll_{s}"] = str(d["collateral_actions_executed"])
        # verified although the fault was still there at its planned end
        v[f"nfalsever_{s}"] = str(sum(1 for r in runs[s] if "verified:" in r["action_log"]
                                      and r["end_reason"] != "remediated"))
        m = [float(r["mttr_s"]) for r in runs[s] if r["scenario"] == "18" and r["mttr_s"]]
        v[f"mttr18_{s}"] = f"{sum(m) / len(m):.0f}" if m else "–"
        for sid in ("15", "16", "18", "19"):
            r = by[(s, sid)]
            v[f"n{sid}det_{s}"] = r["detected"]
            v[f"n{sid}res_{s}"] = r["auto_resolved"]
            v[f"n{sid}esc_{s}"] = r["escalated"]
    s15 = [r for r in runs["S"] if r["scenario"] == "15"]
    first_ok = [float(r["mttr_s"]) for r in s15 if r["root_cause_ok"] == "True" and r["mttr_s"]]
    later = [float(r["mttr_s"]) for r in s15 if r["root_cause_ok"] == "False" and r["mttr_s"]]
    v["s15_first"] = str(len(first_ok))
    v["s15_fmin"], v["s15_fmax"] = f"{min(first_ok):.0f}", f"{max(first_ok):.0f}"
    v["s15_wrong"] = str(sum(1 for r in s15 if r["root_cause_ok"] == "False"))
    v["s15_later"] = str(len(later))
    v["s15_later_t"] = " and ".join(f"{x:.0f}" for x in sorted(later))
    v["n_total"] = str(int(v["n_total"]) + int(v["n_novel"]))
    return v


def novel_rows(v):
    names = {"15": "15 Frontend latency", "16": "16 Frontend errors",
             "18": "18 Two faults", "19": "19 Redis memory"}
    rows = []
    for sid, label in names.items():
        rows.append([label] + [f"{{n{sid}det_{s}}} / {{n{sid}res_{s}}} / {{n{sid}esc_{s}}}" for s in NOVEL_SYSTEMS])
    rows.append(["Resolved (of 40)"] + [f"{{nauto_{s}}}" for s in NOVEL_SYSTEMS])
    rows.append(["Verified, fault stayed"] + [f"{{nfalsever_{s}}}" for s in NOVEL_SYSTEMS])
    return rows


def content(v, img):
    cite = Cites()
    edited = iter(a2_text.PARAGRAPHS)
    pick = (lambda t: next(edited)) if EDITED else (lambda t: t)
    P = lambda t: para("BodyText", cite(pick(t)), v)
    H1 = lambda t: para("Heading1", t, v)
    H2 = lambda t: para("Heading2", t, v)
    out = []

    # The template forbids symbols and math in the abstract: no %, no ~.
    out.append(para("Abstract", "", v, ppr_extra='<w:spacing w:before="10pt"/>', inner=runs("*Abstract*—", v) + runs(
        "Large language models (LLMs) can read monitoring data and propose fixes for failing "
        "services, but executing their output on a live system is risky, because a plan can name "
        "the wrong service, invent an action or be malformed. This paper presents a closed-loop "
        "incident response system for microservices in which an anomaly detector and alert rules "
        "find faults, a locally hosted LLM or rule-based runbooks recommend actions, and a "
        "deterministic policy validator alone decides what may run. Every executed fix is verified "
        "and re-analyzed at most three times before the incident is escalated. On a three-service "
        "containerized application we compare runbooks, the LLM and the full system over {n_total} "
        "fault-injection runs covering 18 scenarios, split into faults the runbooks were written "
        "for and faults they were not, and test the validator with 29 adversarial plans. No unsafe "
        "action was executed in any run or adversarial case. On known faults the runbooks were the "
        "better choice: the LLM found the same root causes but chose a less suitable action in "
        "{llm_wrong_word} percent of runs and added about {llm_cost} seconds to recovery. On four "
        "faults without a runbook the full system resolved {nautopct_S} percent of runs against "
        "{nautopct_B1} percent for the runbooks: the detector found faults below the alert "
        "thresholds and the LLM chose a fix where no rule matched, while with the LLM switched off "
        "the same detections could only be escalated. Faults that every variant misdiagnosed were "
        "escalated after a bounded number of attempts. The results support runbooks for known "
        "faults, the LLM where they end, and one guard for both." if not EDITED else a2_text.ABSTRACT,
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
        "incident to a human. We study four questions. RQ1 (safety): can such a loop run on live "
        "containers without an unsafe action, even when plans are malformed or malicious? RQ2 "
        "(known faults): given the same detection, does the LLM diagnose and act better than "
        "rule-based runbooks? RQ3 (unknown faults): which part of the system helps when no runbook "
        "was written for the fault? RQ4 (robustness): what happens when the diagnosis is wrong, the "
        "fault is misleading or keeps returning, or the LLM is unavailable? The contributions are:"))
    for t in [
        "1) A closed-loop architecture (monitor, detect, analyze, decide, respond, verify) in which "
        "the LLM has no access to the system and a policy validator, the only path to execution, "
        "enforces an action allowlist, known targets, a confidence threshold, a cross-incident "
        "cooldown, per-incident limits, human approval for destructive actions and bounded "
        "re-analysis followed by escalation.",
        "2) An adversarial suite of 29 hallucinated, malformed and malicious plans run against the "
        "real responder, which exposed four input-handling defects in the responder and the gateway, "
        "fixed before the evaluation.",
        "3) An evaluation on real containers with {n_total} fault-injection runs over 18 scenarios "
        "in three groups, known faults, misleading, below-threshold and recurring faults, and "
        "faults without a runbook, and four system variants, among them one in which the LLM is "
        "unavailable.",
        "4) A comparison of the detector, the LLM and the runbooks under the same guard, showing "
        "that each covers a different part of the problem: runbooks the known faults, the detector "
        "the subtle ones, and the LLM the faults no runbook matches."] if not EDITED else a2_text.CONTRIBUTIONS:
        out.append(para("BodyText", cite(t), v))
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
                       a2_text.FIG1_CAPTION if EDITED else
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
    out.append(table([48, 136, 58], ["Check", "Rule", "On failure"], [
        ["Allowlist", "reset, restart, flush cache, update resources, escalate", "fallback/escalate"],
        ["Target", "allowed service (no reset on Redis)", "fallback/escalate"],
        ["Confidence", "a number in [0, 1] and at least 0.7", "human approval"],
        ["Risk", "flush cache, update resources", "human approval"],
        ["Cooldown", "same action and target not within 300 s", "fallback/escalate"],
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
        "Building the suite exposed four input-handling defects in the "
        "responder and the gateway, which were then fixed; for instance, a NaN "
        "confidence passed the threshold test because NaN < 0.7 is false, and a Boolean true was "
        "read as a confidence of 1.0. After the fixes all 29 cases behave as specified: the "
        "control case runs, and every adversarial plan is blocked, reduced to its safe part or "
        "sent to a human."))


    # V
    out.append(H1("Evaluation Setup"))
    out.append(H2("Testbed and Fault Scenarios"))
    out.append(P(
        "All experiments run on one laptop (Apple M4, 10 cores, 16 GB) with Docker Desktop; the LLM "
        "runs on the host. A Locust load generator sends about five requests per second. A fault "
        "injector starts each fault, logs its start and planned end, and polls the target until the "
        "fault is gone. A run counts as remediated if the fault disappears before its planned end, "
        "which only happens if the system fixed it. Table II lists the scenarios."))
    scenarios_text = (
        "Scenarios 1 to 9 "
        "form the core set of known faults, the ones the runbooks were written for, lasting 180 s "
        "(300 s for the leak). Scenarios 10 to 14 form an extra set of misleading, below-threshold "
        "and recurring faults lasting 300 s (480 s for scenario 14). Scenarios 15, 16, 18 and 19 "
        "form an unknown set, faults for which no runbook rule was written, lasting 300 s: subtle "
        "faults on the frontend, two faults at once, and a Redis memory fault whose matching "
        "memory rule prescribes a restart that cannot fix it. We added this set after the first two "
        "had been evaluated and ran it on the unchanged system.")
    out.append(table([14, 107, 14, 107], ["#", "Fault (expected action)", "#", "Fault (expected action)"], [
        ["1", "CPU load, frontend (reset or restart)", "10", "Corrupted cache value (flush, approval)"],
        ["2", "CPU load, API (reset or restart)", "11", "Slow Redis writes (restart Redis)"],
        ["3", "Memory 420 MB, API (restart)", "12", "Latency 0.6 s, API (reset)"],
        ["4", "Latency 5 s, API (reset)", "13", "5% of requests fail, API (reset)"],
        ["5", "All requests fail, API (reset)", "14", "Latency that returns after every fix (escalate)"],
        ["6", "Redis stopped (restart Redis)", "15", "Latency 0.6 s, frontend (reset or restart)"],
        ["7", "Frontend stopped (restart)", "16", "5% of requests fail, frontend (reset or restart)"],
        ["8", "Memory leak, 440 MB over 240 s (restart)", "18", "CPU on frontend and errors on API (reset both)"],
        ["9", "CPU and latency, API (reset)", "19", "Redis filled with 150 MB of keys (flush, approval)"],
    ], v, "Fault Scenarios: Known (1–9), Extra (10–14) and Unknown (15–19)"))
    out.append(P(scenarios_text))   # rest of V-A, after the table it introduces
    out.append(H2("Systems Compared"))
    out.append(P(
        "*B1*: alert rules and runbooks, without the LLM or the anomaly detector. *B2*: alert rules "
        "and the LLM with runbook fallback, without the anomaly detector. B1 and B2 receive the same "
        "signals, so their difference isolates the analysis step. *S*: the full system. *SF*: the "
        "full system with the LLM unreachable, so that its runbooks act on the detector's "
        "incidents; it ran on scenarios 3, 4, 6 and 8 and on the unknown set. S and SF differ only "
        "in the analysis step, SF and B1 only in the detector. All variants share the same "
        "responder and policies."))
    out.append(H2("Protocol and Metrics"))
    out.append(P(
        "Each round runs every scenario once per system in a shuffled order fixed by a seed, with "
        "rounds interleaved across systems, and consecutive runs are 300 s apart so the cooldown "
        "never carries over. The core set ran for {rounds_min} rounds ({n_B1} runs per system), "
        "the extra set for 10 rounds ({n_extra} runs) and the unknown set for 10 rounds on all four "
        "variants ({n_novel} runs); a run the laptop slept through was voided and repeated. We report root-cause accuracy of the first plan; action correctness "
        "against the expected action; unsafe actions; collateral actions, permitted actions on a "
        "service that was not the cause; the auto-resolution rate; the mean time to recover (MTTR, "
        "fault start to fault gone, for remediated runs); the share of runs needing a second "
        "attempt; the escalation rate; and the LLM cost as plan latency and tokens per incident."))

    # VI
    out.append(H1("Results"))
    out.append(H2("Safety (RQ1)"))
    out.append(P(
        "No unsafe action was executed in any of the {n_total} runs of the four variants, and no "
        "incident was opened without an injected fault. Safety did not come for free: on the "
        "misleading faults of the extra set the variants executed {coll_B1}, {coll_B2} and "
        "{coll_S} collateral actions (B1, B2, S), resets and restarts of a healthy service that the "
        "policy permits, and S executed {ncoll_S} more on the unknown set. The cooldown and the "
        "action limit capped these at three per incident. No plan in the live runs proposed a "
        "destructive action, so the approval path was exercised only by the adversarial suite."))
    out.append(P(
        "To see how the policy behaved in practice, we counted its decisions in the "
        "{guard_incidents} incidents recorded by the incident store (core rounds 5 to 20, extra "
        "rounds 2 to 10). The allowlist, target and "
        "confidence checks never had to block a live plan: every recommendation named a permitted "
        "action and target with a valid confidence, so the evidence for these checks is the "
        "adversarial suite. The guard intervened through the cooldown. On the extra set the LLM "
        "variants recommended {cd_B2} (B2) and {cd_S} (S) times to repeat a reset or restart that had "
        "just failed; each time the cooldown blocked it, and the responder ran the fallback action "
        "or escalated. The runbooks never did this, because their plans for unmatched incidents "
        "escalate directly."))
    out.append(H2("Known Faults: LLM Versus Runbooks (RQ2)"))
    out.append(P(
        "On the core scenarios, summarized in Table III, every variant detected every fault. B1 and B2 found the "
        "root cause in every run, but the executed action was correct in {act_B1} of runs for B1 and "
        "{act_B2} for B2. All of B2's wrong actions were on scenario 5 ({act5_B2} correct), where the "
        "LLM named the right service but restarted it instead of resetting its fault; the restart "
        "also removed the fault, so the error cost time rather than safety."))
    out.append(table([96, 49, 49, 48], ["Metric", "B1", "B2", "S"], [
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
    ], v, "Results on the Core Scenarios ({n_B1} Runs per Variant)"))
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
    out.append(H2("Unknown Faults (RQ3)"))
    out.append(P(
        "The results for the unknown set are summarized in Table IV. The subtle frontend faults "
        "(15 and 16) stayed below the alert thresholds, so B1 and B2 never responded. The anomaly "
        "detector found the latency fault (15) in every S and SF run. With the LLM unavailable, SF "
        "had no runbook rule for an anomaly-only latency incident and escalated all ten runs; S "
        "resolved {n15res_S} of 10, {s15_first} with a correct first reset of the frontend in "
        "{s15_fmin} to {s15_fmax} s and {s15_later} after the verify loop corrected a first plan "
        "that blamed the api-service ({s15_later_t} s). The detector found this fault and the LLM "
        "fixed it; neither did so alone. The 5 percent error fault (16) is intermittent and was "
        "detected in only {n16det_S} S runs and {n16det_SF} SF run, and never resolved."))
    out.append(table([78, 41, 41, 41, 41], ["Scenario", "B1", "B2", "S", "SF"], novel_rows(v), v,
                     "Unknown Faults: Detected / Resolved / Escalated Runs of 10"))
    out.append(P(
        "The combined fault (18) fires the usual error alert, and B1, B2 and S resolved it in every "
        "run in two steps, the api-service first and the frontend after re-analysis; B1 was fastest "
        "({mttr18_B1} s against {mttr18_S} s for S). SF resolved {n18res_SF}, escalating when its "
        "incident opened on the anomaly before the alert. In the Redis memory fault (19) every "
        "variant named Redis and restarted it, but Redis reloaded the keys from disk, so the fault "
        "stayed; no plan, from the LLM or a runbook, proposed flushing the cache. S and SF saw the "
        "anomaly persist and escalated every run. Without the detector, the verifier of B1 and B2 "
        "accepted the restart in {nfalsever_B1} and {nfalsever_B2} runs because the memory alert had "
        "briefly cleared, and the alert later opened a new incident. Over the 40 runs, S resolved "
        "{nauto_S}, B1 and B2 {nauto_B1} each and SF {nauto_SF}."))
    out.append(H2("Wrong Diagnoses and the Verify Loop (RQ4)"))
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
    out.append(H2("Misleading and Recurring Faults (RQ4)"))
    out.append(P(
        "The results for the extra set are summarized in Table V. In the misleading Redis faults (10 and 11) Redis stays up "
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
    out.append(H2("LLM Unavailable and Cost (RQ4)"))
    out.append(P(
        "With the LLM unreachable, SF fell back to the runbooks and resolved {sf_fixed} of "
        "{sf_runs} known-fault runs, the memory, Redis and leak faults in every run and faster than "
        "S, since no LLM call was made. In {sf4_esc} of 10 latency runs (scenario 4) the incident "
        "opened on an anomaly before the latency alert fired, no runbook matched an anomaly-only "
        "latency incident, and the fallback plan escalated it early; the same gap caused its "
        "escalations on the unknown set. An incident in S used {calls_S} LLM calls on average, with "
        "about {tokin_S} prompt and {tokout_S} completion tokens on the core set and {tokxin_S} and "
        "{tokxout_S} on the extra set. With a local model this costs time rather than money: about "
        "{lat_S} s per plan."))

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
        "*Each part has a different job.* On known faults the LLM added latency and no accuracy, "
        "and on the misleading faults it failed like the runbooks. On the unknown set it was the "
        "only analysis step that resolved the subtle latency fault, and only because the detector "
        "had found it first; the detector without the LLM could only escalate, and the LLM without "
        "the detector never saw the fault. The detector also kept the verifier from accepting a "
        "restart that had not worked. A deployment should therefore let runbooks handle known "
        "patterns, call the LLM when no runbook applies, and keep the same guard for both. The LLM "
        "is not a general fix: on the Redis memory fault it chose the same useless restart as the "
        "runbook."))
    out.append(P(
        "*Validity.* Faults are injected through an endpoint, so the reset action stands in for "
        "real-world rollbacks or feature-flag switches. The testbed is one laptop with three "
        "services, synthetic load and one 8-billion-parameter model; a larger model may diagnose "
        "the misleading faults better. The unknown set has four scenarios, designed by the authors "
        "after the first evaluation, so it shows where the LLM can help rather than how often it "
        "will. A manual baseline in which an engineer handles the same faults is needed to quantify "
        "the time saved against current practice. Future work includes error logs and deployment "
        "events in the incident context, rollback as an action, fine-tuning the model on logged "
        "incidents and testing it on held-out faults, and larger Kubernetes deployments."))

    # VIII
    out.append(H1("Conclusion"))
    out.append(P(
        "We presented a closed-loop incident response system in which a policy layer, not the LLM, "
        "decides what runs. On real containers no unsafe action was executed in {n_total} runs or 29 "
        "adversarial plans, the verify loop repaired wrong first diagnoses, and misleading or "
        "recurring faults were escalated after a bounded number of attempts. On known faults the "
        "runbooks beat the LLM on action choice and speed; on faults without a runbook the detector "
        "and the LLM together resolved {nauto_S} of 40 runs against {nauto_B1} for the runbooks. "
        "Bounded, verified automation with graded human approval lets operators use LLMs where "
        "runbooks end, without trusting them."))

    if EDITED:
        assert next(edited, None) is None, "a2_text.PARAGRAPHS has more paragraphs than the paper"
    # References (the style numbers them), in order of first citation
    out.append(para("Heading5", "References", v, ppr_extra="<w:keepNext/>"))
    missing = set(cite.order) - set(REFERENCES)
    assert not missing, f"no reference entry for {missing}"
    for key in cite.order:
        out.append(para("references", REFERENCES[key], v, ppr_extra='<w:suppressAutoHyphens/><w:ind w:start="17.70pt" w:hanging="17.70pt"/><w:jc w:val="start"/>'))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", required=True)
    ap.add_argument("--extra", required=True)
    ap.add_argument("--novel", required=True, help="dir with eval_novel_stage3_* files")
    ap.add_argument("--out", default=os.path.join(bp.PAPER, "EmergIN2027_paperA2.docx"))
    ap.add_argument("--txt")
    ap.add_argument("--latex", metavar="DIR")
    ap.add_argument("--literal-numbers", action="store_true")
    ap.add_argument("--original-text", action="store_true", help="the wording before the authors' rewording")
    a = ap.parse_args()
    global EDITED
    EDITED = not a.original_text
    bp.USE_FRAMES = not a.literal_numbers
    bp.TITLE = a2_text.TITLE if EDITED else TITLE
    bp.content = content
    xs = a.extra.replace("_by_scenario.csv", "_summary.json")
    values = load_novel(bp.load_numbers(a.core, a.extra, xs), a.novel)
    bp.build(values, a.out, a.txt, a.literal_numbers, a.latex)
    print("wrote", os.path.relpath(a.out))
    if a.txt:
        print("wrote", os.path.relpath(a.txt))


if __name__ == "__main__":
    main()
