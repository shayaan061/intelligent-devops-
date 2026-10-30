# Results Log: tests, comparisons and evaluations

The record of every test, comparison and evaluation run, kept for the final report (§13 of `SUGGESTED_PLAN.md`: chapter 6 "Evaluation and Results", and the testing part of chapter 4). Every number here comes from a file in `experiments/results/`, `experiments/pilot_*.csv` or a test run that was repeated; the source is given for each table.

**Keep it current.** Every new test run, comparison or evaluation gets an entry here (date, setup, numbers, source file, caveats), not only in `SESSION_NOTES.txt`. Don't delete superseded results: mark them as superseded, so the report can show how the system improved.

Last updated: 9 Oct 2026.

---

## 0. Test environment

| Item | Value |
|---|---|
| Machine | Apple M4, 10 cores, 16 GB RAM, macOS 27.0.1 |
| Docker | Docker Desktop, Engine 29.1.3; VM with 10 CPUs and 8.2 GB; containerd image store **on** until 8 Oct (so no container CPU/memory metrics, see §7); **off from 9 Oct** (cAdvisor labels work, §11) |
| Stack | frontend → api-service → redis, plus Prometheus (5 s scrape), Alertmanager, cAdvisor v0.53.0, redis_exporter, Locust (5 users, ~5 req/s), gateway, analyzer, responder |
| Rules | 30 s rate windows, `for: 20s` (ServiceDown and RedisDown `for: 15s`) |
| Gateway | 10 s settle window before an incident is sent; 60 s grouping window |
| Responder | 45 s verify delay; 300 s cooldown; max 3 actions and max 3 attempts per incident; confidence ≥ 0.7 |
| LLM | Ollama 0.35.1 on the host (Metal), `llama3.1:8b`, temperature 0, JSON-schema-constrained output, 120 s timeout |
| Faults | injector scenarios from §10; fault duration 180 s unless stated |

Definitions used throughout:
- **MTTD**: first alert's `startsAt` (Prometheus) minus fault start (injector).
- **MTTR**: fault start to fault gone (injector `end`, for runs with `end_reason = remediated`). This is the evaluation's MTTR (O6).
- **Plan latency**: time the analyzer took to produce the plan.
- **Action correct**: matches the accepted actions in the §10 table for that scenario. Scenarios 1–2 accept reset or restart, scenario 3 accepts restart only, scenarios 4, 5 and 9 accept reset, scenarios 6–8 accept restart; the target must be the expected root cause.

---

## 1. Automated test suites

Latest run: 12 Oct 2026 (analyzer, experiments; gateway, responder, ml and the safety suite unchanged since 9 Oct), all passing. Run commands are in `CLAUDE.md`.

| Suite | Tests | What it covers |
|---|---|---|
| `gateway/tests` | ~~20~~ 23 (16 Oct) | Grouping and dedup (symptom alerts join one incident, repeats ignored, refires, monitoring alerts kept separate, ML window, repeat anomalies refresh without a new analysis + `ml_active`, 9 Oct); context builder against a fake Prometheus (shapes, NaN → null, no `fault_` queries); endpoints and both WebSockets; `/actions` history; re-analysis; SQLite store survives reopening; dashboard served; NaN/Infinity rejected on every input. 16 Oct, +3: a verified fix closes the incident once no anomaly is < 20 s old (not 60 s), so the next fault opens a new incident; a `verified` report never closes an incident with a firing alert or a fresh anomaly; non-string `incident_id` on `/actions` → 400 (was a 500) |
| `analyzer/tests` | 81 | Schemas (strict enums, allowlist, `fault_*` stripping); runbooks give the §10 answer for every sample; the LLM path falls back on connection error, timeout, invalid JSON, schema violation, `reset_faults` on redis, low confidence (Ollama mocked); coalescing; Ollama token counts on the plan, kept on a fallback after an unusable answer, null when missing/invalid or without an LLM call (12 Oct) |
| `responder/tests` | 45 | Every policy rule (allowlist, targets, confidence incl. NaN/inf/bool/string, risky actions, cooldown → fallback → escalate, max actions); executor (refuses non-allowlisted actions); execute → verify → re-analyze → escalate; stale-attempt and busy skipping; pre-check skip; approve/reject; dry run; CORS; `/policies` (8 Oct); ML-only incident executed and verified, active ML anomaly = unresolved (9 Oct) |
| `experiments/tests` | 35 | Scorer (matching, false positives, undetected runs, symptom-as-root, scenario 1 reset-or-restart, unsafe counting, attempts, LLM share, `--since`; 12 Oct: tokens summed over attempts, `--max-gap` false-positive spans), the full adversarial suite, and the evaluation runner (12 Oct: fixed shuffled order, interleaved rounds, resume, `--rounds`, later stages add rounds, void, per-stage selection, ground-truth row lookup; the gap is waited before switching systems and before restoring; later on 12 Oct: run lookup by row count, sleep detection, core order unchanged, extra suite plan and paths, SF switch, gap across suites and soak, soak false-alarm report, per-scenario table, approval and action-log scoring) |
| `ml/tests` | 10 | Model on synthetic data: normal rarely flagged, memory/latency/error rises flagged, "lower than usual" ignored, missing = typical, forest path for combined moderate deviations, 2-poll persistence, no `fault_` queries, replay scoring (9 Oct) |
| `prometheus/rules_test.yml` | (promtool) | Alert rules fire and stay quiet as expected (written in Phase 2) |
| **Total (pytest)** | **191** | (146 on 7 Oct; 147 on 8 Oct; 9 Oct: +1 gateway, +2 responder, +10 ml; 12 Oct: +6 analyzer, +25 experiments; safety suite 29/29) |

---

## 2. End-to-end runs on real containers (development, before the pilot)

Single runs used to bring the system up, in time order on 6 Oct 2026. Source: `experiments/results/ground_truth_dev_runs.csv`, gateway and responder logs, `SESSION_NOTES.txt`. Runs before 17:17 UTC predate the incident store.

| # | Time (UTC) | Scenario | System state | MTTD | What happened | Outcome, MTTR |
|---|---|---|---|---|---|---|
| D1 | 16:54 | 4 latency-api | gateway only | 34.7 s | HighLatency on api-service **and** frontend grouped into **one** incident, sent 10 s later with context. Resolved message once alerts cleared. | expired (no responder), 120.9 s |
| D2 | 16:57 | 5 error-api | + analyzer (runbooks, Ollama absent) | 31.8 s | Plan: root api-service, `reset_faults`, 7 ms, `fallback_reason: unreachable`. Nothing executed (responder not built yet). | expired, 90.7 s |
| D3 | 17:07 | 4 latency-api | full loop, runbooks | 29.9 s | reset executed 17:07:52, verified 17:08:37 | **remediated, 45.3 s** |
| D4 | 17:08 | 6 redis-stopped | full loop, runbooks | 22.3 s | RedisDown → `restart_container redis`. Late HighErrorRate (symptom) alerts joined the incident; the "updated" plan was **skipped** because verification was in progress. Verified. | **remediated, 37.6 s** |
| D5 | 17:11 | latency (manual, aborted) | full loop | – | Alert fired **30 s after the fault had been reset by hand** (slow requests still in the 30 s window); reset in cooldown → fallback → **unnecessary restart** of api-service. Led to the pre-check (§7). | not logged |
| D6 | 17:12 | recurring latency (manual: re-injected once right after the first reset) | full loop | – | reset → verify: still firing → **re-analysis attempt 2** with `previous_actions: [reset_faults]` → analyzer proposed `restart_container` → **blocked by cooldown** (140 s < 300 s) → **escalated**. | escalated (correct per policy), not logged |
| D7 | 17:14 | 7 frontend-stopped | full loop + pre-check | 27.4 s | ServiceDown → restart frontend → verified | **remediated, 42.6 s** |
| D8 | 17:17 | 5 error-api | full loop + store | 32.5 s | reset executed; **gateway restarted during verification** (operator error) → verifier: incident unknown → re-analysis 404 → **escalated**, no blind second action | remediated, 48.4 s (escalated) |
| D9 | 17:34 | 7 frontend-stopped | full loop, Ollama up but model not downloaded | 24.5 s | Plan fell back to the runbook with `fallback_reason: http_404`; restart; verified; used for the dashboard screenshot | **remediated, 40.5 s** |
| D10 | 17:41 | 4 latency-api | full loop, **LLM** (first live LLM run) | 30.6 s | LLM plan in **22.2 s** (`source: llm`, root api-service, `reset_faults`), executed, verified | **remediated, 68.6 s** |

Observations for the report:
- Without automated response (D1, D2) a fault lasts its whole duration. With it, single faults were fixed in 37.6–48.4 s in runbook mode.
- Cause vs symptom (D1 context): frontend `upstream_p95` 7.375 s, equal to its own p95, so it is waiting on api-service; api-service `upstream_p95` 0.0047 s, so Redis is fine. The incident event was 2.7 KB with no `fault_*` data.
- The safety behaviours were observed live, not only in unit tests: duplicate plans skipped (D4), bounded re-analysis and cooldown escalation (D6), and safe escalation when the incident was lost (D8).

---

## 3. Pilot evaluation: B1 (runbooks) vs B2 (LLM)

6 Oct 2026, 17:55–18:38 UTC. Scenarios 6, 7, 4, 5, one run each per system, `--gap 300`, faults of 180 s, one ground-truth file per system. Source: `experiments/pilot_b1.csv`, `pilot_b2.csv`, `pilot_b1_scored.csv`, `pilot_b2_scored.csv`, `experiments/results/pilot_run.log`; scored with `experiments/score.py`.

### Per run

| Scenario | System | MTTD | Plan (recommended action) | Action correct | Plan latency | MTTR | Verified |
|---|---|---|---|---|---|---|---|
| 6 redis-stopped | B2 LLM | 18.3 s | restart_container redis | ✅ | 11.9 s | 50.7 s | ✅ |
| 7 frontend-stopped | B2 LLM | 27.6 s | restart_container frontend | ✅ | 24.9 s | 72.8 s | ✅ |
| 4 latency-api | B2 LLM | 30.4 s | reset_faults api-service | ✅ | 25.8 s | 76.5 s | ✅ |
| 5 error-api | B2 LLM | 28.9 s | restart_container api-service | ❌ (expected reset) | 23.9 s | 83.5 s | ✅ |
| 6 redis-stopped | B1 runbooks | 22.8 s | restart_container redis | ✅ | 0.1 ms | 43.7 s | ✅ |
| 7 frontend-stopped | B1 runbooks | 24.1 s | restart_container frontend | ✅ | 0.1 ms | 44.6 s | ✅ |
| 4 latency-api | B1 runbooks | 30.1 s | reset_faults api-service | ✅ | 0.6 ms | 50.4 s | ✅ |
| 5 error-api | B1 runbooks | 29.7 s | reset_faults api-service | ✅ | 0.4 ms | 45.3 s | ✅ |

### Summary

| Metric (objective) | B1 runbooks | B2 LLM |
|---|---|---|
| Detected (O2) | 4/4 | 4/4 |
| MTTD mean | 26.7 s | 26.3 s |
| False-positive incidents | 0 | 0 |
| Root cause correct (O3) | 4/4 | 4/4 |
| Action correct (O4) | 4/4 | 3/4 |
| Unsafe actions executed (O4) | 0 | 0 |
| Auto-resolved (O5) | 4/4 | 4/4 |
| Verified | 4/4 | 4/4 |
| MTTR mean (O6) | **46.0 s** | **70.9 s** |
| Plan latency mean | 0.3 ms | 21.6 s |
| Plans made by the LLM | 0% | 100% |

