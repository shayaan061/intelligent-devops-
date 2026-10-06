# Progress Log: Phases 2–6 (Monitoring, Gateway, Analyzer, Responder, Verifier)

**Date:** 3 Oct 2026 · **Last updated:** 6 Oct 2026
**Plan:** `SUGGESTED_PLAN.md` §3 (fixes) and §15 (immediate next steps)
**Status:** Phase 2 is complete (commit `9415a44`). Phase 3 (Event Gateway) is complete and tested end-to-end under Docker (Step 4–5). Phase 4 (analyzer + runbooks) has started (Step 6). Phases 5–6 (responder, verifier, re-analysis, incident store) are built and the loop closes on real containers (Step 7). **Open blocker:** container CPU/memory metrics on macOS (see A below).

| §15 item | Status |
|---|---|
| Fix the `latency`/`error` duration bug and histogram recording | ✅ Done |
| Add `api-service` + Redis + redis_exporter + cAdvisor | ✅ Done |
| Write `prometheus/rules.yml` and `alertmanager/alertmanager.yml` | ✅ Done |
| Implement `injector/injector.py` with ground-truth logging | ✅ Done |
| Skeleton gateway: `/alerts` → print → WebSocket broadcast | ✅ Done, tested end-to-end under Docker (Step 4–5) |

> First Docker run: 6 Oct 2026 (Docker 29.1.3, Docker Desktop on macOS). All 4 Prometheus targets are UP, and scenario 4 went injector → Prometheus → Alertmanager → gateway → `/ws/events` as one grouped incident.

---

## Next steps

In order. Owners follow the work split in `SUGGESTED_PLAN.md` §9.

