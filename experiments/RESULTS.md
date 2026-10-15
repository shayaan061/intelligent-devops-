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
| `gateway/tests` | 20 | Grouping and dedup (symptom alerts join one incident, repeats ignored, refires, monitoring alerts kept separate, ML window, repeat anomalies refresh without a new analysis + `ml_active`, 9 Oct); context builder against a fake Prometheus (shapes, NaN → null, no `fault_` queries); endpoints and both WebSockets; `/actions` history; re-analysis; SQLite store survives reopening; dashboard served; NaN/Infinity rejected on every input |
| `analyzer/tests` | 81 | Schemas (strict enums, allowlist, `fault_*` stripping); runbooks give the §10 answer for every sample; the LLM path falls back on connection error, timeout, invalid JSON, schema violation, `reset_faults` on redis, low confidence (Ollama mocked); coalescing; Ollama token counts on the plan, kept on a fallback after an unusable answer, null when missing/invalid or without an LLM call (12 Oct) |
| `responder/tests` | 45 | Every policy rule (allowlist, targets, confidence incl. NaN/inf/bool/string, risky actions, cooldown → fallback → escalate, max actions); executor (refuses non-allowlisted actions); execute → verify → re-analyze → escalate; stale-attempt and busy skipping; pre-check skip; approve/reject; dry run; CORS; `/policies` (8 Oct); ML-only incident executed and verified, active ML anomaly = unresolved (9 Oct) |
| `experiments/tests` | 25 | Scorer (matching, false positives, undetected runs, symptom-as-root, scenario 1 reset-or-restart, unsafe counting, attempts, LLM share, `--since`; 12 Oct: tokens summed over attempts, `--max-gap` false-positive spans), the full adversarial suite, and the evaluation runner (12 Oct: fixed shuffled order, interleaved rounds, resume, `--rounds`, later stages add rounds, void, per-stage selection, ground-truth row lookup; the gap is waited before switching systems and before restoring) |
| `ml/tests` | 10 | Model on synthetic data: normal rarely flagged, memory/latency/error rises flagged, "lower than usual" ignored, missing = typical, forest path for combined moderate deviations, 2-poll persistence, no `fault_` queries, replay scoring (9 Oct) |
| `prometheus/rules_test.yml` | (promtool) | Alert rules fire and stay quiet as expected (written in Phase 2) |
| **Total (pytest)** | **181** | (146 on 7 Oct; 147 on 8 Oct; 9 Oct: +1 gateway, +2 responder, +10 ml; 12 Oct: +6 analyzer, +15 experiments; safety suite 29/29) |

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
| `SESSION_NOTES.txt` | chronological work log with every finding |