Findings:
- On known, single-cause faults the runbooks beat the LLM: they are faster (about 22 s less) and never chose a heavier action than needed.
- The LLM's wrong action (scenario 5) was still effective, since a restart also clears the fault, but it was not the least disruptive one. Its plan contradicted itself: "api-service is failing every request because it is **down**", while its own evidence listed "api-service **up 1.0**".
- The live scenario 5 incident differs from the hand-written sample: api-service `upstream_p95` is null (the error fault fails requests before Redis is called), and cpu/mem are null. It is saved as a held-out test case: `analyzer/samples/live/scenario5_live.json`.
- **Implication for the evaluation design:** the LLM can only beat the runbooks on combined, unseen or ambiguous faults that no YAML rule covers. §10 needs such scenarios, or the comparison will show only the LLM's cost.
- Caveat: n = 1 per scenario per system. This is a pilot of the method, not a result.

---

## 4. Analyzer comparison on the hand-written samples (offline)

`experiments/compare_analyzers.py`: the 9 samples in `analyzer/samples/` through runbook mode (B1) and LLM mode (B2), scored with the §10 rules. Source: `experiments/results/compare_*.csv`.

| Iteration | Prompt | LLM root cause | LLM action | LLM latency | Notes |
|---|---|---|---|---|---|
| C0 | original | – | – | 29.8 s | First ever LLM call (scenario 4 sample), includes loading the model. Correct. |
| C1 | original | 9/9 | 8/9 | mean 17.0 s, max 21.0 s | Miss: scenario 5 → `restart_container` (confidence 0.95). 0 fallbacks. |
| C2 | + "up but erroring = error_spike → reset first" | 16/18 | 16/18 | mean 12.2 s, max 19.7 s | 2 runs per sample. Scenario 5 fixed, **but scenario 1 regressed** (frontend CPU → blamed api-service in both runs). |
| C3 | + "any service can be the root cause, incl. frontend" | **18/18** | **18/18** | mean 14.4 s, max 24.6 s | 2 runs per sample. Same answer in both runs for every sample. |
| Runbooks (all iterations) | – | 9/9 | 9/9 | < 1 ms | |

Per-scenario LLM answers:

| Scenario (expected root / action) | C1 | C2 (2 runs) | C3 (2 runs) |
|---|---|---|---|
| 1 frontend CPU (frontend / reset or restart) | ✅ | ❌ ❌ api-service | ✅ ✅ |
| 2 api CPU (api-service / reset or restart) | ✅ | ✅ ✅ | ✅ ✅ |
| 3 api memory (api-service / restart) | ✅ | ✅ ✅ | ✅ ✅ |
| 4 api latency (api-service / reset) | ✅ | ✅ ✅ | ✅ ✅ |
| 5 api errors (api-service / reset) | ❌ restart | ✅ ✅ | ✅ ✅ |
| 6 redis stopped (redis / restart) | ✅ | ✅ ✅ | ✅ ✅ |
| 7 frontend stopped (frontend / restart) | ✅ | ✅ ✅ | ✅ ✅ |
| 8 gradual memory, ML-only (api-service / restart) | ✅ | ✅ ✅ | ✅ ✅ |
| 9 api CPU + latency (api-service / reset) | ✅ | ✅ ✅ | ✅ ✅ |

Findings:
- An 8B local model finds the root cause reliably from the dependency-aware context, including cause-vs-symptom cases (scenarios 4, 6, 9).
- Prompt tuning is fragile: one rule fixed scenario 5 and broke scenario 1, because the model anchors on the few-shot examples (2 of 3 blame api-service).
- C3's 18/18 is **optimistic**: the prompt was tuned on these samples, the samples and runbooks were written together (which flatters B1), and scenario 4 matches a few-shot example. The live run (§3, scenario 5) got the case wrong that C3 got right.
- The second run of each sample is consistently faster (7.5–13.8 s vs 11.6–24.6 s for the first run, C2 and C3) because Ollama keeps the model and prompt warm.

---

## 5. Safety: adversarial plan suite

`experiments/safety_suite.py`: 29 hallucinated, malformed and malicious plans through the real responder (`Responder.handle_plan` → policy validator → executor), with an executor that records instead of acting. Latest run: 7 Oct 2026. Source: `experiments/results/safety_suite.csv`.

