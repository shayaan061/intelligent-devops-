# File Index: what each file contains

A map of every file in the repo, so you can find things quickly when writing the report or picking up the project. **Update it whenever a file is added, removed or changes purpose.**

Last updated: 7 Oct 2026.

## Start here

| If you need… | Open |
|---|---|
| Results for the report (all tests, comparisons, evaluations, with numbers) | `experiments/RESULTS.md` |
| What has been built, step by step, and what's still open | `PROGRESS.md` |
| The plan: architecture, schemas, scenarios, timeline, checklist | `SUGGESTED_PLAN.md` |
| What happened in each work session, in time order | `SESSION_NOTES.txt` |
| How to run things, and the project rules | `CLAUDE.md` |
| Patent edits and the revised patent draft | `PATENT_CHANGES.md`, `docs/PATENT_CHANGES_FINAL.txt`, `docs/IDF_revised_tracked.docx` |

---

## 1. Documents (repo root)

| File | Contents |
|---|---|
| `SUGGESTED_PLAN.md` | **The main plan.** Core idea and patent claims (§1), objectives O1–O6 (§2), demo app (§4), architecture (§5), module design and JSON schemas for `IncidentEvent` / `ResponsePlan` (§6), tech stack (§7), repo layout (§8), timeline and work split (§9), evaluation scenarios, baselines and metrics, plus the scoring decisions of 6 Oct (§10), risks (§11), MVP vs stretch (§12), report outline (§13), patent checklist (§14), next-steps checklist (§15) |
| `PROGRESS.md` | Progress log, Steps 0–10: what was built in each step, test results, live-run results, the pilot evaluation, and the open checklists (sections A–E) |
| `SESSION_NOTES.txt` | Chronological work log of every session (timestamps, decisions, findings, fixes) |
| `CLAUDE.md` | Instructions for working on the repo: current state, commands, the gateway → analyzer → responder contract, invariants (no `fault_*` data in inputs, safety rules), the results-log rule |
| `FILE_INDEX.md` | This file |
| `commands.txt` | Quick reference: commands to start and stop the whole system (Ollama + compose stack), the URLs to open, pre-demo checks |
| `EVALUATION_GUIDE.md` | Guide for the Phase 2 evaluation and demo: what each part is, how to run it, what to show, likely questions. **Snapshot of 4 Oct**: written before the gateway, analyzer and responder existed |
| `sys arch.md` | Plain-language explanation of how the system works, component by component. **Snapshot of Phase 2**: lists the gateway, LLM and response system as future work |
| `PATENT_ALIGNED_PLAN.md` | Plan B: the base plan aligned with the patent draft (input to `SUGGESTED_PLAN.md`) |
| `PROJECT_PLAN.md` | Plan A: the ML-centric alternative plan (input to `SUGGESTED_PLAN.md`) |
| `PLAN_COMPARISON.md` | Why the suggested plan combines Plan A and Plan B |
| `PATENT_CHANGES.md` | Edits for the patent disclosure form, by page (sections A–L), extra dependent claims 8–13 with evidence (M), what was applied to the Word draft (N), and the final pass (O) |
| `patent .pdf` | The original Invention Disclosure Form, the older PDF version |
| `README.md` | Only the repo title |

## 2. Results and experiment data (`experiments/`)

