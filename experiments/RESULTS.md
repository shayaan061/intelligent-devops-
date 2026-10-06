# Results Log: tests, comparisons and evaluations

The record of every test, comparison and evaluation run, kept for the final report (§13 of `SUGGESTED_PLAN.md`: chapter 6 "Evaluation and Results", and the testing part of chapter 4). Every number here comes from a file in `experiments/results/`, `experiments/pilot_*.csv` or a test run that was repeated; the source is given for each table.

**Keep it current.** Every new test run, comparison or evaluation gets an entry here (date, setup, numbers, source file, caveats), not only in `SESSION_NOTES.txt`. Don't delete superseded results: mark them as superseded, so the report can show how the system improved.

Last updated: 6–7 Oct 2026.

---

## 0. Test environment

| Item | Value |
|---|---|
| Machine | Apple M4, 10 cores, 16 GB RAM, macOS 27.0.1 |
| Docker | Docker Desktop, Engine 29.1.3; VM with 10 CPUs and 8.2 GB; containerd image store **on** (so no container CPU/memory metrics, see §7) |
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

Latest run: 7 Oct 2026, all passing. Run commands are in `CLAUDE.md`.

| Suite | Tests | What it covers |
|---|---|---|
| `gateway/tests` | 19 | Grouping and dedup (symptom alerts join one incident, repeats ignored, refires, monitoring alerts kept separate, ML window); context builder against a fake Prometheus (shapes, NaN → null, no `fault_` queries); endpoints and both WebSockets; `/actions` history; re-analysis; SQLite store survives reopening; dashboard served; NaN/Infinity rejected on every input |
| `analyzer/tests` | 75 | Schemas (strict enums, allowlist, `fault_*` stripping); runbooks give the §10 answer for every sample; the LLM path falls back on connection error, timeout, invalid JSON, schema violation, `reset_faults` on redis, low confidence (Ollama mocked); coalescing |
| `responder/tests` | 42 | Every policy rule (allowlist, targets, confidence incl. NaN/inf/bool/string, risky actions, cooldown → fallback → escalate, max actions); executor (refuses non-allowlisted actions); execute → verify → re-analyze → escalate; stale-attempt and busy skipping; pre-check skip; approve/reject; dry run; CORS |
| `experiments/tests` | 10 | Scorer (matching, false positives, undetected runs, symptom-as-root, scenario 1 reset-or-restart, unsafe counting, attempts, LLM share, `--since`), plus the full adversarial suite |
| `prometheus/rules_test.yml` | (promtool) | Alert rules fire and stay quiet as expected (written in Phase 2) |
| **Total (pytest)** | **146** | |

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
| O2 detection | recall ≥ 0.90, FP ≤ 10% | rules: 16/16 logged real faults detected, 0 false-positive incidents in the pilot; ML detector not built |
| O3 root cause | ≥ 80% | pilot 8/8 (B1 4/4, B2 4/4); samples LLM 18/18 (optimistic) |
| O4 safe, correct action | ≥ 85% correct, 0 unsafe | pilot B1 4/4, B2 3/4; **0 unsafe** in every run and 29/29 adversarial cases |
| O5 auto-resolved | ≥ 60% | pilot 8/8 auto-resolved and verified |
| O6 MTTR | ≥ 50% faster than manual | not measured: needs B0 (a person fixing faults by hand, timed). Unfixed faults lasted their full 90–120 s (D1, D2) |

None of these are final: the §10 evaluation needs all 9 scenarios × ≥ 20 runs per system, with B0 and the ML detector.

---

## 9. Caveats to state in the report

- Small n everywhere so far (one run per scenario per system).
- Scenarios 1, 2, 3, 8, 9 not yet run live (P2). Scenario 8 also needs the ML detector.
- The hand-written samples were written together with the runbooks, and the prompt was tuned on them.
- One machine, one model (llama3.1:8b); no comparison with a hosted model yet.
- MTTR includes the LLM's latency on this hardware; a faster model or GPU would change B2's MTTR.

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
| `SESSION_NOTES.txt` | chronological work log with every finding |
