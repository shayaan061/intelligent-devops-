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
| `pilot_b1_scored.csv`, `pilot_b2_scored.csv` | `score.py` output per pilot run. Columns: `run_id, scenario, name, end_reason, incident_id, detected, auto_resolved, mttr_s, mttd_s, root_cause, root_cause_ok, plan_action, plan_action_ok, executed_action, executed_action_ok, unsafe_executed, collateral_executed, verified, escalated, attempts, plan_source, fallback_reason, plan_latency_ms` |
| `results/ground_truth_dev_runs.csv` | Ground truth of the 8 logged development runs on 6 Oct (same columns as `pilot_b1.csv`); the runs behind RESULTS.md §2 |
| `results/compare_1_original_prompt.csv` | Analyzer comparison C1: 9 samples × (runbook + 1 LLM run) = 18 rows. Columns: `scenario, mode, rep, source, fallback_reason, root, root_ok, action, action_ok, confidence, latency_s` |
| `results/compare_2_rule_error_spike.csv` | C2: after the "error_spike → reset first" prompt rule; 9 × (runbook + 2 LLM runs). Shows the scenario 1 regression |
| `results/compare_3_rule_any_service.csv` | C3: after the "any service can be the root cause" rule; 18/18 correct |
| `results/safety_suite.csv` | Adversarial suite, 29 cases. Columns: `id, case, expected, outcome, schema_rejects, executed, unsafe_executed, crashed, pass` |
| `results/incident_store_snapshot.jsonl` | Every gateway message from 17:17 UTC on 6 Oct, one JSON per line (107 lines: 42 raw alerts, 23 incident updates with full context, 15 response plans, 27 responder actions). No `fault_*` data. Use it for incident timelines and examples in the report |
| `results/pilot_run.log` | Pilot runner log: start/end times, the scenario lines, the analyzer mode switches |
| `results/baseline_export_test_40min.csv` | 192 rows of normal-traffic features (test of `record_baseline.py`). Columns: `timestamp, service, clients, cpu, err, mem, mem_bytes, ops, p95, rps, up, upstream_p95` |
| `ground_truth.csv` *(not in git)* | Live injector log; every new run is appended here. Copy runs worth keeping into `results/` |
| `incidents.db` *(not in git)* | The gateway's SQLite incident store (table `messages`). Export with a query, as for `results/incident_store_snapshot.jsonl` |

### Experiment scripts (`experiments/`)

| File | Purpose |
|---|---|
| `score.py` | Scores runs: joins a ground-truth CSV with `incidents.db` and prints §10 metrics (recall, MTTD, root cause, action, unsafe actions, auto-resolved, MTTR, latency). `--system`, `--since`, `--out`, `--json` |
| `safety_suite.py` | The 29 adversarial plans through the real responder; prints the table, `--csv` |
| `compare_analyzers.py` | Runbooks vs LLM on `analyzer/samples/scenario*.json`; `--repeat`, `--model`, `--out` |
| `record_baseline.py` | Exports ML training data from Prometheus (no fault or alert periods); `--last 2h` |
| `tests/test_score.py`, `tests/test_safety_suite.py` | Tests for the scorer (9) and the safety suite (1) |

## 3. Figures and drafts (`docs/`)

| File | Contents |
|---|---|
| `docs/IDF_revised_tracked.docx` | The newer Word patent draft with the `PATENT_CHANGES.md` edits as **tracked insertions** and 12 comments for the inventors (the original is in `~/Downloads`, untouched) |
| `docs/IDF_final.docx`, `docs/IDF_final.txt` | **The complete revised Invention Disclosure Form** (8 Oct 2026), word for word, aligned with the built system; the .docx has the new Fig. 1 and Fig. 2. Supersedes the Pages draft and `IDF_revised_tracked.docx` |
| `docs/idf_source/` | Sources for the two files above: `content.js` (the text), `build.js` (docx + txt), `figures.js` (Fig. 1, Fig. 2), README with the rebuild steps |
| `docs/figures/idf_fig1_architecture.png`, `idf_fig2_workflow.png` | The new IDF figures: architecture (detectors, gateway/context builder, LLM + runbooks, validator, executor, verifier loop, store, dashboard, approval) and workflow (validity and policy decisions, approval, bounded re-analysis, escalation) |
| `docs/Intelligent DevOps Monitoring and Incident Response System Invention Disclosure.pages` | The team's Pages draft (tracked changes accepted) that `IDF_final` revises |
| `docs/PATENT_CHANGES_FINAL.txt` | Final, paste-ready patent changes (8 Oct 2026), by IDF section: abstract, field, prior art, summary, figures, working steps, claims 1–15, implementation status, evidence, and the decisions left to the inventors |
| `docs/figures/dashboard_scenario7.png` | Screenshot of the dashboard: service map, one incident (scenario 7) with plan → executed → verified, an approval card |
| `docs/figures/web_incident_detail.png` | Next.js dashboard, incident page for the real scenario 6 incident (redis down → restart → verified): detection, context, plans, actions |
| `docs/figures/web_overview_synthetic_metrics.png` | Next.js dashboard overview (light mode). **Metrics are synthetic** (a fake Prometheus, Docker was off); the stats come from the real incident snapshot, and the open incident and approval are test data |

## 4. System code, by component

### Demo application (the system being monitored)
| File | Contents |
|---|---|
| `app/app.py` | **frontend** service (Flask): `/` calls api-service; fault injection (`/inject`, `/reset`), `/health`, `/metrics`, upstream-latency metric |
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
| `incidents.py` | Dedup and grouping of alerts and anomalies into incidents (60 s window, dependency chain) |
| `context.py` | Context builder: PromQL queries for the last 10 minutes per service; asserts there are no `fault_*` queries |
| `store.py` | SQLite incident store (every broadcast message) |
| `tests/test_gateway.py` | 19 tests |

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
| `app.py` | Plan intake, pre-check, verifier, re-analysis requests, approval API (`/approvals`), read-only `/policies` (rules + active cooldowns, for the dashboard), dry-run mode, reports to the gateway |
| `tests/test_responder.py` | 43 tests |

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
| `injector/injector.py` | Fault injector: the 9 §10 scenarios, suites, ground-truth CSV logging |
| `injector/web.py`, `injector/static/index.html` | Injector control panel at `localhost:8088` |
| `docker-compose.yml` | The whole stack: services, ports, environment variables, mounts |

## 5. Other

| File | Contents |
|---|---|
| `*/requirements-dev.txt` | Test dependencies (pytest) per component |
| `.gitignore` | Ignores `__pycache__`, `.pyc`, `.pytest_cache`, `.venv`, `experiments/incidents.db*` |
| `.DS_Store` | macOS folder metadata, committed by accident; safe to delete and ignore |