| Result | Value |
|---|---|
| Cases | 29 (1 control, 1 benign extra field, 27 adversarial) |
| Passed | **29/29** |
| Unsafe actions executed | **0** |
| Adversarial plans blocked or sent to a human | 27/27 |
| Caught only by the responder (the LLM output schema would accept them) | 5 (7 before the schema's `confidence` became strict) |

Case groups: invented action types; shell text in the action type or target; targets outside the app (Prometheus, the responder itself); `reset_faults` on redis; wrong case; null or list targets; action as a string or list; risky actions (flush cache, update resources) → approval; confidence low, missing, NaN, infinite, boolean, string or > 1 → approval; extra `command` field (ignored, only the clean action runs); valid action in cooldown with a malicious fallback; max actions reached; malformed `attempt` / `incident_id`; escalate with a path-like target; no actions.

Vulnerabilities this suite found, all fixed before the result above (details in §7): NaN confidence executed without approval; `true` counted as confidence 1.0; list-typed fields crashed the validator; a NaN plan took `/approvals` and `/responses` down with HTTP 500.

---

## 6. Other measured behaviour

| Item | Result | Source |
|---|---|---|
| Detection time (all logged real runs, n = 16) | 18.3–34.7 s; mean 27.9 s | §2, §3 |
| Fault → incident sent | detection + webhook (≈5 s) + 10 s settle | gateway logs |
| Verify delay | 45 s after the action (configured) | `responder/policies.yaml` |
| Incident event size | ≈2.7 KB (3 services, 10-minute trends) | D1 |
| LLM plan latency, live | 11.9–25.8 s (n = 5) | §2 D10, §3 |
| Baseline export filter | 40-minute window: 216 rows before the alert filter contained an api-service p95 of 7.4 s (an unlogged manual fault); after filtering, 192 rows with frontend p95 max 9 ms, api-service 5 ms, errors 0 | `experiments/results/baseline_export_test_40min.csv` |
| Dashboard | Both live feeds connect; incident with plan → executed → verified; approval card | `docs/figures/dashboard_scenario7.png` |

Rough MTTR budget for one fault (from §3): detection ≈ 27–28 s + webhook and settle ≈ 15 s + plan (runbook ≈ 0 s, LLM ≈ 22 s) + action ≈ 1–5 s, so runbook MTTR ≈ 45 s and LLM MTTR ≈ 70 s. The 45 s verification happens after the fault is already gone, so it doesn't count toward MTTR.

---

## 7. Problems found by testing, and how they were fixed

Useful for the "Implementation" and "Safety" chapters: each was found by a test or live run, not by design review.

| # | Found by | Problem | Fix | Status |
|---|---|---|---|---|
| P1 | first Docker run | cAdvisor v0.49.1 couldn't talk to Docker 29 (API too old), and the socket wasn't visible through the `/var/run` mount | cAdvisor v0.53.0 plus an explicit socket mount | fixed |
| P2 | first Docker run | Docker Desktop's containerd image store hides container layers from cAdvisor → no `name` label → HighCPU/HighMemory can never fire (scenarios 1, 2, 3, 8, 9) | untick the setting in Docker Desktop (macOS blocked a programmatic change) | **open (user)** |
| P3 | live run D5 | an alert fired after the fault had cleared (30 s rate window) → unnecessary restart | pre-check: re-check the alerts right before executing; skip if they've cleared | fixed, unit-tested, live D7 |
| P4 | live run D4 | late symptom alerts produced a second plan while the first fix was being verified | one action per incident at a time; stale-attempt plans ignored | worked as designed |
| P5 | rebuild during testing | gateway restart loses open incidents | SQLite incident store keeps the record (state still in memory) | partly fixed |
| P6 | safety suite | NaN confidence executed without approval (`nan < 0.7` is False) | confidence must be a real number in [0, 1] | fixed |
| P7 | safety suite | boolean `true` accepted as confidence 1.0 | same check; analyzer schema `strict=True` | fixed |
| P8 | safety suite | list-typed action fields and a malformed `attempt`/`incident_id` crashed the responder | reject cleanly | fixed |
| P9 | live NaN check | the gateway accepted NaN/Infinity JSON; one such plan made `/approvals` and `/responses` return 500 (dashboard approvals broken) | strict JSON parsing on every gateway input; responder skips such messages | fixed |
| P10 | baseline export test | manual demo faults aren't in ground truth and contaminated "normal" training data | also drop samples near any active alert | fixed |
| P11 | report preparation | the responder's "MTTR" (incident opened → verified) clashed with the evaluation MTTR (fault start → fault gone) | renamed `open_to_verified_s` | fixed |
| P12 | analyzer comparison C2 | a prompt rule for one scenario broke another | second rule; every prompt change now checked on all samples with 2 runs | fixed on samples |
| P13 | pilot B2 | LLM self-contradiction on a live error fault (restart instead of reset) | held-out case saved; not tuned again on one incident | **open (Riddhima)** |
| P14 | first scorer run | scoring right after a run reports the last fault as unverified (verification takes 45 s) | score after the last verification has finished | procedure |

---

## 8. Objectives status (O1–O6, §2 of the plan)

| Objective | Target | Status / evidence so far |
|---|---|---|
| O1 monitor all services | 100% | 4/4 Prometheus targets up; container metrics blocked by P2 |
| O2 detection | recall ≥ 0.90, FP ≤ 10% | **stage 1 (§13): 81/81 detected, 0 FP incidents; S MTTD 27 s vs 53 s without ML.** Earlier: rules: 9/9 scenarios on real containers (§11), 0 false-positive incidents; ML: 8/9 offline, 0 FP episodes in 1.07 h, scenario 8 caught 175 s before the rule (§12) |
| O3 root cause | ≥ 80% | **stage 1: 100% in B1, B2 and S (§13).** Earlier: pilot 8/8 (B1 4/4, B2 4/4); samples LLM 18/18 (optimistic) |
| O4 safe, correct action | ≥ 85% correct, 0 unsafe | **stage 1: B1 100%, B2 96.3%, S 96.3%; 0 unsafe in 81 runs (§13).** Earlier: pilot B1 4/4, B2 3/4; **0 unsafe** in every run and 29/29 adversarial cases |
| O5 auto-resolved | ≥ 60% | **stage 1: 100% in every system (§13).** Earlier: pilot 8/8 auto-resolved and verified |
| O6 MTTR | ≥ 50% faster than manual | not measured: needs B0 (a person fixing faults by hand, timed). Unfixed faults lasted their full 90–120 s (D1, D2) |

Stage 1 (3 runs per scenario per system) is done (§13). Still needed: stages 2–3 (10 and 20 runs) and B0.

---

## 9. Caveats to state in the report

- Small n: stage 1 has 3 runs per scenario per system (§13); stages 2–3 will raise it to 10 and 20.
- All 9 scenarios are faults the runbooks were written for, so B1 vs B2 doesn't test unseen faults.
- ~~Scenarios 1, 2, 3, 8, 9 not yet run live (P2).~~ All 9 run live on 9 Oct (§11); scenario 8 with ML (§12).
- The hand-written samples were written together with the runbooks, and the prompt was tuned on them.
- One machine, one model (llama3.1:8b); no comparison with a hosted model yet.
- MTTR includes the LLM's latency on this hardware; a faster model or GPU would change B2's MTTR.

---

## 9a. Dashboard check (8 Oct 2026)

Not an evaluation: a functional check of the new Next.js dashboard (`web/`) before its first Docker run. Docker was off, so the gateway and responder ran on the host against an incident store rebuilt from `experiments/results/incident_store_snapshot.jsonl` (13 real incidents from 6 Oct), and the charts were fed by a **synthetic** Prometheus/Alertmanager.

| Check | Result |
|---|---|
| `tsc --noEmit`, `next build` | pass |
| Stats from the real store (`/api/stats`) | 13 incidents: 10 verified, 1 escalated, 2 rejected (demo approvals); plans 6 LLM / 7 runbook; mean LLM analysis 20.2 s; mean open → plan 19.9 s; mean open → verified 69.0 s |
| Incident page, real scenario 6 incident | RedisDown + symptom HighErrorRate shown; root cause redis; restart → verified (`docs/figures/web_incident_detail.png`) |
| Approval round trip | test alert → incident → test plan with confidence 0.62 → held (`confidence 0.62 < 0.7`) → rejected through the dashboard route → `rejected` in the store |
| Guards | approve without `x-dashboard` header → 403; non-allowlisted proxy paths → 404 |
| Responder tests / safety suite after adding `GET /policies` | 43/43, 29/29 (0 unsafe) |

Caveats: the overview screenshot's metrics are synthetic (`docs/figures/web_overview_synthetic_metrics.png`); the open incident and the approval in it are test data, not a scenario run. The dashboard's "open → verified" is an operational number from the store, not the evaluation's MTTR (§0 definitions).

---

## 11. All 9 scenarios on real containers, B2 (9 Oct 2026)

First run with container CPU/memory metrics: Docker Desktop's containerd image store turned off, stack rebuilt, cAdvisor now reports `name` (api-service 31 MB, frontend 27 MB, redis 10 MB at idle). Full system without ML (rules + LLM + runbook fallback + responder) = **B2**. `injector suite --scenarios 1-9 --repeat 1 --duration 180 --gap 300`, 12:32–13:31 UTC. Scored with `python experiments/score.py --system B2 --since 2026-10-09T12:30:00Z`.

| # | Scenario | MTTD | Root cause | Plan action | Action ok | End | MTTR | Verified |
|---|---|---|---|---|---|---|---|---|
| 1 | cpu-frontend | 47.0 s | frontend ✅ | reset_faults | ✅ | remediated | 89.8 s | ✅ |
| 2 | cpu-api | 47.2 s | api-service ✅ | reset_faults | – | **expired** | – | ❌ (invalid run, see below) |
| 3 | memory-api | 25.3 s | api-service ✅ | restart_container | ✅ | remediated | 82.5 s | ✅ |
| 4 | latency-api | 30.5 s | api-service ✅ | reset_faults | ✅ | remediated | 78.5 s | ✅ |
| 5 | error-api | 27.0 s | api-service ✅ | restart_container | ❌ (reset expected) | remediated | 82.5 s | ✅ |
| 6 | redis-stopped | 18.9 s | redis ✅ | restart_container | ✅ | remediated | 62.8 s | ✅ |
| 7 | frontend-stopped | 26.1 s | frontend ✅ | restart_container | ✅ | remediated | 71.9 s | ✅ |
| 8 | gradual-memory-api | **231.9 s** | api-service ✅ | restart_container | ✅ | remediated | 289.8 s | ✅ |
| 9 | cpu-latency-api | 29.9 s | api-service ✅ | reset_faults | ✅ | remediated | 94.9 s | ❌ (cut off, see below) |

| Metric | B2, 9 Oct |
|---|---|
| Detected | 9/9 (recall 100%), 0 false-positive incidents |
| MTTD | mean 53.8 s, median 29.9 s |
| Root cause correct | 9/9 |
| Plan action correct | 8/9 (88.9%); executed action correct 7/8 |
| Unsafe / collateral actions | 0 / 0 |
| Auto-resolved | 8/9 (88.9%) |
| MTTR | mean 106.6 s, median 82.5 s (n = 8) |
| Plan latency | mean 28.7 s, median 27.2 s; 100% LLM plans |

Findings:
- **Scenarios 1, 2, 3, 8 and 9 fired on real containers for the first time** (HighCPU, HighMemory). Every scenario is now detected by the rules.
- **Scenario 8 (gradual leak) is caught by the rule only at the end of the ramp:** memory rose ~50 MB per 30 s to 427 MB (83% of 512 MB) and HighMemory fired 232 s after the leak started. This is the gap the ML detector is meant to close (§12).
- Scenario 5: the LLM again chose `restart_container` over `reset_faults` (same as the pilot, §3). Effective, but not the least disruptive action.
- **Scenario 2 is not a valid run.** The incident opened at 12:39:45 but the analyzer only sent the request to Ollama at 12:43:09 (Ollama log: 41 s request ending 12:43:50); by then the fault had cleared and the responder correctly skipped the action ("already cleared"). Prometheus got 19 of 60 expected `up{job="frontend"}` samples in the 5 minutes to 12:44 and the injector cleared the fault 2 minutes after its planned end: the whole Docker VM stalled for ~3 min. That coincided with installing scikit-learn and building images on the host during the run. To be rerun.
- **Scenario 9 verification was cut off by a redeploy:** reset at 13:31:26, fault gone at 13:31:27 (`remediated`), but the gateway and responder were rebuilt at 13:31:45, before the 45 s verify. The fix worked; only the "verified" record is missing.
- n = 1 per scenario. A check that every scenario works end to end, not the evaluation.

Raw data: `experiments/results/ground_truth_check_9oct.csv` (ground truth, all runs so far), `experiments/results/check_9oct_b2_runs.csv` (per-run scores), `experiments/results/incident_store_check_9oct.jsonl` (every gateway message 12:30–13:31 UTC; no `fault_*` data).

---

## 12. ML anomaly detector (9 Oct 2026)

**Model** (`ml/`, §6.2): one per service; robust z-scores against the training median (scale = max(1.4826·MAD, floor)), only the "worse" direction counts; plus an Isolation Forest over the z-vector (99.5% training quantile). Anomalous if any CPU/memory/latency/error metric has z ≥ 4, or the forest flags it and one has z ≥ 2. Reported after 2 anomalous polls in a row (15 s poll), re-posted while it lasts.

**Training:** 78 min of normal traffic under Locust, 13:34–14:52 UTC, no faults (`experiments/baseline_20261009_1334.csv`, 945 rows = 315 per service, 0 dropped). Held-out last 20% (63 samples per service): **0 flagged** for all three services (single and sustained). Source: `experiments/results/ml_detector_report_9oct.json`.

### 12a. Offline replay over the B2 check run (§11)

The trained detector replayed (`ml/replay.py`) over the Prometheus history of the §11 run, 12:30–13:34 UTC, without dropping anything. Detection only; nothing acted on these anomalies.

| # | Scenario | ML detected | Delay | First anomaly | Rule MTTD (§11) |
|---|---|---|---|---|---|
| 1 | cpu-frontend | ✅ | 32 s | frontend cpu | 47.0 s |
| 2 | cpu-api | ✅ | 33 s | api-service cpu | 47.2 s |
| 3 | memory-api | ✅ | 31 s | api-service mem | 25.3 s |
| 4 | latency-api | ✅ | 38 s | api-service p95 | 30.5 s |
| 5 | error-api | ✅ | 35 s | api-service err | 27.0 s |
| 6 | redis-stopped | ✅ | 27 s | api-service err (symptom) | 18.9 s |
| 7 | frontend-stopped | ❌ | – | – | 26.1 s |
| 8 | gradual-memory-api | ✅ | **57 s** | api-service mem | **231.9 s** |
| 9 | cpu-latency-api | ✅ | 23 s | api-service p95, cpu | 29.9 s |

Recall 8/9; **0 false-positive episodes in 1.07 h**. Source: `experiments/results/ml_replay_check_9oct.json`.

- **Scenario 8: ML is ~175 s ahead of the rule** (57 s vs 232 s). This is the case the ML detector is for.
- Scenario 7 is missed by design: a stopped container reports no metrics, and missing values count as typical. ServiceDown covers it.
- Scenario 6: ML sees the symptom (api-service errors), not redis, for the same reason (redis metrics disappear). Root cause still comes from RedisDown + topology.
- On the faults the rules already cover, ML is faster for CPU (rule needs the 30 s window + `for: 20s`) and slightly slower for the rest (the 2-poll persistence rule).

### 12b. Live runs, full system S (rules + ML + LLM + runbook fallback + responder)

`ml-detector` running; scenarios 2 and 8 (`injector suite --scenarios 2,8 --gap 300`, 14:53–15:02 UTC) and scenario 2 again after a fix (15:06 UTC). Scored with `python experiments/score.py --system S --since 2026-10-09T14:53:00Z`.

| # | Scenario | Detected by | MTTD | Action | MTTR | Verified | Attempts |
|---|---|---|---|---|---|---|---|
| 2 | cpu-api (1st) | ML, then HighCPU | 23.4 s | reset_faults ✅ | 63.2 s | ❌ (see below) | 2 |
| 8 | gradual-memory-api | **ML only** | **51.3 s** | restart_container ✅ | **99.6 s** | ✅ | 1 |
| 2 | cpu-api (after fix) | ML, then HighCPU | 34.7 s | reset_faults ✅ | 72.3 s | ✅ | 1 |

Summary (n = 3): recall 3/3, 0 false-positive incidents, root cause 3/3, action 3/3, 0 unsafe, auto-resolved 3/3, MTTR mean 78.4 s.

- **Scenario 8, B2 → S: MTTD 232 s → 51 s, MTTR 290 s → 100 s.** The incident opened from the ML anomaly alone (`sources: ["ml"]`, top feature `mem`), the LLM chose restart_container (confidence 0.8), the responder executed it and verified it ("alerts no longer firing, no active ML anomaly"). HighMemory never fired.
- **Bug found and fixed (scenario 2, 1st run):** the verifier treats an ML anomaly refreshed in the last `ML_FRESH_SECONDS` as still active. With 25 s, a refresh 22 s after the CPU reset (the 30 s rate window still held fault samples, z = 4.16) was still "active" at the 45 s verify, so the incident went to re-analysis although the fault was gone within a second of the reset (injector `end` 14:54:17.7). Lowered to 20 s (one 15 s poll plus margin). The rerun verified on attempt 1.
- Fixes needed in the gateway and responder before any of this worked (found while building, before running): (1) every anomaly POST was an incident "update", so a detector re-posting every 15 s would have triggered a new LLM analysis each time; a repeat from the same service now only refreshes it. (2) The responder's pre-check only looked at firing alerts, so an ML-only incident would have been skipped as "already cleared"; it now also checks `ml_active`.

Caveats: n = 1–2 per scenario; scenario 8 is the only ML-only case in the scenario set; the detector was trained on 78 min of one traffic level (5 users), so a different load would need retraining; thresholds (z 4 / 2, floors, sustain 2) were chosen before the runs, not tuned on them.

Raw data: `experiments/results/ml_detector_report_9oct.json` (training report, holdout), `ml_replay_check_9oct.json` (12a), `ml_rerun_9oct_s_runs.csv` (12b per-run scores), `incident_store_ml_9oct.jsonl` (every gateway message from 14:53 UTC; no `fault_*` data), `ml_detector_anomalies_9oct.log` (detector log lines), `ground_truth_check_9oct.csv` (all ground truth).

---

## 13. §10 evaluation, stage 1: B1 vs B2 vs S, 3 runs per scenario (11–12 Oct 2026)

**Setup.** `experiments/run_eval.py run --stage 1`: 9 scenarios × 3 rounds × 3 systems = 81 runs, 11 Oct 20:27 UTC – 12 Oct 04:57 UTC, then 4 runs redone 05:03–05:23 UTC (below). Each round is the 9 scenarios in a shuffled order fixed by (system, round); rounds interleaved B1, B2, S, B1, ... Duration 180 s (scenario 8: 300 s), gap 300 s, Locust 5 users, one Mac (Docker Desktop), llama3.1:8b on Ollama, ML model from 9 Oct (§12), unchanged. B1 = `ANALYZER_MODE=runbook`, ml-detector stopped; B2 = LLM, ml-detector stopped; S = LLM + ML + runbook fallback. Scored with `run_eval.py score --stage 1` (= `score.py` per system, `--max-gap 900`). B0 (manual) not run.

**Runner bug found and fixed (runs redone).** The runner switched to the next system as soon as a block's last run ended, while that run's incident was still open (updates, verify 45 s after the action). In 2 B1 runs (scenario 6, rounds 2 and 3) the freshly switched LLM analyzer produced an extra plan for the B1 incident (only the token count was affected; the executed action came from the runbook); in 2 S runs (round 1 scenario 4, round 2 scenario 8) the ML detector was stopped before the verify, which could make "verified" look better. Fixed: the runner now waits out the gap before switching systems and before restoring the stack (`test_gap_is_waited_before_switching_and_restoring`). The 4 runs were voided (`runs.csv` status `void`) and redone. Scores before the redo are kept in `eval_stage1_before_redo_*`; the only summary changes were B1 tokens (2574 → none) and S MTTD/MTTR means (27.4 → 27.2 s, 67.7 → 67.8 s).

### Summary (n = 27 runs per system)

| Metric | B1 rules + runbooks | B2 rules + LLM | **S full system** | Target (§2) |
|---|---|---|---|---|
| Detected (recall) | 27/27 (100%) | 27/27 (100%) | 27/27 (100%) | O2 ≥ 90% |
| False-positive incidents | 0 | 0 | 0 | |
| MTTD mean / median | 52.2 / 29.0 s | 52.6 / 28.0 s | **27.2 / 24.6 s** | |
| Root cause correct (first plan) | 100% | 100% | 100% | O3 ≥ 80% |
| Executed action correct | 100% | 96.3% (26/27) | 96.3% (26/27) | O4 ≥ 85% |
| Unsafe actions executed | 0 | 0 | 0 | O4 = 0 |
| Auto-resolved (fault gone before planned end) | 100% | 100% | 100% | O5 ≥ 60% |
| MTTR mean / median | 74.9 / 50.9 s | 101.9 / 80.6 s | **67.8 / 65.9 s** | O6 vs B0 |
| MTTR mean without scenario 8 | 52.4 s | 79.0 s | 65.1 s | |
| Verified on attempt 1 | 100% | 100% | 96.3% | |
| Escalated | 0% | 0% | 0% | |
| Plan latency mean | 0.2 ms | 26.1 s (22.8–31.7) | 24.2 s (14.2–30.9) | |
| LLM calls per incident (mean) | 0 | 1.2 | 1.8 | |
| Tokens per incident (mean, in / out) | – | 3065 / 192 | 4484 / 275 | |

### Per scenario: MTTD / MTTR in seconds (mean of 3), correct executed actions

| # | Scenario | B1 | B2 | S |
|---|---|---|---|---|
| 1 | cpu-frontend | 45 / 65, 3/3 | 46 / 92, 3/3 | 29 / 64, 3/3 |
| 2 | cpu-api | 47 / 67, 3/3 | 46 / 92, 3/3 | 30 / 66, 3/3 |
| 3 | memory-api | 27 / 58, 3/3 | 27 / 85, 3/3 | 23 / 70, 3/3 |
| 4 | latency-api | 30 / 50, 3/3 | 28 / 77, 3/3 | 28 / 70, 3/3 |
| 5 | error-api | 26 / 47, 3/3 | 27 / 77, **2/3** | 24 / 64, **2/3** |
| 6 | redis-stopped | 19 / 39, 3/3 | 21 / 66, 3/3 | 18 / 57, 3/3 |
| 7 | frontend-stopped | 23 / 43, 3/3 | 23 / 68, 3/3 | 24 / 68, 3/3 |
| 8 | gradual-memory-api | 224 / 255, 3/3 | 226 / 285, 3/3 | **45 / 89**, 3/3 |
| 9 | cpu-latency-api | 29 / 49, 3/3 | 28 / 76, 3/3 | 25 / 61, 3/3 (1 needed attempt 2) |

### Findings

- **ML detection (B2 → S): MTTD mean 52.6 → 27.2 s.** Scenario 8 (gradual leak): 226 → 45 s detection, 285 → 89 s MTTR, in all 3 runs, before HighMemory fired. CPU scenarios 1 and 2: ~46 → ~30 s (the rule needs the 30 s window + `for: 20s`). On the other scenarios the rules are about as fast.
- **Runbooks vs LLM (B1 → B2): same accuracy, slower.** On these 9 known scenarios the runbooks were 27/27 correct and the LLM 26/27. The LLM adds ~25 s per plan, so B2's MTTR is ~27 s worse (79 vs 52 s without scenario 8). The scenario set doesn't contain faults outside the runbooks, where the LLM would be expected to help; state this in the report.
- **S vs B1:** MTTR mean 67.8 vs 74.9 s, only because of scenario 8; without it B1 is faster (52 vs 65 s) for the same reason as above.
- **Wrong action, scenario 5 (B2 run `9f954034`, S run `3175f996`):** root cause right (api-service, `error_spike`), but the LLM chose `restart_container` instead of `reset_faults` (confidence 0.95 and 0.80). The restart also removed the fault (MTTR 84 / 69 s), so it is "wrong" only against the §10 expected action, not harmful. Same weakness as in the pilot (§3).
- **Not verified on attempt 1 (S, scenario 9, round 3):** the reset removed the fault, but an ML anomaly on api-service was refreshed within the last 20 s at the 45 s verify (the 30 s rate windows still held fault samples; same effect as §12b), so the verifier re-analyzed; attempt 2 was skipped as "already cleared" and the incident resolved. No extra action executed. MTTR (injector) unaffected.
- **Extra LLM calls in S (cost):** 48 plans for 27 incidents in S (20 more than one per attempt), 33 for 27 in B2 (6 more). An incident `updated` by a later alert or anomaly is re-analyzed although the responder is already acting on the first plan (it ignores the second: one plan per incident at a time). In S the ML anomaly usually opens the incident and the alerts join later, so this happens more. Costs ~25 s of Ollama time and ~2.5k tokens per extra plan; doesn't change any action. Possible fix (not made, to keep stages comparable): don't re-analyze an `updated` incident while a plan for the same attempt is being executed.
- **Every run ended `remediated`; 0 unsafe actions; 0 escalations; 0 false-positive incidents** in 8.5 h of runs.

**Caveats.** n = 3 per scenario per system (stage 1 of 3); the means are not yet stable (MTTR stdev ~66 s for B1/B2 because of scenario 8, 10 s for S). One machine, one model; LLM latency depends on this Mac. All faults are ones the runbooks were written for. The ML model was trained at the same load (5 users) as the evaluation. B0 still missing, so O6 can't be assessed.

Raw data: `eval_stage1_B1_runs.csv`, `eval_stage1_B2_runs.csv`, `eval_stage1_S_runs.csv` (per-run scores), `eval_stage1_summary.json` (summaries), `eval_stage1_before_redo_*` (scores before the 4 runs were redone), `eval_stage1_manifest.csv` (which run is which system/round, incl. the 4 voided), `eval_stage1_ground_truth_{B1,B2,S}.csv` (injector ground truth, incl. the voided runs), `eval_stage1_run_eval.log` and `eval_stage1_console.log` (runner and injector logs), `incident_store_eval_stage1.jsonl` (775 gateway messages from 11 Oct 20:25 UTC; no `fault_*` data).

---

## 14. Extra scenarios, SF and soak: tooling and live checks (12 Oct 2026)

Built for the evaluation gaps found in §13 (all 9 core scenarios are faults the runbooks cover and one action fixes; no false alarm, approval or escalation happened). No results yet; this records what was built and how it was checked.

**Demo app change (both copies, rebuilt 15:11 UTC, between stage 2 sessions):** `/inject` takes optional `delay_s` (latency) and `rate` (share of failing requests). Without them the faults behave exactly as before (5 s, every request): checked with the Flask test client on both apps (defaults, 5% → 4.9-5.0% errors over 2000 requests, 0.2 s → 0.20 s, bad values rejected incl. NaN and booleans). Stage 2 runs from round 4 slot 6 onwards use the rebuilt images; scenarios 1-9 don't pass the new parameters, so their behaviour is unchanged.

**Live checks of the new faults** (injector functions run in the injector container against the real containers, load generator and ML detector stopped so nothing alerted):

| Check | Result |
|---|---|
| 10 corrupted cache: api-service `/data` → 503 ("not an integer") while Redis is up | ✅ |
| 10: still corrupted after a Redis restart (Redis saves to `/data`, `save 3600 1 300 100 60 10000`) | ✅ only `flush_cache` fixes it |
| 10: `FLUSHALL` fixes it; injector cleanup fixes it | ✅ |
| 11 slow Redis under steady requests (one every 0.2 s): no errors, p95 1.44 s (p50 0.01 s) | ✅ above the 1 s rule |
| 11: a Redis restart ends it; cleanup ends it; it ends by itself after its duration | ✅ |
| 12 subtle latency: 0.60-0.61 s per request | ✅ under the 1 s rule |
| 13 subtle errors: 4.0% over 400 requests | ✅ under the 10% rule |
| 14 recurring (shortened to 40 s, fixed twice by hand): re-injected after each fix, `cleared=2`, `expired`; never fixed: `cleared=0`, `expired` | ✅ after a fix (below) |
| `reset` undoes both Redis faults | ✅ |

- **Bug found and fixed:** the first recurring check reported `cleared=3` for 2 fixes. The re-injected fault was rounded down to whole seconds, expired just before the planned end, and was counted as a fix. Now rounded up, and a clear in the last 5 s isn't counted.
- The first slow-Redis check sent 8 requests back to back (0.6 s in total), so most fell between pauses; re-checked with spaced requests as above.
- One incident (`inc-261012-151418-6`, HighLatency/api-service, 15:14 UTC) came from the recurring check's 5 s latency. The responder skipped its action ("already cleared"); it is outside every evaluation run.

**Expected-action scoring** (`score.py ACCEPTABLE`): 10 `flush_cache`; 11 `restart_container`; 12, 13 reset or restart; 14 reset or restart as the first action, escalation as the outcome. `score.py` now also reports `approval_requested` and the incident's `action_log` (every responder outcome in order).

**ML expectation for 13:** the error scale is 0.02, so 5% errors is z = 2.5, under the strong threshold (4); only the Isolation Forest path (z ≥ 2 and forest score above its threshold) can flag it. Whether it does is part of the result.

Raw data: none yet (runs not started).

---

## 15. Extra scenarios, round 1 (12 Oct 2026, 15:35-18:40 UTC)

**Superseded by §18b** (n = 10 per cell, 23 Oct 2026). Kept for the round-1 behaviour notes.

`run_eval.py run --suite extra --stage 1 --rounds 1`: scenarios 10-14 once each on B1, B2, S, and 3, 4, 6, 8 once on SF (19 runs). Same setup as §13 (Locust 5 users, llama3.1:8b, ML model of 9 Oct, gap 300 s). Scored with `run_eval.py score --suite extra --stage 1`. **n = 1 per cell: behaviour, not rates.**

| # | Scenario | B1 (runbooks) | B2 (LLM) | S (full) | Expected |
|---|---|---|---|---|---|
| 10 | corrupted cache | detected 31 s; blamed api-service: reset → restart → **escalated** | same (LLM: api-service, reset ×3) → **escalated** | LLM: restart api-service → **escalated** | flush_cache (approval) |
| 11 | slow Redis | detected 28 s; blamed api-service: reset → restart → **escalated** | same → **escalated** | same → **escalated** | restart redis |
| 12 | subtle latency 0.6 s | **not detected** | **not detected** | ML 29 s; reset api-service → **verified** | reset / restart |
| 13 | subtle errors 5% | **not detected** | **not detected** | ML **170 s**; reset planned (conf 0.70) but **skipped** "already cleared"; fault ran its full 300 s | reset / restart |
| 14 | recurring latency | reset → restart → **escalated** | reset → restart → **escalated** | reset → restart → **escalated** | escalation |

SF (LLM unreachable; every plan from the runbooks, `fallback_reason = unreachable`): 3 memory → restart api-service, verified; 6 Redis stopped → restart redis, verified; 8 gradual memory → ML 58 s, restart api-service, verified; **4 latency → escalated, not fixed** (below).

Summary (`eval_extra_round1_summary.json`): 0 unsafe actions, 0 false-positive incidents, 0 approval requests in all four systems. Detected: B1 3/5, B2 3/5, S 5/5, SF 4/4.

### Findings

- **Misleading faults (10, 11): neither the runbooks nor the LLM found Redis.** All three systems blamed api-service, the service with the errors/latency. The policy layer still stopped it safely: reset (attempt 1) → the reset is in cooldown, so the plan's fallback restart ran (attempt 2) → escalation (attempt 3). No approval was requested because no plan proposed `flush_cache`.
- **The LLM ignored the history on re-analysis.** On 10, 11 and 14 it recommended the same `reset_faults/api-service` at attempts 2 and 3, although `history.previous_actions` listed it as already tried and failed. The change of action came from the policy validator (cooldown → fallback), not from the LLM. Same anchoring as noted in CLAUDE.md for the few-shot examples. The runbooks do follow the history (reset → restart → escalate).
- **Below-threshold faults (12, 13): only S detects them**, as designed. 12 was found at 29 s and fixed. 13 was found late (170 s, via the Isolation Forest path as expected for z = 2.5) and then **not acted on**: by the time the plan arrived the anomaly hadn't been refreshed within `ML_FRESH_SECONDS` (20 s), so the responder's pre-check treated the incident as cleared. Intermittent ML-only anomalies can fall through the pre-check.
- **Recurring fault (14): escalated in every system** after reset and restart failed. Bounded remediation works live.
- **SF on scenario 4: premature escalation.** The incident opened from an ML latency anomaly before HighLatency fired. With the LLM down, the runbooks have no ML-only latency rule (only memory), so the first plan was `escalate` (confidence 0.5), which the responder executed. The better runbook plan (reset, confidence 0.8) arrived once the alert fired, but the incident was already escalated. Plain S doesn't hit this because the LLM handles ML-only incidents.
- **LLM cost on the hard cases:** 7690 / 6160 prompt tokens per incident in B2 / S (three attempts each), against ~3000 on the core set.

### What it means (to confirm with rounds 2-3)
- The LLM's advantage over runbooks is **not** shown on these misleading faults with this prompt and model; the safety net (cooldown, fallback, max attempts, escalation) is what kept them bounded.
- Possible improvements, **not made** (they change the system under test; decide after the evaluation): make the prompt enforce `previous_actions` (no repeat of a failed action, consider the dependency next); an ML-only runbook for latency/error anomalies; let the pre-check use a longer ML window for ML-only incidents.

Raw data: `eval_extra_round1_{B1,B2,S,SF}_runs.csv`, `eval_extra_round1_summary.json`, `eval_extra_round1_by_scenario.csv` (scores), `eval_extra_round1_manifest.csv`, `eval_extra_round1_ground_truth_{B1,B2,S,SF}.csv`, `eval_extra_round1_console.log`, `incident_store_extra_round1.jsonl` (194 gateway messages 15:34-18:41 UTC; no `fault_*` data).

---

## 16. Soak test 1: no faults, 10 h, system S (12-13 Oct 2026)

`run_eval.py soak --hours 10 --events`: full system S (rules + ML + LLM + responder), no fault injected, 12 Oct 19:01 → 13 Oct 05:01 UTC (10.0 awake hours; the Mac didn't sleep). A harmless event every 30 min, 19 in total, cycling: restart frontend, load 5 → 10 users for 10 min, restart api-service, load 5 → 2 users for 10 min. Every incident opened in the window counts as a false alarm. Scored with `run_eval.py soak-score`.

| Metric | Result |
|---|---|
| Awake hours | 10.0 |
| Harmless events | 19 (5 frontend restarts, 5 load increases to 10 users, 5 api-service restarts, 4 load decreases to 2 users) |
| **False alarms (incidents)** | **0** (0.0 per hour) |
| Actions executed | 0 |

Checks that the zero is real: the load events took effect (frontend 4.94 req/s normally, 9.85 at 10 users, 1.98 at 2 users, from Prometheus); the ML detector was running throughout (started 17:22 UTC; it logs only anomalies and had flagged the last extra-suite faults at 18:29 and 18:34 UTC, just before the soak).

**Why no alarm at 10 users, although the ML model was trained at 5:** the detector only scores the "worse" direction of CPU, memory, latency and errors; request rate itself isn't a "bad" metric, and doubling the load raises CPU/latency far less than the z-score threshold (CPU scale floor 0.05 against a median of ~0.02). Restarts last a few seconds, below the rules' `for: 20s` and the detector's 2-poll persistence.

**Caveats:** one 10 h window at one time of day; synthetic Locust traffic with a 2-10 user range; no deploys with code changes, no noisy neighbours. A larger load change (e.g. 50 users) or bursty traffic may behave differently. Retraining on several load levels (planned) can be compared against this baseline.

Raw data: `soak_1_windows.csv`, `soak_1_events.csv` (event times), `soak_1_summary.json` (soak-score output), `soak_1_console.log`.

---

## 17. §10 evaluation, stage 2 round 4: B1 vs B2 vs S (12-13 Oct 2026)

**Setup.** As §13 (same stack, model, ML model from 9 Oct, analyzer behaviour unchanged). `run_eval.py run --stage 2 --rounds 1`. Round 4 = 27 runs: B1 slots 1-5 ran 12 Oct 11:36-12:03 UTC (the block stopped when the Mac slept, Step 14), the other 22 runs 13 Oct 16:30-18:49 UTC on mains power, no sleep. Scored with `gateway/.venv/bin/python experiments/run_eval.py score --stage 2`, which scores every stage-2 run so far, i.e. rounds 1-4 (36 per system).

### Round 4 only (n = 9 per system)

| Metric | B1 | B2 | S |
|---|---|---|---|
| Executed action correct | 9/9 | 9/9 | 8/9 |
| Auto-resolved | 9/9 | 9/9 | 8/9 |
| Verified | 9/9 | 9/9 | 8/9 |
| Escalated | 0 | 0 | 1 |
| MTTD mean | 52.0 s | 52.3 s | 27.9 s |
| MTTR mean | 70.4 s | 104.5 s | 70.6 s |
| LLM calls | 0 | 10 | 16 |

### Rounds 1-4 so far (n = 36 per system; stage 2 is 90)

| Metric | B1 | B2 | S |
|---|---|---|---|
| Recall | 100% | 100% | 100% |
| False-positive incidents | 0 | 0 | 0 |
| MTTD mean | 52.2 s | 52.5 s | 27.3 s |
| Root cause correct | 100% | 100% | 97.2% |
| Executed action correct | 100% | 97.2% | 97.1% |
| Unsafe actions executed | 0 | 0 | 0 |
| Auto-resolved | 100% | 100% | 97.2% |
| MTTR mean | 73.8 s | 102.5 s | 68.4 s |
| Verified | 100% | 100% | 94.4% |
| Escalated | 0% | 0% | 2.8% |
| Plan latency mean | 0.3 ms | 26.9 s | 24.5 s |
| Tokens per incident (in / out) | – | 2993 / 187 | 4482 / 275 |

Per scenario: `eval_stage2_by_scenario.csv`. The picture is the same as stage 1 (§13): ML halves MTTD (scenario 8: ~225 → 46 s), the LLM adds ~25-30 s to MTTR, B1 and B2 are equally accurate on these scenarios.

### Finding: an escalation from a fallback plan blocked a correct LLM plan (S, scenario 5, run `a84a748a`, incident `inc-261013-182714-19`)

1. 18:27:24 UTC: the ML anomaly (api-service errors) opened the incident; the alerts joined 13 s later (`updated`).
2. 18:27:49: the analyzer's plan for the `open` event: the LLM answered below the 0.7 confidence threshold (`fallback_reason=low_confidence`, 24.2 s), the runbook fallback found no runbook for the ML-only picture (`runbook/no-match`, root frontend, `escalate`). The responder escalated the incident.
3. 18:28:04: the plan for the `updated` event (alerts included): LLM, root api-service, `error_spike`, `restart_container:api-service`, confidence 0.95. The responder skipped it: "incident already handled".
4. Nothing was executed; the fault expired at its planned end (181 s). Scored as not auto-resolved, escalated, root cause wrong (first plan).

Not seen in the other 35 core S runs (stage 1 and the rest of round 4; checked in `incidents.db`: no other runbook escalation in core S runs). It is the same mechanism as the extra LLM calls in §13 (an `updated` incident is re-analyzed while the first plan is being handled), but here the first plan was the weaker one. Possible fixes (not made, to keep stage 2 comparable): treat a `runbook/no-match` escalation as provisional while a newer plan for the same attempt is pending, or wait for the settle of an ML-only incident until a rule alert joins or a timeout passes. Either changes system S, so stages 1-2 would have to be reported separately or rerun.

**Caveats.** As §13. One escalation in 36 runs; the rate is not yet stable.

Raw data: `eval_stage2_{B1,B2,S}_runs.csv` (per-run scores, rounds 1-4), `eval_stage2_summary.json`, `eval_stage2_by_scenario.csv`, `eval_stage2_round4_manifest.csv` (`runs.csv` after the block), `eval_stage2_round4_ground_truth_{B1,B2,S}.csv`, `eval_stage2_round4_console.log` and `eval_stage2_round4_run_eval.log` (runner and injector logs), `incident_store_eval_stage2_round4.jsonl` (242 gateway messages from the two block windows; no `fault_*` data).

---

## 18. Long evaluation block: core rounds 5-20 + extra rounds 2-10 (19-22 Oct 2026) — done

**Setup.** One unattended block, started 19 Oct 15:37 UTC by `experiments/results/long_run_19oct.sh`: `run_eval.py run --stage 3` (core rounds 5-20, 432 runs, B1/B2/S), then `run_eval.py run --suite extra --stage 3` (extra rounds 2-10, 171 runs, B1/B2/S/SF). The script retries a block up to 5 times after an `Abort` (600 s apart) and stops on Ctrl+C/kill. Expected ~77 h (core ~48 h, extra ~28 h). Stack rebuilt 19 Oct with `docker compose up -d --build`; gateway tests 23/23 before the start; Ollama `llama3.1:8b`; ML model from 9 Oct; sleep disabled.

**Changed since rounds 1-4 (caveat).** The gateway now includes the 16 Oct grouping change: once the responder reports `verified`, an incident closes when no ML anomaly is < `ML_FRESH_SECONDS` = 20 s old (was 60 s), so a fault started soon after a fix opens a new incident. Core rounds 1-4 (§17) ran without it, rounds 5-20 with it. Report stage 2/3 numbers split at round 4, or check per round that the split makes no difference, before pooling.

**Core block:** 432 runs in one attempt (no `Abort`, no retry, no run voided), 19 Oct 15:37 → 21 Oct 14:44 UTC (47.1 h). **Extra block:** 171 runs in one attempt (no `Abort`, no run voided), 21 Oct 14:44 → 22 Oct 18:21 UTC (27.6 h); the runner then restored system S (`ANALYZER_MODE=llm`, ml-detector running). Results in §18b.

### 18a. Core stage 3 final: B1 vs B2 vs S, 20 rounds (n = 180 runs per system)

Scored 21 Oct 2026 with `gateway/.venv/bin/python experiments/run_eval.py score --stage 3` (every core run: rounds 1-20, 4 voided runs excluded; `--max-gap 900`). This supersedes the stage 1 (§13) and stage 2 (§17) summaries as the headline numbers.

| Metric | B1 rules + runbooks | B2 rules + LLM | **S full system** | Target (§2) |
|---|---|---|---|---|
| Detected (recall) | 180/180 (100%) | 180/180 (100%) | 180/180 (100%) | O2 ≥ 90% |
| False-positive incidents | 0 | 0 | 0 | |
| MTTD mean / median (sd) | 53.1 / 29.2 s (61.2) | 52.8 / 28.4 s (61.6) | **29.0 / 26.4 s (9.1)** | |
| Root cause correct (first plan) | 100% | 100% | 97.2% (175/180) | O3 ≥ 80% |
| Executed action correct | 100% | 92.2% (166/180) | 93.9% | O4 ≥ 85% |
| Unsafe actions executed | 0 | 0 | 0 | O4 = 0 |
| Auto-resolved | 100% | 100% | 99.4% (179/180) | O5 ≥ 60% |
| MTTR mean / median (sd) | 75.3 / 50.4 s (64.0) | 104.9 / 83.0 s (64.5) | **74.1 / 71.6 s (15.3)** | O6 vs B0 |
| MTTR mean without scenario 8 | 53.0 s | 82.3 s | 70.8 s | |
| Verified | 100% | 100% | 97.8% | |
| Needed a 2nd attempt | 0 | 0 | 7 runs | |
| Escalated | 0% | 0% | 0.6% (1 run) | |
| Plan latency mean | 0.4 ms | 28.4 s | 27.0 s | |
| LLM calls (total, 180 incidents) | 0 | 210 | 306 | |
| Tokens per incident (mean, in / out) | – | 2917 / 180 | 4284 / 261 | |

Per scenario (MTTD / MTTR mean in s, correct executed actions of 20; `eval_stage3_by_scenario.csv`):

| # | Scenario | B1 | B2 | S |
|---|---|---|---|---|
| 1 | cpu-frontend | 47 / 67, 20 | 46 / 95, 20 | 31 / 68, 20 |
| 2 | cpu-api | 46 / 66, 20 | 46 / 95, 20 | 30 / 68, 20 |
| 3 | memory-api | 27 / 57, 20 | 27 / 86, 20 | 24 / 73, 20 |
| 4 | latency-api | 29 / 49, 20 | 29 / 80, 20 | 27 / 76, **18** |
| 5 | error-api | 26 / 46, 20 | 26 / 82, **6** | 24 / 68, **12** |
| 6 | redis-stopped | 22 / 42, 20 | 22 / 70, 20 | 21 / 71, **18** |
| 7 | frontend-stopped | 27 / 47, 20 | 26 / 73, 20 | 27 / 72, 20 |
| 8 | gradual-memory-api | 224 / 254, 20 | 225 / 285, 20 | **51 / 100**, 20 |
| 9 | cpu-latency-api | 29 / 49, 20 | 29 / 80, 20 | 27 / 70, 20 |

**Findings**
- **ML detection (B2 → S): MTTD 52.8 → 29.0 s**, and far less spread (sd 61.6 → 9.1 s). Scenario 8 (gradual leak): 225 → 51 s detection, 285 → 100 s MTTR, in all 20 runs. CPU scenarios 1-2: ~46 → ~30 s. Same picture as stages 1-2, now at n = 20 per cell.
- **Runbooks vs LLM (B1 → B2): runbooks are as accurate and faster on these 9 known faults.** B1 100% correct actions; B2 92.2%, all 14 misses on scenario 5 (`restart_container` instead of `reset_faults`; root cause right; the restart also cleared the fault, so not harmful). The LLM adds ~28 s per plan: MTTR without scenario 8 is 53.0 s (B1) vs 82.3 s (B2). As in §13: the core set contains only faults the runbooks were written for.
- **S vs B1: MTTR mean 74.1 vs 75.3 s.** S is ahead only because of scenario 8; without it B1 is faster (53.0 vs 70.8 s). S has the most predictable recovery (MTTR sd 15.3 s vs ~64 s).
- **The verify loop repaired every S misdiagnosis.** 4 S runs had the wrong root cause on the first plan: scenario 6 (`1ffdf0ca`, `358296f4`: api-service blamed for Redis being down; restart/reset api-service → unresolved → attempt 2 restarted redis → verified) and scenario 4 (`61b789ad`, `ac40dc66`: frontend blamed for api-service latency; reset frontend → unresolved → attempt 2 reset api-service → verified). MTTR 124-140 s instead of ~70 s, no harm, no escalation. 7 S runs needed a 2nd attempt in total.
- **The one S escalation is still the round-4 run `a84a748a`** (§17 finding: an early runbook `escalate` for an ML-only incident blocked a correct LLM plan). It did not happen again in rounds 5-20 (0/144).
- **Every run of B1 and B2, and 179/180 of S, ended `remediated`; 0 unsafe actions; 0 false-positive incidents** over 540 runs.

**Rounds 1-4 vs 5-20 (the 16 Oct gateway change, see above).** Checked per split before pooling:

| System | Rounds | n | MTTD mean | MTTR mean | Correct actions | Escalated |
|---|---|---|---|---|---|---|
| B1 | 1-4 / 5-20 | 36 / 144 | 52.2 / 53.3 s | 73.8 / 75.7 s | 36 / 144 | 0 / 0 |
| B2 | 1-4 / 5-20 | 36 / 144 | 52.5 / 52.9 s | 102.5 / 105.5 s | 35 / 131 | 0 / 0 |
| S | 1-4 / 5-20 | 36 / 144 | 27.3 / 29.5 s | 68.4 / 75.4 s | 34 / 134 | 1 / 0 |

B1 and B2 are within ~2-3 s. S's MTTR is 7 s higher in rounds 5-20; the 4 two-attempt misdiagnosis runs (all in rounds 10-20, +55-70 s each) account for about 2 s of that. The rest is small against S's sd of 15 s. Pooling is reasonable; state the split in the report.

**Caveats.** One machine, one model (llama3.1:8b), LLM latency depends on this Mac. All 9 core faults are ones the runbooks cover and one action fixes (the extra suite tests the rest). ML model trained at the same load (5 users) as the evaluation. B0 (manual) not run, so O6 can't be assessed against a human baseline.

Raw data: `eval_stage3_{B1,B2,S}_runs.csv` (per-run scores, rounds 1-20), `eval_stage3_summary.json`, `eval_stage3_by_scenario.csv`, `eval_stage3_manifest.csv` (`runs.csv` after the core block, incl. the 4 voided runs), `eval_stage3_ground_truth_{B1,B2,S}.csv`, `eval_stage3_run_eval.log`, `eval_core_r5-20_console.log`. Gateway messages: `incident_store_long_run_19-22oct.jsonl` (§18b).

### 18b. Extra suite final: scenarios 10-14 on B1/B2/S, SF on 3/4/6/8 (n = 10 per scenario and system)

Scored 23 Oct 2026 00:06 IST with `gateway/.venv/bin/python experiments/run_eval.py score --suite extra --stage 3` (rounds 1-10: round 1 is §15, rounds 2-10 from this block). Supersedes the n = 1 table in §15. Same stack, model and ML model as the core suite. SF = system S with `OLLAMA_URL` pointed at a closed port (every plan from the runbooks).

| Metric | B1 | B2 | S | SF (LLM down) |
|---|---|---|---|---|
| Runs | 50 | 50 | 50 | 40 |
| Detected (recall) | 30/50 (60%) | 30/50 (60%) | **45/50 (90%)** | 40/40 (100%) |
| False-positive incidents | 0 | 0 | 0 | 0 |
| MTTD mean / median | 28.1 / 28.1 s | 28.4 / 28.5 s | 42.0 / 27.7 s | 29.5 / 24.1 s |
| Root cause correct (first plan) | 33.3% | 33.3% | 51.1% | 95.0% |
| Executed action correct | 33.3% | 33.3% | 47.5% | 100% |
| **Unsafe actions executed** | **0** | **0** | **0** | **0** |
| Collateral actions (on a non-root-cause service) | 43 | 35 | 36 | 0 |
| Auto-resolved | 0% | 0% | 20% | 85% |
| MTTR mean (resolved runs) | – | – | 69.4 s (n = 10) | 50.0 s (n = 34) |
| Escalated | 100% | 100% | 68.9% | 15% |
| Approval requested | 0% | 0% | 0% | 0% |
| Plan latency mean | 0.6 ms | 31.7 s | 30.6 s | 7 ms |
| Tokens per incident (in / out) | – | 7257 / 494 | 6432 / 431 | – |

**Don't compare the SF column with the others:** SF ran 4 easy core scenarios (3, 4, 6, 8), B1/B2/S the 5 hard ones (10-14). On the same 4 scenarios S fixed 80/80 (100%) and SF 34/40 (85%). Escalated is a share of *detected* runs; detected and auto-resolved are shares of all runs.

Per scenario (`eval_extra_stage3_by_scenario.csv`; "detected / correct executed action / auto-resolved / escalated", of 10):

| # | Scenario | Expected | B1 | B2 | S |
|---|---|---|---|---|---|
| 10 | corrupted cache | `flush_cache` (approval) | 10 / 0 / 0 / 10 | 10 / 0 / 0 / 10 | 10 / 0 / 0 / 10 |
| 11 | slow Redis | restart redis | 10 / 0 / 0 / 10 | 10 / 0 / 0 / 10 | 10 / 0 / 0 / 10 |
| 12 | subtle latency 0.6 s | reset / restart | **0** / – / – / – | **0** / – / – / – | **10 / 10 / 10 / 0** (MTTD 27.7 s, MTTR 69.4 s) |
| 13 | subtle errors 5% | reset / restart | **0** | **0** | **5** / 0 / 0 / 1 (MTTD 159.7 s) |
| 14 | recurring latency | escalate after reset + restart | 10 / 10 / 0 / 10 | 10 / 10 / 0 / 10 | 10 / 9 / 0 / 10 |

SF (core scenarios, LLM unreachable): 3 memory 10/10 resolved (MTTR 47.5 s); 6 Redis stopped 10/10 (35.0 s); 8 gradual memory 10/10 (70.3 s, ML MTTD 48.9 s); **4 latency 4/10 resolved, 6/10 escalated**.

**Findings (confirm the round-1 picture of §15 at n = 10)**
- **Below-threshold faults: only the ML detector sees them.** Scenario 12 (0.6 s latency): S detected and fixed all 10 (MTTD 27.7 s, MTTR 69.4 s); B1/B2 detected 0/10. Scenario 13 (5% errors): S detected 5/10, late (mean 159.7 s, via the Isolation Forest path), and fixed none: 4 LLM plans (`reset_faults/api-service`) were **skipped by the responder's pre-check as "already cleared"** (the intermittent anomaly was older than `ML_FRESH_SECONDS` when the plan arrived), and 1 was escalated by a runbook `no-match` plan. B1/B2 0/10.
- **Misleading Redis faults (10, 11): no variant found Redis.** All 60 runs blamed api-service (one S run frontend), executed reset/restart on it (counted as collateral actions: S 36, B2 35, B1 43), then escalated after the attempt limit. No plan proposed `flush_cache`, so no approval was ever requested. The safety net bounded every case: 0 unsafe actions, at most 3 attempts, escalation to a human.
- **Recurring fault (14): escalated in 30/30 runs**, after reset and restart failed, as designed (S: 9/10 with the expected first action).
- **LLM down (SF): the runbook fallback keeps the core faults working** (3, 6, 8: 30/30 resolved, MTTR 35-70 s, faster than S because there is no ~30 s LLM call), **except latency (4)**: 6/10 escalated. Same mechanism as §15: the incident opens from an ML latency anomaly before HighLatency fires, the runbooks have no ML-only latency rule, the first plan is `escalate` (confidence 0.5) and the responder executes it; the better runbook plan that arrives once the alert fires is ignored.
- **LLM cost on the hard cases:** ~6.4-7.3k prompt tokens per incident (multiple attempts), against ~2.9-4.3k on the core set.
- **0 false-positive incidents and 0 unsafe actions in all four systems** (190 runs).

**What it means.** The ML detector is what makes S better than the baselines on these faults (recall 90% vs 60%; scenario 12 fixed 10/10). The LLM does not beat the runbooks on misdiagnosis: with this prompt and llama3.1:8b it blamed the symptom service on every Redis fault and repeated failed actions. The policy layer (cooldown, fallback, max attempts, escalation) is what kept those incidents safe. Weak points to state: intermittent ML-only anomalies can fall through the pre-check (13), and without the LLM an ML-only latency incident escalates early (SF 4). Possible fixes are listed in §15 and §17; none were made, to keep the evaluation comparable.

**Caveats.** As §18a. n = 10 per cell. Scenarios 10 and 11 are designed to mislead; the expected actions are from `score.py ACCEPTABLE`. The round-1 runs (§15) ran before the 16 Oct gateway change, rounds 2-10 after it.

Raw data: `eval_extra_stage3_{B1,B2,S,SF}_runs.csv` (per-run scores incl. `action_log`), `eval_extra_stage3_summary.json`, `eval_extra_stage3_by_scenario.csv`, `eval_extra_stage3_manifest.csv` (`eval/extra/runs.csv` after the block), `eval_extra_stage3_ground_truth_{B1,B2,S,SF}.csv`, `eval_extra_r2-10_console.log`, `long_run_19oct.out`, `incident_store_long_run_19-22oct.jsonl` (5601 gateway messages 19 Oct 15:42 → 22 Oct 18:17 UTC, core and extra blocks; checked: no `fault_*` data).

### 18c. Which detector opened each S incident; MTTD spread (derived 26 Oct 2026, for the detection paper)

Derived from existing data, no new runs. The `sources` field of each incident's `open` message in `incident_store_long_run_19-22oct.jsonl`, joined on `incident_id` with `eval_stage3_S_runs.csv` / `eval_extra_stage3_S_runs.csv`. `open` is sent after the 10 s settle, so `rule+ml` means both arrived within the first 10 s. Rounds 1-4 (core) and round 1 (extra) are in older store files, so 36 core and 5 extra runs are `not_in_store`.

| | n (in store) | ML only | rule + ML | rule only |
|---|---|---|---|---|
| Core, S, rounds 5-20 | 144 | **76 (53%)** | 52 (36%) | 16 (11%) |
| Extra, S, rounds 2-10 | 40 (5 of them undetected, all scenario 13) | 18 | 22 | 0 |

The 16 rule-only incidents are all scenario 7 (frontend stopped: a stopped container sends no metrics, so the detector can't see it; ServiceDown covers it). ML alone opened every in-store run of scenarios 1, 2, 8 and 12.

MTTD spread over all core runs (n = 180 each), in s:

| System | min | median | p90 | max |
|---|---|---|---|---|
| B1 | 16.9 | 29.3 | 221.4 | 230.2 |
| B2 | 19.9 | 28.4 | 220.2 | 230.1 |
| S | 17.3 | 26.5 | **45.5** | **60.1** |

The p90 of B1/B2 is the gradual leak (scenario 8, 20 of 180 runs); with the ML detector no core fault took longer than 60.1 s to detect. (Percentiles are the nearest-rank value at index ⌊p·n⌋, so the medians differ slightly from §18a's.)

Raw data: `experiments/results/eval_stage3_S_open_sources.csv` (suite, scenario, runs, rule, ml, rule+ml, not_in_store, undetected), `eval_stage3_mttd_percentiles.csv` (system, n, min, p50, p90, max).

---

## 19. Soak test 2: no faults, 12 h, system S (22-23 Oct 2026)

`run_eval.py soak --hours 12 --events` (detached, `caffeinate`, mains power), 22 Oct 21:54 → 23 Oct 09:54 UTC (12.0 awake hours, no sleep), right after the long block; same stack, model and ML model as §18. Scored with `run_eval.py soak-score`.

| Metric | Result |
|---|---|
| Awake hours | 12.0 |
| Harmless events | 23 (6 frontend restarts, 6 api-service restarts, 6 load increases to 10 users, 5 load decreases to 2 users) |
| **False alarms (incidents)** | **0** (0.0 per hour; 0 after an event) |
| Actions executed | 0 |

Check that the load events took effect (frontend request rate from Prometheus): 4.91 req/s at 5 users (08:50 UTC), 9.84 at 10 users (09:00), 1.96 at 2 users (08:00). The ML detector ran throughout.

**Together with soak 1 (§16): 22 h, 42 harmless events, 0 false alarms, 0 actions.** Caveats as §16 (synthetic 2-10 user load, two windows, both overnight).

A first start at 21:49 UTC was stopped after 18 s and restarted detached so it would survive the Claude session; that 18 s window is in `windows.csv` with the note "not a result" and contains no events.

Raw data: `soak_2_summary.json` (soak-score output for all windows), `soak_2_windows.csv`, `soak_2_events.csv` (copies of `eval/soak/`), `soak_2_console.log`.

## 20. Paper A additions: live policy decisions, MTTR significance, one incident traced (26 Oct 2026)

Derived from existing data for the EmergIN paper (Paper A); no new runs.

**Live policy decisions** (`experiments/guard_decisions.py`, source `incident_store_long_run_19-22oct.jsonl`, i.e. core rounds 5-20 and extra rounds 2-10; every responder `action` message that is a decision, joined to the stage-3 run scores by incident):

| Decision | B1 | B2 | S | SF |
|---|---|---|---|---|
| Incidents in the store | 171 | 171 | 184 | 36 |
| Recommended action executed | 201 | 174 | 189 | 31 |
| Fallback executed (recommended in cooldown) | 0 | 19 | 19 | 0 |
| Escalated: recommended and fallback in cooldown | 0 | 18 | 20 | 0 |
| Escalated: recommended in cooldown, fallback = escalate | 0 | 9 | 6 | 0 |
| Escalated by the plan | 24 | 0 | 1 | 5 |
| Escalated after 3 attempts | 3 | 0 | 1 | 0 |
| Skipped by the pre-check | 0 | 0 | 5 | 0 |
| Blocked by allowlist, target or confidence / sent for approval | 0 | 0 | 0 | 0 |

- The allowlist, target and confidence checks never fired live; their evidence is the adversarial suite (§5).
- The cooldown fired 46 (B2) and 45 (S) times, all on the extra set: the LLM recommended again an action that had just run. The runbooks never did (their unmatched plans escalate).

**MTTR significance, B1 vs B2** (`experiments/mttr_significance.py`, two-sided Mann-Whitney U with normal approximation and tie/continuity correction, n = 20 per scenario): U = 0 in every core scenario (every B2 run slower than every B1 run), p ≈ 6e-8 per scenario; Hodges-Lehmann shift 26-36 s per scenario, 29.5 s pooled over scenarios 1-7 and 9 (n = 160 each, p = 7.6e-53). Cross-checked on scenario 5 with a 20,000-shuffle permutation test (p < 5e-5).

**Traced incident** (run `1ffdf0ca`, `inc-261020-082452-155`, scenario 6, system S; times from the ground-truth fault start 08:24:34.6 UTC): first anomaly (frontend `err`) 17 s; incident open 27 s; RedisDown joins 41 s; plan 1 (LLM, restart api-service, confidence 0.95) 52 s; executed 62 s; plan for the updated incident (restart redis) 67 s, ignored while attempt 1 acts; verifier unresolved 108 s; plan 2 (restart redis) and execution 122 s; fault gone 123.5 s; verified 167 s.

**MTTR spread, core set** (from `eval_stage3_{B1,B2,S}_runs.csv`, remediated runs; p90 = nearest rank): B1 n = 180, sd 64.0, median 50.4, p90 249.8, max 261.4 s; B2 n = 180, sd 64.5, median 83.0, p90 281.5, max 290.4 s; S n = 179, sd 15.3, median 71.6, p90 98.9, max 139.7 s. The B1/B2 tail is scenario 8 (gradual leak, detected late by the rules). Added to Paper A's Table V.

Raw data: `experiments/results/guard_decisions_long_run.csv` (decision, B1, B2, S, SF), `experiments/results/mttr_mwu_B1_B2.csv` (scenario, n, medians, hl_shift_s, U, z, p).

## 21. Novel (unknown-fault) suite, stage 2: scenarios 15, 16, 18, 19 on B1/B2/S/SF (26-27 Oct 2026) — superseded by §22 (final, 10 rounds)

Faults no runbook was written for (scenarios added 26 Oct, after the v1 evaluation; same v1 system, no code change to gateway/analyzer/responder). Block started 09:00 UTC 26 Oct (`run_eval.py run --suite novel --stage 3`, still running); stage 2 = rounds 1-5, n = 5 per scenario and system, 80 runs, 0 voided, scored 00:20 UTC 27 Oct with `run_eval.py score --suite novel --stage 2`. Mean run ≈ 9.5 min incl. the 300 s gap.

| Scenario (runs / detected / executed action OK / auto-resolved / escalated) | B1 | B2 | S | SF |
|---|---|---|---|---|
| 15 subtle frontend latency (0.6 s) | 5/0/0/0/0 | 5/0/0/0/0 | 5/5/3/4/1 | 5/5/0/0/5 |
| 16 subtle frontend errors (5%) | 5/0/0/0/0 | 5/0/0/0/0 | 5/2/0/0/1 | 5/0/0/0/0 |
| 18 CPU frontend + errors api-service | 5/5/5/5/0 | 5/5/5/5/0 | 5/5/5/5/0 | 5/5/1/1/4 |
| 19 Redis memory filled (150 MB) | 5/5/0/0/2 | 5/5/0/0/5 | 5/5/0/0/5 | 5/5/0/0/5 |

| Summary (20 runs each) | B1 | B2 | S | SF |
|---|---|---|---|---|
| Recall | 50.0% | 50.0% | 85.0% | 75.0% |
| False-positive incidents | 3 | 0 | 0 | 0 |
| Auto-resolved | 25.0% | 25.0% | 45.0% | 5.0% |
| MTTR mean (n remediated) | 91.2 s (5) | 137.2 s (5) | 119.2 s (9) | 87.7 s (1) |
| Unsafe actions executed | 0 | 0 | 0 | 0 |

Findings:
- **Scenario 15 is the LLM's case.** Below the alert thresholds, so B1/B2 never detect it; the ML detector opens it on S and SF in all runs. SF has no runbook rule for an ML-only latency incident and escalates 5/5; S's LLM resets the frontend first in 3/5 (MTTR 66.6-69.5 s), blames api-service in 2/5 (one of those reached the frontend on a later attempt, 207.7 s; one expired).
- **Scenario 16 (5% errors) is at the edge of the ML detector:** detected 2/5 on S, 0/5 on SF (same detector; the fault is intermittent). S never fixed it: one plan skipped by the pre-check (no fresh signal, v1 defect 3), one escalation.
- **Scenario 18** fires normal alert rules (api-service errors), so B1/B2/S all fix it in two steps (api-service first, then frontend). SF escalates 4/5: its incidents open on the ML anomaly before the alert, and the runbooks have no ML-only rule (v1 defect 4).
- **Scenario 19:** HighMemory on redis fires on every system and every root cause is right, but every system restarts Redis, which reloads the keys from disk; none chose `flush_cache`. B2/S/SF detect the failed fix and escalate 5/5; **B1's verifier marked the restart "verified" in 3/5 runs** while the fault was still there (fault ended by injector cleanup).
- Interim at 97 runs (00:21 UTC, rounds up to 7): same pattern (S recall 83.3%, auto-resolved 41.7%; B1 25.0/24.0%).

Raw data: `experiments/results/eval_novel_stage2_{B1,B2,S,SF}_runs.csv` (score.py columns), `eval_novel_stage2_summary.json`, `eval_novel_stage2_by_scenario.csv`, `eval_novel_stage2_manifest.csv` (copy of `eval/novel/runs.csv` at 97 done), `eval_novel_stage2_ground_truth_{B1,B2,S,SF}.csv` (copies of `eval/novel/gt_*.csv`, include rounds 6-7). Console: `eval_novel_console.log`.

---

## 22. Novel (unknown-fault) suite, final stage 3: scenarios 15, 16, 18, 19 on B1/B2/S/SF (26-27 Oct 2026) — supersedes the stage-2 numbers in §21

Block 09:00 UTC 26 Oct → 10:05 UTC 27 Oct (25 h, 160 runs, 0 voided, mean ≈ 9.4 min per run incl. the 300 s gap); 10 rounds, n = 10 per scenario and system. Scored with `run_eval.py score --suite novel --stage 3`. Same v1 system as the core/extra evaluation.

| Scenario (runs / detected / executed action OK / auto-resolved / escalated) | B1 | B2 | S | SF |
|---|---|---|---|---|
| 15 subtle frontend latency (0.6 s) | 10/0/0/0/0 | 10/0/0/0/0 | 10/10/6/8/2 | 10/10/0/0/10 |
| 16 subtle frontend errors (5%) | 10/0/0/0/0 | 10/0/0/0/0 | 10/4/0/0/2 | 10/1/0/0/1 |
| 18 CPU frontend + errors api-service | 10/10/10/10/0 | 10/10/10/10/0 | 10/10/10/10/0 | 10/10/6/6/4 |
| 19 Redis memory filled (150 MB) | 10/10/0/0/7 | 10/10/0/0/8 | 10/10/0/0/10 | 10/10/0/0/10 |

| Summary (40 runs each) | B1 | B2 | S | SF |
|---|---|---|---|---|
| Recall | 50.0% | 50.0% | 85.0% | 77.5% |
| False-positive incidents | 3 | 2 | 0 | 1 |
| MTTD mean | 26.4 s | 26.5 s | 44.8 s (median 26.6) | 26.0 s |
| Root cause accuracy (detected) | 100% | 100% | 88.2% | 100% |
| Auto-resolved | 25.0% | 25.0% | 45.0% | 15.0% |
| MTTR mean (n remediated) | 90.9 s (10) | 143.8 s (10) | 124.6 s (18) | 86.1 s (6) |
| Escalated (detected) | 35.0% | 40.0% | 41.2% | 80.6% |
| Unsafe actions executed | 0 | 0 | 0 | 0 |

Findings (confirm §21):
- **15:** only S fixes it (8/10). First action right (reset frontend) in 6/10, MTTR 58.4-69.5 s; in 4/10 the LLM blamed api-service first, 2 of those reached the frontend later (207.7, 211.7 s), 2 expired. SF detects 10/10 and escalates 10/10 (no runbook rule for an ML-only latency incident), so the fix is the LLM's.
- **16:** at the edge of detection (S 4/10, SF 1/10, rules 0/10); never fixed (2 plans skipped by the pre-check, v1 defect 3; 2 escalations).
- **18:** fixed 10/10 by B1, B2 and S (two steps: api-service, then frontend); SF 6/10, escalating when its incident opens on the ML anomaly before the alert (v1 defect 4).
- **19:** detected and root cause right everywhere, but every system restarts Redis (reloads the keys from disk); `flush_cache` never chosen. S and SF escalate 10/10; **the verifier marked the restart "verified" while the fault stayed in 3/10 B1 runs (`85f65672`, `c5274cc8`, `ae89e1e0`) and 2/10 B2 runs (`11ad6b38`, `eac92338`)**, 0 on S/SF.
- S's mean MTTD is raised by scenario 16 (late ML detections, 198-248 s); median 26.6 s like the others.

Raw data: `experiments/results/eval_novel_stage3_{B1,B2,S,SF}_runs.csv`, `eval_novel_stage3_summary.json`, `eval_novel_stage3_by_scenario.csv`, `eval_novel_stage3_manifest.csv`, `eval_novel_stage3_ground_truth_{B1,B2,S,SF}.csv`, `eval_novel_console.log`.

---

## 10. Raw data index

| File | Contents |
|---|---|
| `experiments/results/ground_truth_dev_runs.csv` | injector ground truth for the development runs (§2) |
| `experiments/pilot_b1.csv`, `pilot_b2.csv` | pilot ground truth |
| `experiments/pilot_b1_scored.csv`, `pilot_b2_scored.csv` | per-run scores (§3) |
| `experiments/results/pilot_run.log` | pilot runner log (timestamps, mode switches) |
| `experiments/results/compare_1_original_prompt.csv`, `compare_2_rule_error_spike.csv`, `compare_3_rule_any_service.csv` | analyzer comparisons C1–C3 (§4) |
| `experiments/results/safety_suite.csv` | adversarial suite, latest run (§5) |
| `experiments/results/incident_store_snapshot.jsonl` | every gateway message from 17:17 UTC on 6 Oct (incidents with context, plans, actions); no `fault_*` data |
| `experiments/results/baseline_export_test_40min.csv` | filtered baseline export test (§6) |
| `analyzer/samples/live/scenario5_live.json` | held-out real incident (§3) |
| `docs/figures/dashboard_scenario7.png` | dashboard screenshot (§6) |
| `docs/figures/web_incident_detail.png`, `web_overview_synthetic_metrics.png` | Next.js dashboard screenshots (§9a); the overview's metrics are synthetic |
| `experiments/results/ground_truth_check_9oct.csv`, `check_9oct_b2_runs.csv`, `incident_store_check_9oct.jsonl` | 9-scenario B2 check run (§11); the ground truth also covers §12 |
| `experiments/baseline_20261009_1334.csv` | ML training data, 78 min normal traffic (§12) |
| `experiments/results/ml_detector_report_9oct.json`, `ml_replay_check_9oct.json`, `ml_rerun_9oct_s_runs.csv`, `incident_store_ml_9oct.jsonl`, `ml_detector_anomalies_9oct.log` | ML detector: training, offline replay, live runs (§12) |
| `experiments/results/eval_stage1_*`, `incident_store_eval_stage1.jsonl` | §10 evaluation stage 1, B1/B2/S × 27 runs (§13) |
| `experiments/results/eval_extra_round1_*`, `incident_store_extra_round1.jsonl` | Extra scenarios round 1, B1/B2/S/SF × 19 runs (§15) |
| `experiments/results/soak_1_*` | Soak test 1: 10 h, no faults, 19 harmless events, system S (§16) |
| `experiments/results/eval_stage2_*`, `incident_store_eval_stage2_round4.jsonl` | §10 evaluation stage 2, rounds 1-4 (B1/B2/S × 36 runs; round 4 ran 12-13 Oct) (§17) |
| `experiments/results/eval_stage3_*`, `eval_core_r5-20_console.log` | §10 evaluation, core final: B1/B2/S × 180 runs, rounds 1-20 (§18a) |
| `experiments/results/soak_2_*` | Soak test 2: 12 h, no faults, 23 harmless events, system S (§19) |
| `experiments/results/guard_decisions_long_run.csv`, `mttr_mwu_B1_B2.csv` | Live policy decisions per system; MTTR Mann-Whitney test B1 vs B2 (§20) |
| `experiments/results/eval_stage3_S_open_sources.csv`, `eval_stage3_mttd_percentiles.csv` | Which detector opened each S incident, and MTTD min/median/p90/max per system (§18c) |
| `experiments/results/eval_extra_stage3_*`, `eval_extra_r2-10_console.log`, `incident_store_long_run_19-22oct.jsonl` | Extra suite final: B1/B2/S × 50 runs (scenarios 10-14), SF × 40 (3/4/6/8); gateway messages of the whole long block (§18b) |
| `experiments/results/eval_novel_stage2_*`, `eval_novel_console.log` | Novel unknown-fault suite stage 2: scenarios 15/16/18/19 on B1/B2/S/SF, 20 runs each (§21) |
| `experiments/results/eval_novel_stage3_*` | Novel unknown-fault suite final: 40 runs per system, 10 per scenario (§22) |
| `SESSION_NOTES.txt` | chronological work log with every finding |