### A. Close out Phase 2 (before starting the gateway)
- [x] **Run the stack under Docker for the first time.** Done 6 Oct: all 4 targets UP.
- [ ] **⚠️ Blocker: cAdvisor has no `name` label on this Mac, so HighCPU/HighMemory can never fire** (scenarios 1, 2, 3, 8, 9 and the context's `cpu`/`mem`, which are `null`). Checked 6 Oct:
  1. v0.49.1 couldn't talk to Docker 29 at all (API too old) and the socket wasn't visible through the `/var/run` mount. **Fixed in compose:** image → `ghcr.io/google/cadvisor:v0.53.0`, plus an explicit `/var/run/docker.sock` mount. The Docker factory now registers.
  2. Remaining cause: Docker Desktop's **containerd image store** (`docker info` → `driver-type io.containerd.snapshotter.v1`). cAdvisor logs `failed to identify the read-write layer ID … mount-id: no such file or directory` for every container.
  **Fix (manual):** Docker Desktop → Settings → General → untick *Use containerd for pulling and storing images* → Apply & restart, then `docker compose up -d --build`. Check with `container_memory_working_set_bytes{name="api-service"}` at `localhost:9090/graph`. Each team member running the demo on a Mac needs this setting.
- [ ] **Run each scenario once for real** and note the alert and detection time: `docker compose run --rm injector run <1-9> --duration 180`. Scenarios 1, 2, 3, 6 and 7 have never fired on real containers.
- [ ] **Scenario 8 should not fire HighMemory early.** It is meant to be caught by ML only. Check how long the ramp stays under 80%.
- [x] **Decide scoring for scenario 3:** restart only (decided 6 Oct, written into §10 of the plan; `experiments/score.py` encodes it).
- [ ] **Update the §6.1 table in `SUGGESTED_PLAN.md`** to the real windows (30 s rate, `for: 20s`) and fault caps (600 s, 450 MB).

### B. Phase 3, part 1: skeleton gateway (§15, last item). Owner: Shayaan
Detailed checklist in [Step 4](#step-4-skeleton-event-gateway--to-do-later) below. Summary:
- [x] `gateway/` FastAPI service: `POST /alerts`, `GET /health`, WebSocket `/ws/events`
- [x] Compose service named `gateway` on port 8000
- [x] End-to-end test: injector → Prometheus → Alertmanager → gateway → WebSocket client (scenario 4, 6 Oct)
- [x] Tick the last box in §15 of `SUGGESTED_PLAN.md`

### C. Phase 3, part 2 (Oct week 4 – Nov week 1) ✅ Done 6 Oct, see Step 5
- [x] Grouping: events within 60 s along `frontend → api-service → redis` become one incident with an `incident_id`
- [x] Context builder: last 10 min of CPU, memory, p95, error rate and `upstream_p95` per service, through the Prometheus HTTP API
- [x] Emit the full `IncidentEvent` JSON (§6.3), with `fault_*` metrics filtered out
- [x] `POST /anomalies` stub for the ML detector, and the `/ws/responses` channel

### E. Phases 5–6: response system + verifier ✅ (6 Oct, see Step 7). Owner: Shayaan
- [x] Policy validator (`responder/policy.py`, `policies.yaml`): allowlist, known targets, confidence ≥ 0.7, 5-min cooldown, ≤ 3 actions per incident, approval for risky actions
- [x] Executor: `reset_faults`, `restart_container`, `flush_cache` (approval only); `update_resources` not implemented (plans carry no limits)
- [x] Approval flow: `GET /approvals`, `POST /approvals/{id}/approve|reject` on port 8001
- [x] Verifier + re-analysis with history, max 3 attempts, then escalate
- [x] Incident store (SQLite, `experiments/incidents.db`)
- [x] **Decide the cooldown for evaluation runs.** Decided 6 Oct: keep the 300 s cooldown and run suites with `--gap 300` (§10 of the plan), so back-to-back scenarios aren't blocked by the previous run's cooldown.
- [ ] Incident *state* is in memory: a gateway restart loses open incidents (the store keeps the record). Persisting state is optional for the MVP.
- [ ] **Riddhima:** the analyzer's Pydantic schema coerces `"0.99"` and `true` into a confidence (lax mode). The responder now rejects them, but consider `strict=True` on `confidence` in `analyzer/schemas.py`.
- [ ] Approvals have no timeout yet; a pending approval keeps its incident waiting until a human answers.
- [x] Minimal UI (MVP, §12): `dashboard/index.html` at `http://localhost:8000/dashboard/`: service map, incident feed with plans/actions, approval queue with Approve/Reject. Riddhima (dashboard owner, §9) can replace it with the full React dashboard in Phase 8.
- [ ] Open the dashboard in a browser during the next scenario run; it was checked by syntax check + HTTP only, not visually.

### D. Can start in parallel
- [x] **Riddhima:** LLM prompt and `ResponsePlan` schema (§6.4), using hand-written `IncidentEvent` samples; YAML runbooks for scenarios 1–9 (these are also baseline B1). First version built 6 Oct (Step 6); Riddhima to review the prompt and runbooks.
- [x] **Install Ollama on the host.** Done 6 Oct: Homebrew `ollama` 0.35.1 as a launchd service (`brew services start ollama`), model `llama3.1:8b`. First results in Step 9.
- [ ] **Verifier/responder must send `history.previous_actions`** as `[{"type", "target"}]` when re-analysing (§6.6); the analyzer skips actions already tried.
- [ ] **Check scenario 8's ML feature names** against the runbook `ml-memory-anomaly` (matches any `top_features` entry containing `mem`) once the ML detector exists.
- [ ] **Shruti:** record 1–2 hours of normal traffic under Locust now, as training data for the ML detector (Phase 7)
- [ ] **All:** apply the edits in `PATENT_CHANGES.md` to the patent draft

---

## Step 0: Fixes to the existing code (`app/app.py`)

From §3 of the plan:

| # | Problem | Fix |
|---|---|---|
| 1 | `latency`/`error` faults ignored `duration` and never cleared | Timer thread clears them automatically |
| 2 | Latency histogram skipped on error paths | `@instrumented(endpoint)` decorator records count and latency in a `finally` block, so every path is covered |
| 3 | `fault_*_active` gauges are ground truth | Marked in the code: scoring only, never fed to the ML detector, the LLM or the alert rules |
| 4 | No container metrics | cAdvisor added (port 8080) |
| 5 | No restart policy or healthcheck | `restart: unless-stopped` and a `/health` healthcheck |

Additional bugs found and fixed:
- **`/reset` didn't stop the CPU fault.** The busy-loop never checked the flag. Every worker now checks it.
- **The memory fault may not have used real memory.** A zero-filled `bytearray` isn't always counted against the container until written to. It's now filled with non-zero bytes so the usage really goes up.
- **Old timers could clear new faults.** Each fault now has a *generation counter*, so a timer from an earlier injection can't clear a newer one.
- `/inject` now validates its input (400 on bad values), and every fault type returns 409 if it's already running.

---

## Step 1: Multi-service demo app

```
Locust → frontend (app/, :5001) → api-service (:5002) → redis
```

- **`api-service/`** (new): a Flask service with the same fault, `/health`, `/metrics`, `/inject` and `/reset` code. `GET /data` runs `INCR hits` on Redis.
- **`frontend`** (`app/`): `/` calls `api-service/data` and returns 502 if that fails.
- **`upstream_request_duration_seconds{upstream=...}`** in both services: the time spent calling the next service. **This is what separates the root cause from the symptoms.**
- Redis, plus **redis_exporter** (port 9121).
- Containers renamed to `frontend`, `api-service`, `redis` and so on (no `devops-` prefix), because the cAdvisor alert rules match on these names.
- The Redis client has **retries disabled**. With the default retries, Redis being down showed up as about 4 s of latency instead of an error.

**Test results:**

| Scenario | frontend | api-service |
|---|---|---|
| Normal | 200 | 200 |
| `api-service` error fault | 502 | 500 |
| `api-service` latency fault | 5.0 s | Redis call ~4 ms (shows `api-service` is the cause) |
| Redis down | 502, returned instantly | 503 |

---

## Step 2: Alert rules and Alertmanager

- **`prometheus/rules.yml`** has 7 alerts: HighCPU, HighMemory, HighLatency, HighErrorRate, ServiceDown, RedisDown, and ExporterDown (cAdvisor or redis_exporter has stopped reporting).
  - Every alert has a **`service` label** (`frontend` / `api-service` / `redis`) for the gateway.
- **`prometheus/rules_test.yml`**: `promtool` unit tests, covering every alert firing and a healthy system staying silent. All pass.
- **`alertmanager/alertmanager.yml`**:
  - Webhook → `http://gateway:8000/alerts`, grouped by `alertname` + `service`.
  - `send_resolved: true`, for the verifier.
  - Inhibit rule: when a service is down, its own latency and error alerts are suppressed.

**Live test results:**

| Scenario | Alerts | Time |
|---|---|---|
| Latency fault in `api-service` | HighLatency on `api-service` and on `frontend` | 38 s |
| Fault reset | Both alerts sent "resolved" | 51 s |
| `api-service` killed | ServiceDown on `api-service` and HighErrorRate on `frontend` | 34 s |

**Changes from the plan:**
- **Rate windows are 30 s with `for: 20s`, not 1 minute and 30 s.** With the plan's values a CPU fault needs about 78 s to alert, so a 30-second fault never would. The table in §6.1 of the plan still shows the old numbers.
- **Fault limits raised:** `duration` up to 600 s (was 60) and `size_mb` up to 450 (was 300). A fault has to last through detection *and* remediation for the verify loop to mean anything, and at 300 MB the 80% memory threshold could never be reached.

---

## Step 3: Fault injector and background load

- **`injector/injector.py`** runs the 9 evaluation scenarios from §10:

  | # | Scenario | Target | Expected action |
  |---|---|---|---|
  | 1 | cpu-frontend | frontend | reset_faults |
  | 2 | cpu-api | api-service | reset_faults |
  | 3 | memory-api (420 MB) | api-service | restart_container |
  | 4 | latency-api | api-service | reset_faults |
  | 5 | error-api | api-service | reset_faults |
  | 6 | redis-stopped | redis | restart_container |
  | 7 | frontend-stopped | frontend | restart_container |
  | 8 | gradual-memory-api (440 MB over 240 s) | api-service | restart_container |
  | 9 | cpu-latency-api | api-service | reset_faults |

- **Ground truth** is written to `experiments/ground_truth.csv`. Each row has the start, the planned end, the actual end and an `end_reason`:
  - `expired`: nothing fixed the fault.
  - `remediated`: the fault ended early, so the system fixed it. **MTTR and the auto-resolve rate are scored on these rows.**
  - `cleanup`: the injector had to undo the fault itself.
- The memory fault has a new **`ramp_seconds`** option (it grows 10 MB at a time) for scenario 8.
- **`load/locustfile.py`** generates about 5 requests per second. It always runs as the `load` service, because the HTTP alerts need traffic.
- **Test results:** every `end_reason` recorded correctly. The tests also covered skipping a target that's already faulty, and Ctrl-C undoing the active fault.

- **Web control panel** (`injector/web.py`, http://localhost:8088, compose service `injector-ui`). It's a browser front end to `injector.py` and does everything the CLI does: single/suite runs with a live countdown, cancel, reset, manual faults, container stop/start, Prometheus alerts and recent ground truth. Runs go through `run_scenario`, so ground truth is identical. Manual actions are blocked during a run, and **Reset all** cancels the run first; otherwise the reset would be recorded as `remediated`.

**Open question for scoring:** in scenario 3, `reset_faults` also frees the memory. Decide whether to accept it alongside `restart_container`.

---

## How to run

```bash
docker compose up --build                       # whole stack + background load
# Prometheus :9090 · Alertmanager :9093 · cAdvisor :8080 · frontend :5001 · api-service :5002

# Injector UI: http://localhost:8088  (or the CLI below)
docker compose run --rm injector list
docker compose run --rm injector run 4 --duration 180
docker compose run --rm injector suite --scenarios 1-9 --repeat 3 --shuffle --seed 1 --gap 60
docker compose run --rm injector reset

cd prometheus && promtool test rules rules_test.yml
```

---

## Step 4: Skeleton Event Gateway ✅ (code done, Docker test pending)

**Owner:** Shayaan · **Phase 3 in the timeline** (Oct week 4 – Nov week 1) · Plan: §6.3

Goal: a FastAPI service that receives Alertmanager webhooks, logs them, and broadcasts them over WebSocket. Grouping and the context builder come after it, in the rest of Phase 3.

**Skeleton scope:**
- [x] `gateway/` with `app.py`, `requirements.txt` (`fastapi`, `uvicorn`) and a `Dockerfile`
- [x] `POST /alerts`: accepts Alertmanager's webhook JSON (`status`, `alerts[]` with `labels`, `annotations`, `startsAt`, `endsAt`, `fingerprint`) and logs each alert
- [x] Converts each alert to a minimal `IncidentEvent`-shaped message (`alertname`, `service`, `status`, `severity`, `startsAt`, `source: "rule"`)
- [x] WebSocket `/ws/events`: broadcasts every message to all connected clients
- [x] `GET /health`
- [x] A `gateway` service in `docker-compose.yml` on port **8000**. The service name must be `gateway`, because Alertmanager already posts to `http://gateway:8000/alerts`.
- [ ] Test: run an injector scenario → the alert arrives at the gateway → a WebSocket client (e.g. `websocat ws://localhost:8000/ws/events`) receives it

**What was built:**
- `gateway/app.py` (FastAPI + uvicorn). Each alert becomes `{type, source: "rule", alertname, service, status, severity, category, startsAt, endsAt, fingerprint, labels, annotations}`. Annotations are dropped on resolved alerts (stale values); labels starting with `fault_` are dropped.
- `GET /events` returns the last 100 events, and a new `/ws/events` client gets them replayed first (`"replay": true`), so a dashboard opened mid-incident has history.
- `GET /health` reports connected clients and webhook/event counts. Malformed webhooks get a 400.
- Compose: `gateway` service on 8000 with a healthcheck; Alertmanager now `depends_on` it.
- Smoke-tested with FastAPI's TestClient (firing → WS, resolved → WS without annotations, replay, 400s). Not yet run under Docker.

**Things to keep in mind (from steps 2–3):**
- Use the `service` label on every alert; it's already set to `frontend` / `api-service` / `redis`.
- Resolved notifications carry the annotation text from the last time the alert fired, so don't read metric values from them.
- A single fault fires alerts on the symptom service too. For example, `api-service` latency → HighLatency on both services. That's expected: the later grouping step (60 s window along the dependency chain) merges them into one incident.
- Never include `fault_*` metrics or `ground_truth.csv` in anything the gateway sends.

**Later in Phase 3 (after the skeleton):**
- [ ] `POST /anomalies` for the ML detector
- [ ] Dedup and grouping: events within 60 s along `frontend → api-service → redis` become one incident
- [ ] Context builder: the last 10 minutes of key metrics per service, through the PromQL API, plus topology and history (see the `IncidentEvent` example in §6.3)
- [ ] `/ws/responses` channel for the analyzer

---

## Step 5: Event Gateway, Phase 3 complete ✅ (6 Oct)

`gateway/` is split into three files:
- `incidents.py`: dedup and grouping. Alerts are deduped by fingerprint. A new alert or ML anomaly joins the open incident on the same chain (`frontend → api-service → redis`); `ExporterDown` (`service=monitoring`) is grouped on its own. An incident stays open while an alert is firing or an ML anomaly is < 60 s old (`GROUP_WINDOW`), then resolves. A later alert opens a new incident.
- `context.py`: the context builder. One PromQL `query_range` per metric per service (10 min, 60 s step; the last point is the current value, the list is the `trend`). Metrics: `up, cpu, mem, p95, err, rps, upstream_p95` for frontend/api-service; `up, ops, mem_bytes, clients, mem` for redis. Same 30 s windows and endpoint filter as `rules.yml`. Container status/restart count/start time come from the Docker socket (mounted read-only). An import-time assert rejects any query containing `fault_`. NaN and missing data become `null`.
- `app.py`: endpoints. A new incident waits `SETTLE_SECONDS` (10 s) so cause and symptom alerts go out in one `open` message; later changes go out as `updated`, then `resolved`. Each alert in the message has `value` (from the fresh context) and `threshold`.

| Endpoint | Purpose |
|---|---|
| `POST /alerts` | Alertmanager webhook |
| `POST /anomalies` | ML detector: `{service, score, top_features}` (`fault_*` features dropped) |
| `POST /responses`, or a message on `/ws/responses` | ResponsePlan from the analyzer |
| `/ws/events` | raw alerts (`type: alert`) and incidents (`type: incident`) |
| `/ws/responses` | plans (`type: response_plan`) |
| `GET /events`, `/responses`, `/incidents`, `/incidents/{id}`, `/health` | inspection |

Clients get the last 100 messages replayed on connect (`"replay": true`).

**Tests:** `cd gateway && pip install -r requirements-dev.txt && pytest -q`: 14 tests (grouping, context builder against a fake Prometheus, endpoints, both WebSockets). All pass.

**End-to-end (real Docker, scenario 4, 6 Oct):** fault injected 16:54:27 → HighLatency on api-service and frontend at 16:55:07 (40 s) → one incident `open` at 16:55:17 → `resolved` at 16:57:07. The context separated cause from symptom: frontend `upstream_p95` 7.4 s = its own p95; api-service `upstream_p95` 0.005 s. The event is ~2.7 KB; no `fault_` anywhere.

## Step 6: Analyzer + runbooks, Phase 4 started (6 Oct)

- `analyzer/schemas.py`: the shared contract. `IncidentEvent` (tolerant, strips `fault_*` at any depth) and `ResponsePlan` (strict: action allowlist, known targets, confidence 0–1, no `reset_faults` on redis; only `escalate` may have a null target).
- `runbooks/*.yaml` + `analyzer/runbooks.py`: baseline B1 and the LLM fallback. Priority: monitoring-only → redis down → service down → memory → CPU → errors → latency → ML memory anomaly; no match → escalate. Root cause from topology and context only (latency: a service is "explained" by its upstream when `upstream_p95 ≥ 0.5 × p95` and the dependency is slow). Skips actions already in `history.previous_actions`.
- `analyzer/llm.py`: Ollama `/api/chat` with the ResponsePlan JSON schema as `format`, temperature 0. Falls back to the runbook on `unreachable`, `timeout`, `invalid_json`, `schema_error`, `invalid_action`, `low_confidence` (< 0.7), etc.; the reason is in `fallback_reason`.
- `analyzer/analyzer.py`: `serve` (WebSocket → one worker with per-incident coalescing → `POST /responses`) and `analyze <sample.json> [--mode runbook|llm]`.
- `analyzer/samples/scenario1..9.json`: hand-written IncidentEvents. Runbook mode gives the §10 root cause and action for all 9.
- Compose service `analyzer`; `ANALYZER_MODE=runbook` runs baseline B1.

**Tests:** `cd analyzer && pip install -r requirements-dev.txt && python -m pytest tests`: 75 pass (Ollama mocked).

## Step 7: Response system + verifier, Phases 5–6 (6 Oct, session 3)

Session log: `SESSION_NOTES.txt`.

```
analyzer --ResponsePlan--> gateway /ws/responses --> responder
   responder: pre-check alerts still active -> policy validator -> execute | approval | escalate
            -> wait 45 s -> verify (Prometheus ALERTS for the incident's alerts)
            -> verified | unresolved -> POST gateway /incidents/{id}/reanalyze (attempt+1, previous_actions)
            -> analyzer again (skips actions already tried) -> ... -> after 3 attempts: escalate
   every outcome -> POST gateway /actions -> /ws/responses ("type": "action") + incident history + SQLite store
```

- `responder/policy.py` + `policies.yaml`: the validator (pure, unit-tested). Recommended action first, then the fallback; nothing valid → escalate. Low confidence or `requires_approval` → human.
- `responder/executor.py`: the only code that changes anything; re-checks the allowlist itself. No shell commands built from plan text.
- `responder/app.py`: one plan per incident at a time (plans while an action runs, is verified or awaits approval are skipped; plans from an earlier attempt are ignored). **Pre-check:** right before executing, the incident's alerts are re-checked and the action is skipped if they already cleared (alerts trail the fault by up to the 30 s rate window). `RESPONDER_MODE=dry_run` validates and reports without executing (baseline B0). `ESCALATION_WEBHOOK` (optional, Slack/Discord).
- Gateway: `POST /actions` (executed/failed actions become `history.previous_actions`), `POST /incidents/{id}/reanalyze` (re-sends the incident as status `reanalyze`), `GET /history`, `GET /history/{id}` (SQLite store). The analyzer now also analyzes `reanalyze` incidents.

**Tests:** gateway 17, analyzer 75, responder 27, all pass.

**End-to-end on real containers (6 Oct, runbook mode because Ollama isn't installed):**

| Run | Detected | Action | Result | Injector `end_reason` |
|---|---|---|---|---|
| Scenario 4, latency api-service | HighLatency ×2 | `reset_faults` api-service | verified | remediated after 45 s (planned 180 s) |
| Scenario 6, redis stopped | RedisDown (+ late HighErrorRate ×2 joined) | `restart_container` redis; the late "updated" plan was skipped (verification in progress) | verified | remediated after 38 s |
| Recurring latency (fault re-injected once after the reset) | HighLatency ×2 | `reset_faults` → still firing → re-analysis attempt 2 → analyzer chose `restart_container` → blocked by cooldown | escalated | (manual test, not logged) |
| Scenario 7, frontend stopped | ServiceDown | `restart_container` frontend | verified | remediated after 43 s |
| Scenario 5, errors api-service | HighErrorRate ×2 | `reset_faults` api-service; gateway restarted during verify | escalated (incident unknown after restart), no second action | remediated after 48 s |

Found while testing: a plan can arrive after the fault is gone (an alert fired 30 s after a manual reset) and the responder restarted api-service for nothing. That led to the pre-check above.

**Minimal UI + approval check (6 Oct):** `dashboard/index.html`, served by the gateway (`DASHBOARD_DIR`), live over both WebSockets, polls the responder's `/approvals` (responder allows CORS only from `DASHBOARD_ORIGINS`, default `localhost:8000`). All system text is inserted with `textContent`. Live check: a demo plan recommending `flush_cache` on redis was queued (`pending_approval`) and rejected through `POST /approvals/<id>/reject` with the dashboard's Origin; nothing ran and redis data was untouched.

## Step 8: Evaluation scorer + adversarial safety suite (6 Oct, session 4)

**`experiments/score.py`** joins `ground_truth.csv` with `incidents.db` and prints a per-run table and a summary of the §10 metrics:

| Objective | Metric |
|---|---|
| O2 | recall, precision (false-positive incidents), MTTD |
| O3 | root-cause accuracy (first plan) |
| O4 | plan / executed action accuracy (acceptable actions per §10: scenarios 1–2 accept reset or restart), unsafe actions executed, collateral actions |
| O5 | auto-resolved % (`end_reason == remediated`), verified %, escalated %, attempts |
| O6 | MTTR (fault start → fault gone) |
| cost | LLM share of plans, plan latency |

Use one `ground_truth.csv` per system or filter with `--since/--until`, e.g. `python experiments/score.py --system B1 --since 2026-10-06T17:17:00Z --out b1.csv` (`--json` for the summary). Runs are matched to the first incident opened between the fault start and 60 s after it ended. Real data so far (scenario 5 only, the store started then): MTTD 32.5 s, root cause + action correct, MTTR 48.4 s.

**`experiments/safety_suite.py`**: 29 hallucinated, malformed and malicious plans through the real `Responder.handle_plan` with a recording executor. Cases include invented actions, shell text in type/target, unknown or self targets, `reset_faults` on redis, lists instead of strings, NaN/inf/bool/string confidence, risky actions, cooldown + malicious fallback, max actions, malformed attempt/incident_id. **Result: 29/29 pass, 0 unsafe actions executed, 27/27 adversarial plans blocked or sent to a human; 7 of them only the responder caught (the analyzer schema would have accepted them).** Table for the report: `python experiments/safety_suite.py --csv safety.csv`.

**Bugs the suite found, fixed:**
- `confidence: NaN` executed without approval (`nan < 0.7` is False); `true` counted as 1.0 (bool is an int). Now confidence must be a real number in [0, 1] (`policy.valid_confidence`).
- A list as action type/target crashed the validator; a non-int `attempt` or list `incident_id` crashed `handle_plan`. Now rejected cleanly.
- Live test found more: the gateway accepted `NaN`/`Infinity` in JSON (Python's parser allows them). One such plan made `GET /approvals` (responder) and `GET /responses` (gateway) return 500, which breaks the dashboard's approval queue. Every gateway input (HTTP and WebSocket) now rejects them with 400, and the responder skips such messages.

**Tests:** gateway 19, analyzer 75, responder 42, experiments 10 (`pytest experiments/tests`), all pass.

## Step 9: First LLM results, baseline exporter, decisions (6 Oct, session 5)

**Ollama + llama3.1:8b on the host** (Homebrew, launchd service; the analyzer container reaches it via `host.docker.internal`).

**Offline, 9 hand-written samples** (`python experiments/compare_analyzers.py`, runbook mode vs llm mode, scored with the §10 rules from `score.py`):

| System | Root cause | Action | Latency |
|---|---|---|---|
| B1 runbooks | 9/9 | 9/9 | ~0 s |
| B2 llama3.1:8b | 9/9 | 8/9 | mean 17 s, max 21 s (no fallbacks) |

- The LLM's miss: scenario 5 (error fault) → `restart_container` (confidence 0.95) instead of `reset_faults`. It would also fix the fault, but it is the heavier action. **Prompt-tuning item for Riddhima.**
- Caveats: the samples and the runbooks were written together, so B1's 100% is biased upward; scenario 4 matches a few-shot example in the prompt.

**Live, first LLM-driven fix (scenario 4, real containers):** detected 30.6 s → LLM plan in 22.2 s (`source: llm`, root api-service, `reset_faults`) → executed → verified. Injector: remediated after 68.6 s, vs 45 s in runbook mode. The ~22 s gap is the LLM's analysis time, the cost metric in §10. Scored by `score.py` (`--system B2-llm --since 2026-10-06T17:41:00Z`).

**`experiments/record_baseline.py`**: exports the ML detector's training data from Prometheus (the gateway's context queries, 15 s step, per service). Drops samples near injected runs *and* near any pending/firing alert (manual demo faults aren't in `ground_truth.csv`; the first test export was contaminated by one). Prometheus has no volume: export before rebuilding it.

**Decisions recorded:** scenario 3 = restart only; cooldown stays 300 s, suites run with `--gap 300` (§10 of the plan).

**Other:** dashboard checked visually in headless Chrome (feeds live, incident timeline, approvals). The responder's verified-record field is now `open_to_verified_s` (incident opened → verified), so it can't be confused with the evaluation's MTTR (fault start → fault gone). `PATENT_CHANGES.md` section M: dependent claims 8–13 + preliminary evidence.

**Still blocked:** the Docker Desktop containerd setting (macOS denied access to Docker Desktop's settings file; it has to be changed in the UI).