| File | Contents |
|---|---|
| `RESULTS.md` | **Report-ready results**: environment, the 146 automated tests, development runs D1–D10, pilot B1 vs B2, analyzer comparisons C0–C3, safety suite, timings, 14 problems found by testing, objectives status, caveats, and an index of the raw data |
| `pilot_b1.csv`, `pilot_b2.csv` | Pilot ground truth from the injector, one row per run (4 each). Columns: `run_id, scenario, name, fault, target_service, expected_root_cause, expected_action, start, planned_end, end, end_reason, params` |
| `pilot_b1_scored.csv`, `pilot_b2_scored.csv` | `score.py` output per pilot run. Columns: `run_id, scenario, name, end_reason, incident_id, detected, auto_resolved, mttr_s, mttd_s, root_cause, root_cause_ok, plan_action, plan_action_ok, executed_action, executed_action_ok, unsafe_executed, collateral_executed, verified, escalated, attempts, plan_source, fallback_reason, plan_latency_ms` (from 12 Oct also `llm_calls, prompt_tokens, completion_tokens`; `results/eval_stage<N>_<system>_runs.csv` from `run_eval.py score` have the same columns, `eval_stage<N>_summary.json` the summaries per system) |
| `results/ground_truth_dev_runs.csv` | Ground truth of the 8 logged development runs on 6 Oct (same columns as `pilot_b1.csv`); the runs behind RESULTS.md §2 |
| `results/compare_1_original_prompt.csv` | Analyzer comparison C1: 9 samples × (runbook + 1 LLM run) = 18 rows. Columns: `scenario, mode, rep, source, fallback_reason, root, root_ok, action, action_ok, confidence, latency_s` |
| `results/compare_2_rule_error_spike.csv` | C2: after the "error_spike → reset first" prompt rule; 9 × (runbook + 2 LLM runs). Shows the scenario 1 regression |
| `results/compare_3_rule_any_service.csv` | C3: after the "any service can be the root cause" rule; 18/18 correct |
| `results/safety_suite.csv` | Adversarial suite, 29 cases. Columns: `id, case, expected, outcome, schema_rejects, executed, unsafe_executed, crashed, pass` |
| `results/incident_store_snapshot.jsonl` | Every gateway message from 17:17 UTC on 6 Oct, one JSON per line (107 lines: 42 raw alerts, 23 incident updates with full context, 15 response plans, 27 responder actions). No `fault_*` data. Use it for incident timelines and examples in the report |
| `results/pilot_run.log` | Pilot runner log: start/end times, the scenario lines, the analyzer mode switches |
| `baseline_20261009_1334.csv` | ML training data: 78 min of normal traffic (945 rows). Columns as below |
| `results/ground_truth_check_9oct.csv`, `results/check_9oct_b2_runs.csv`, `results/incident_store_check_9oct.jsonl` | 9-scenario B2 run on real containers (RESULTS §11) |
| `results/ml_detector_report_9oct.json`, `results/ml_replay_check_9oct.json`, `results/ml_rerun_9oct_s_runs.csv`, `results/incident_store_ml_9oct.jsonl`, `results/ml_detector_anomalies_9oct.log` | ML detector training report, offline replay, live runs with ML (RESULTS §12) |
| `results/eval_stage1_{B1,B2,S}_runs.csv`, `results/eval_stage1_summary.json` | §10 evaluation stage 1 scores per run (score.py columns) and per system (RESULTS.md §13) |
| `results/eval_stage1_before_redo_*` | The same, before 4 runs spoiled by a runner bug were voided and redone |
| `results/eval_stage1_manifest.csv` | Copy of `eval/runs.csv` after stage 1 (81 done + 4 void) |
| `results/eval_stage1_ground_truth_{B1,B2,S}.csv` | Injector ground truth per system for stage 1 (same columns as `ground_truth.csv`; includes the voided runs) |
| `results/eval_stage1_run_eval.log`, `results/eval_stage1_console.log` | Runner log and runner + injector console output for stage 1 |
| `results/incident_store_eval_stage1.jsonl` | Every gateway message from 11 Oct 20:25 UTC (stage 1 + redo), one JSON per line; no `fault_*` data |
| `results/eval_stage2_{B1,B2,S}_runs.csv`, `results/eval_stage2_summary.json`, `results/eval_stage2_by_scenario.csv` | §10 evaluation stage 2 scores so far (rounds 1-4, 36 runs per system; same columns as stage 1; per-scenario counts and MTTD/MTTR means) (RESULTS.md §17) |
| `results/eval_stage2_round4_manifest.csv`, `results/eval_stage2_round4_ground_truth_{B1,B2,S}.csv` | Copies of `eval/runs.csv` and the per-system ground truth after stage 2 round 4 |
| `results/eval_stage2_round4_console.log`, `results/eval_stage2_round4_run_eval.log` | Runner + injector console output and runner log up to the end of round 4 |
| `results/eval_stage3_{B1,B2,S}_runs.csv`, `results/eval_stage3_summary.json`, `results/eval_stage3_by_scenario.csv` | §10 evaluation, core final: scores for rounds 1-20 (180 runs per system; same columns as stage 1; per-scenario counts and MTTD/MTTR means) (RESULTS.md §18a) |
| `results/eval_stage3_manifest.csv`, `results/eval_stage3_ground_truth_{B1,B2,S}.csv`, `results/eval_stage3_run_eval.log` | Copies of `eval/runs.csv`, the per-system ground truth and the runner log after the core block (21 Oct) |
| `results/eval_extra_stage3_{B1,B2,S,SF}_runs.csv`, `results/eval_extra_stage3_summary.json`, `results/eval_extra_stage3_by_scenario.csv` | Extra suite final scores (scenarios 10-14 on B1/B2/S, 3/4/6/8 on SF; 10 runs per scenario; same columns as the core scores) (RESULTS.md §18b) |
| `results/eval_extra_stage3_manifest.csv`, `results/eval_extra_stage3_ground_truth_{B1,B2,S,SF}.csv` | Copies of `eval/extra/runs.csv` and the per-system ground truth after the extra block (22 Oct) |
| `results/eval_novel_stage2_{B1,B2,S,SF}_runs.csv`, `results/eval_novel_stage2_summary.json`, `results/eval_novel_stage2_by_scenario.csv` | Novel unknown-fault suite stage 2 scores (scenarios 15/16/18/19, rounds 1-5, 5 runs per scenario and system; same columns as the core scores) (RESULTS.md §21) |
| `results/eval_novel_stage2_manifest.csv`, `results/eval_novel_stage2_ground_truth_{B1,B2,S,SF}.csv` | Copies of `eval/novel/runs.csv` and `eval/novel/gt_*.csv` at 97 runs done (27 Oct 00:21 UTC) |
| `results/eval_novel_stage3_{B1,B2,S,SF}_runs.csv`, `results/eval_novel_stage3_summary.json`, `results/eval_novel_stage3_by_scenario.csv`, `results/eval_novel_stage3_manifest.csv`, `results/eval_novel_stage3_ground_truth_{B1,B2,S,SF}.csv` | Novel suite final scores (10 runs per scenario and system) and copies of `eval/novel/` after the block (RESULTS.md §22) |
| `results/guard_decisions_long_run.csv`, `results/mttr_mwu_B1_B2.csv` | Derived 26 Oct for Paper A: live responder decisions per system (decision, B1, B2, S, SF) and the MTTR Mann-Whitney test B1 vs B2 per scenario (scenario, n_B1, n_B2, median_B1, median_B2, hl_shift_s, U, z, p) (RESULTS.md §20) |
| `results/eval_stage3_S_open_sources.csv`, `results/eval_stage3_mttd_percentiles.csv` | Derived 26 Oct from the stage-3 scores and the long-run store: which detector opened each S incident per scenario (suite, scenario, runs, rule, ml, rule+ml, not_in_store, undetected) and MTTD per system (system, n, min, p50, p90, max) (RESULTS.md §18c) |
| `results/incident_store_long_run_19-22oct.jsonl` | Every gateway message of the long block (19 Oct 15:42 to 22 Oct 18:17 UTC, core + extra), one JSON per line (id, at, channel, type, incident_id, status, body); no `fault_*` data |
| `results/soak_1_*`, `results/soak_2_*` | Soak tests (no faults, harmless events every 30 min, system S): soak 1 = 12-13 Oct, 10 h, 19 events (RESULTS.md §16); soak 2 = 22-23 Oct, 12 h, 23 events (§19); both 0 false alarms. `*_summary.json` = soak-score output, `*_windows.csv` / `*_events.csv` = copies of `eval/soak/`, `*_console.log` |
| `results/incident_store_eval_stage2_round4.jsonl` | Gateway messages from the two round-4 windows (12 Oct 11:30-12:45, 13 Oct 16:25-19:00 UTC), one JSON per line; no `fault_*` data |
| `results/baseline_export_test_40min.csv` | 192 rows of normal-traffic features (test of `record_baseline.py`). Columns: `timestamp, service, clients, cpu, err, mem, mem_bytes, ops, p95, rps, up, upstream_p95` |
| `results/long_run_19oct.sh`, `long_run_19oct.out`, `long_run_19oct.pid` | Wrapper for the long block of 19 Oct (core rounds 5-20, then extra rounds 2-10, retries after an abort), its stdout and its PID (RESULTS.md §18) |
| `results/eval_core_r5-20_console.log`, `eval_extra_r2-10_console.log` | Runner output of that block |
| `ground_truth.csv` *(not in git)* | Live injector log; every new run is appended here. Copy runs worth keeping into `results/` |
| `incidents.db` *(not in git)* | The gateway's SQLite incident store (table `messages`). Export with a query, as for `results/incident_store_snapshot.jsonl` |

### Experiment scripts (`experiments/`)

| File | Purpose |
|---|---|
| `score.py` | Scores runs: joins a ground-truth CSV with `incidents.db` and prints §10 metrics (recall, MTTD, root cause, action, unsafe actions, auto-resolved, MTTR, latency, LLM calls and tokens per incident). `--system`, `--since`, `--max-gap` (count false positives only within a system's blocks), `--out`, `--json` |
| `run_eval.py` | §10 evaluation runner in resumable blocks, shuffled, systems interleaved. Suite `novel` (scenarios 15-19 on B1/B2/S/SF, `eval/novel/`, added 26 Oct). Suite `core`: scenarios 1-9 on B1/B2/S (stages 1/2/3 = 3/10/20 rounds); suite `extra`: 10-14 on B1/B2/S and 3, 4, 6, 8 on SF (LLM unreachable), stages 3/5/10 rounds. Switches the analyzer mode/LLM URL and ml-detector, checks health/quiet, keeps the 300 s gap, voids runs the Mac slept through, caffeinate. `run`, `status`, `void`, `score` (also a per-scenario table), `soak` (no faults, optional restarts/load changes), `soak-score` |
| `eval/` *(not in git until results are kept)* | Runner state: `runs.csv` (columns `system, round, slot, scenario, run_id, status, started, ended, end_reason, note`; status `done` or `void`), `gt_B1.csv` / `gt_B2.csv` / `gt_S.csv` (injector ground truth per system, same columns as `ground_truth.csv`), `run_eval.log`; `extra/` the same for the extra suite (incl. `gt_SF.csv`); `soak/windows.csv` (columns `system, start, end, awake_hours, events, note`) and `soak/events.csv` (`window_start, at, event, detail, until`) |
| `safety_suite.py` | The 29 adversarial plans through the real responder; prints the table, `--csv` |
| `compare_analyzers.py` | Runbooks vs LLM on `analyzer/samples/scenario*.json`; `--repeat`, `--model`, `--out` |
| `record_baseline.py` | Exports ML training data from Prometheus (no fault or alert periods); `--last 2h`; `--keep-all` keeps everything, for `ml/replay.py` |
| `tests/test_score.py`, `tests/test_safety_suite.py`, `tests/test_run_eval.py` | Tests for the scorer (15), the safety suite (1) and the evaluation runner (19) |

## 3. Figures and drafts (`docs/`)

| File | Contents |
|---|---|
| `docs/IDF_revised_tracked.docx` | The newer Word patent draft with the `PATENT_CHANGES.md` edits as **tracked insertions** and 12 comments for the inventors (the original is in `~/Downloads`, untouched) |
| `docs/IDF_final.docx`, `docs/IDF_final.txt` | **The complete revised Invention Disclosure Form** (8 Oct 2026), word for word, aligned with the built system; the .docx has the new Fig. 1 and Fig. 2. Supersedes the Pages draft and `IDF_revised_tracked.docx` |
| `docs/idf_source/` | Sources for the two files above: `content.js` (the text), `build.js` (docx + txt), `figures.js` (Fig. 1, Fig. 2), README with the rebuild steps |
| `docs/figures/idf_fig1_architecture.png`, `idf_fig2_workflow.png` | The new IDF figures: architecture (detectors, gateway/context builder, LLM + runbooks, validator, executor, verifier loop, store, dashboard, approval) and workflow (validity and policy decisions, approval, bounded re-analysis, escalation) |
| `docs/Intelligent DevOps Monitoring and Incident Response System Invention Disclosure.pages` | The team's Pages draft (tracked changes accepted) that `IDF_final` revises |
| `docs/PATENT_CHANGES_FINAL.txt` | Final, paste-ready patent changes (8 Oct 2026), by IDF section: abstract, field, prior art, summary, figures, working steps, claims 1–15, implementation status, evidence, and the decisions left to the inventors |
| `docs/ml_training_notes.txt` | Plain-text notes on the ML detector (13 Oct 2026): how it was trained, the training data (`baseline_20261009_1334.csv`, columns and medians), and whether 78 min is enough (soak evidence, limitations, retrain advice) |
| `experiments/guard_decisions.py`, `experiments/mttr_significance.py` | Paper A analyses: counts live policy decisions from the incident store; Mann-Whitney U on MTTR between two systems (no SciPy) |
| `docs/paper/build/make_chunks.py` | Splits the paper's .txt into ≤1,200-word parts, one paragraph per line; optional 3rd argument = file prefix (`paperA2_chunks/`) |
| `docs/paper/paperA2_chunks/paperA2_part<i>_of_5.txt`, `paperA2_combinedfinal.txt` | `EmergIN2027_paperA2.txt` (final, reworded text) split into 5 parts of ≤1,200 words (1136/1088/1064/1083/1034), and all parts joined; regenerated 28 Oct after the rewording |
| `docs/paper/build/build_paper.py` | Builder library for the paper: fills the IEEE conference template's own styles (layout, tables, figures as TIFF, references, `--txt`/`--latex`/`--literal-numbers` outputs, number loading from `run_eval.py score` files). Its own Paper A text and outputs are no longer used (Paper A files deleted 28 Oct 2026); `build_paper_a2.py` imports it |
| `docs/paper/build/build_paper_a2.py` | Builder for Paper A2 (28 Oct 2026): imports `build_paper.py` (template, layout, figures, references) and replaces the title and text; adds the unknown-fault suite numbers from `experiments/results/eval_novel_stage3_*` (RESULTS.md §22). Same options plus `--novel DIR` |
| `docs/paper/build/a2_text.py` | Paper A2 title, abstract, contributions, Fig. 1 caption and the 32 body paragraphs in order: the authors' reworded chunks corrected against the original wording; used by `build_paper_a2.py` (`--original-text` builds the earlier wording) |
| `docs/paper/EmergIN2027_paperA2.docx`, `EmergIN2027_paperA2.txt`, `EmergIN2027_paperA2.pdf` | **Paper A2**: Paper A extended with the known vs unknown fault comparison (890 runs, 18 scenarios, Table IV unknown faults); Word version, plain text, and the Pages PDF of the Word version (6 pages) |
| `docs/paper/latex_ieee_a2/` | Paper A2 in IEEEtran (`main.tex`, figures, `paperA2_overleaf.zip`, `main.pdf` 6 pages). Generated by `build_paper_a2.py --latex` |
| `docs/paper/EmergIN2027.pdf` | **Submission copy of Paper A2** (renamed from EmergIN2027_PaperA2_FINAL.pdf by the authors) (28 Oct 2026): copy of `latex_ieee_a2/main.pdf`, 6 pages, A4. Rebuilt 29 Oct 2026 with the wording of `EmergIN2027_AI_highlights.docx` (27 paragraphs edited directly in `latex_ieee_a2/main.tex`; `build/a2_text.py` still has the 28 Oct wording, so a rebuild with `build_paper_a2.py --latex` would undo them). Same day: floats moved from `[H]` to the top/bottom of columns and `flushend` added, which removed the empty column bottoms (also by hand in `main.tex`) |
| `docs/paper/build/figures.py` | Draws Fig. 1 (architecture, one column), Fig. 2 (MTTD/MTTR per core scenario) and the MTTR-only Fig. 2 of Paper A (`fig2_mttr` from `eval_stage*_by_scenario.csv`) as SVG and renders PNG with headless Chrome |
| `docs/paper/figures/fig1_architecture.png`, `fig2_results.png`, `fig2_mttr.png` (+ `.html` sources) | Paper figures (Fig. 1 black and white since 28 Oct)s: architecture; MTTD + MTTR per scenario (earlier paper); MTTR per scenario (Paper A's Fig. 2) |
| `docs/paper/PAPER_PLANS.md` | Plans for two separate papers (26 Oct 2026): A = policy-guarded LLM remediation → EmergIN 2027 (30 Oct), B = label-free ML detection → DAL 2026 (7 Nov). Claims, RQs, section/word budgets, numbers with RESULTS.md sections, figures, overlap rules, references to verify, schedule, risks |
| `docs/paper/template/conference-template2027.docx` | The EmergIN 2027 IEEE Word template (A4), downloaded 20 Oct 2026 from niet.co.in/ieee-conference-2027 |
| `docs/paper/template/springer_lnns/word/` | Springer LNNS proceedings Word template (downloaded 23 Oct 2026 from the link on icida.ikrf.in): `splnproc2510.docm` (Windows) and `splnproc2510_mac.docm` (Mac), with macros for the style ribbon; `Quick Start.pdf`, `SPLNPROC Technical Instructions.pdf`. For ICIDA and DAL |
| `docs/paper/template/springer_lnns/latex/` | Springer LNCS/LNNS LaTeX2e package (Sept 2026): `llncs.cls`, `samplepaper.tex`, `splncs04.bst`, `llncsdoc.pdf`. DAL prefers LaTeX |
| `docs/conferences_nov2026.txt` | Conference search for acceptance before 20 Nov 2026 (20-21 Oct 2026). Shortlist at the top: ICIDA 2026, EmergIN 2027, DAL 2026, with dates, fees, rules and links; ICAIN-2026 (dropped), near misses, closed venues and ones to avoid |
| `docs/results/Evaluation_Results.docx` | Word report of the final evaluation (23 Oct 2026): setup, core and extra summary tables, 9 figures each with its reading, soak result, limits, sources |
| `docs/results/figures/fig1-9_*.png` | The report's figures: core MTTD and MTTR per scenario, MTTR spread, correct actions, MTTD per round, extra detection, extra outcomes, SF fallback, LLM cost |
| `docs/results/make_figures.py`, `docs/results/build_doc.py` | Draw the figures (matplotlib) and build the .docx (python-docx) from `experiments/results/`; rerun both after any re-scoring |
| `docs/paper/IEEE CONFERENCES_2026.xlsx` | List of 718 IEEE conferences in India in 2026 (columns: Name, Start Date as an Excel serial date, Location, External URL; Sheet1 only). Checked 21 Oct 2026; results in `docs/conferences_nov2026.txt` §4 |
| `docs/devops_incident_handling_irl.txt` | Plain-text notes (19 Oct 2026) on how incidents are handled in industry (detection, on-call, diagnosis, common fixes, existing automation, postmortems) and how this project maps onto it, for the report |
| `docs/figures/dashboard_scenario7.png` | Screenshot of the dashboard: service map, one incident (scenario 7) with plan → executed → verified, an approval card |
| `docs/figures/web_incident_detail.png` | Next.js dashboard, incident page for the real scenario 6 incident (redis down → restart → verified): detection, context, plans, actions |
| `docs/figures/web_overview_synthetic_metrics.png` | Next.js dashboard overview (light mode). **Metrics are synthetic** (a fake Prometheus, Docker was off); the stats come from the real incident snapshot, and the open incident and approval are test data |

## 4. System code, by component

### Demo application (the system being monitored)
| File | Contents |
|---|---|
| `app/app.py` | **frontend** service (Flask): `/` calls api-service; fault injection (`/inject` incl. optional `delay_s`/`rate` for subtle faults, `/reset`), `/health`, `/metrics`, upstream-latency metric |
| `api-service/app.py` | **api-service** (Flask): `/data` → Redis `INCR`; the same fault-injection, health and metrics code as `app/app.py` (keep the two in sync) |
| `app/`, `api-service/` `Dockerfile`, `requirements.txt` | Container builds |
| `load/locustfile.py` | Locust background traffic (~5 req/s) that the HTTP alerts need |

### Monitoring and detection
| File | Contents |
|---|---|
| `prometheus/prometheus.yml` | Scrape config (5 s): frontend, api-service, redis exporter, cAdvisor |
| `prometheus/rules.yml` | Alert rules: HighCPU, HighMemory, HighLatency, HighErrorRate, ServiceDown, RedisDown, ExporterDown (30 s windows, `for: 20s`) |
| `prometheus/rules_test.yml` | promtool unit tests for the rules |
| `alertmanager/alertmanager.yml` | Routing: webhook to `gateway:8000/alerts`, grouping, inhibition |

### Event Gateway (`gateway/`, port 8000)
| File | Contents |
|---|---|
| `app.py` | Endpoints: `/alerts`, `/anomalies`, `/responses`, `/actions`, `/incidents/{id}/reanalyze`, `/history`, WebSockets `/ws/events` and `/ws/responses`, the dashboard mount; rejects NaN/Infinity JSON |
| `incidents.py` | Dedup and grouping of alerts and anomalies into incidents (60 s window, dependency chain); a repeat anomaly from the same service only refreshes it; `ml_active()` for the verifier |
| `context.py` | Context builder: PromQL queries for the last 10 minutes per service; asserts there are no `fault_*` queries |
| `store.py` | SQLite incident store (every broadcast message) |
| `tests/test_gateway.py` | 20 tests |

### LLM Analysis Engine (`analyzer/`)
| File | Contents |
|---|---|
| `schemas.py` | **The data contract**: Pydantic `IncidentEvent` and `ResponsePlan` (action allowlist, strict confidence) |
| `llm.py` | Ollama client and the **prompt** (`SYSTEM_PROMPT`, with few-shot examples); validates the output; falls back to runbooks with a reason |
| `runbooks.py` | Loads `runbooks/*.yaml` and finds the root cause from topology and context (baseline B1 and the LLM fallback) |
| `analyzer.py` | `analyze()` (LLM with fallback), WebSocket service with a coalescing queue, CLI `analyze <sample.json>` |
| `samples/scenario1..9.json` | Hand-written `IncidentEvent` examples, one per §10 scenario (used by `compare_analyzers.py`; the prompt was tuned on them) |
| `samples/live/scenario5_live.json` | **Held-out** real incident from the pilot (the LLM chose the wrong action on it); not used for tuning |
| `tests/` | 75 tests: `test_schemas.py`, `test_runbooks.py`, `test_llm.py` (Ollama mocked), `test_service.py`, `conftest.py` |

### Runbooks (`runbooks/`)
| File | Runbooks |
|---|---|
| `availability.yaml` | `dependency-down` (redis), `service-down` |
| `resources.yaml` | `high-memory`, `high-cpu`, `ml-memory-anomaly` |
| `http.yaml` | `high-error-rate`, `high-latency` |
| `monitoring.yaml` | `monitoring-down` (ExporterDown → escalate) |

### Response System + Verifier (`responder/`, port 8001)
| File | Contents |
|---|---|
| `policies.yaml` | **The safety rules**: action allowlist and targets, approval-required actions, confidence ≥ 0.7, 300 s cooldown, max 3 actions and 3 attempts, 45 s verify delay |
| `policy.py` | Policy validator (pure functions): execute / approval / escalate |
| `executor.py` | The only code that changes anything: reset faults, restart container, flush cache |
| `app.py` | Plan intake, pre-check and verifier (firing alerts + the gateway's `ml_active`), re-analysis requests, approval API (`/approvals`), read-only `/policies` (rules + active cooldowns, for the dashboard), dry-run mode, reports to the gateway |
| `tests/test_responder.py` | 45 tests |

### ML Anomaly Detector (`ml/`, compose service `ml-detector`)
| File | Contents |
|---|---|
| `model.py` | Per-service model: robust z-scores against the training baseline (only the "worse" direction counts) + Isolation Forest over the z-vector; `FEATURES`, `HIGH_IS_BAD`, scale floors |
| `train.py` | Trains on `record_baseline.py` CSVs; reports the false-positive rate on a held-out last 20%; writes `models/detector.joblib` + `_report.json` |
| `detector.py` | Service: every 15 s reads the gateway's context queries from Prometheus, scores, POSTs `/anomalies` after 2 anomalous polls in a row (re-posted while it lasts). Only reports |
| `replay.py` | Offline: steps the detector through a `--keep-all` export and scores it against `ground_truth.csv` (recall, delay, false-positive episodes) |
| `Dockerfile` | Built from the repo root (copies `gateway/context.py`); root `.dockerignore` limits that context |
| `models/` | Trained model (`detector.joblib`) and its report |
| `tests/test_ml.py` | 10 tests (synthetic data) |

### Dashboard and tools
| File | Contents |
|---|---|
| `dashboard/index.html` | Minimal UI at `localhost:8000/dashboard/`: service map, incident feed with plans and actions, approval buttons (kept as a fallback) |
| `web/` | **Full dashboard** (Next.js 15 + TypeScript + Tailwind + Recharts) at `localhost:3001`, compose service `web` |
| `web/app/page.tsx` | Overview: stat tiles, service map with live values, active incidents with the plan, approval queue, live metric charts (5 min – 1 h) |
| `web/app/incidents/page.tsx`, `incidents/[id]/page.tsx` | Incident list from the store (filter by outcome); one incident end to end: detection → context charts → plans → actions → verification |
| `web/app/approvals/page.tsx`, `web/app/system/page.tsx` | Approval queue with reasons; pipeline health, scrape targets, firing alerts, safety policy, active cooldowns, outcome counts |
| `web/app/api/*` | Server-side routes: `metrics` (fixed PromQL from `gateway/context.py`, asserts no `fault_*`), `stats` (from `/history`), `system` (health probes), `gateway/*` and `responder/*` allowlisted proxies (approve/reject needs the `x-dashboard` header) |
| `web/lib/live.tsx`, `web/lib/types.ts` | Live state from both WebSockets (de-duplicated replays); message types |
| `web/components/` | Charts (one metric per chart, fixed colour per service), service map, plan/action views, approval queue |
| `injector/injector.py` | Fault injector: the 9 §10 scenarios (core), 15-19 (novel, added 26 Oct: subtle frontend latency/errors, CPU limit cut, two faults at once, Redis memory filled; no runbook covers them) and 10-14 (extra: corrupted cache, slow Redis, subtle latency, subtle errors, recurring fault; Redis faults via `docker exec`), suites, ground-truth CSV logging |
| `injector/web.py`, `injector/static/index.html` | Injector control panel at `localhost:8088` |
| `docker-compose.yml` | The whole stack: services, ports, environment variables, mounts |

## 5. Other

| File | Contents |
|---|---|
| `*/requirements-dev.txt` | Test dependencies (pytest) per component |
| `.gitignore` | Ignores `__pycache__`, `.pyc`, `.pytest_cache`, `.venv`, `experiments/incidents.db*`, `.DS_Store` |
| `.dockerignore` | Build context filter for `ml/Dockerfile` (the only image built from the repo root) |
