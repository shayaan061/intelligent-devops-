# Progress Log: Phase 2 (Monitoring + Multi-service)

**Date:** 3 Oct 2026 · **Last updated:** 4 Oct 2026
**Plan:** `SUGGESTED_PLAN.md` §3 (fixes) and §15 (immediate next steps)
**Status:** Phase 2 is complete (commit `9415a44`). Phase 3 (Event Gateway) is next. See [Next steps](#next-steps) and `EVALUATION_GUIDE.md` for how to run and demo what exists.

| §15 item | Status |
|---|---|
| Fix the `latency`/`error` duration bug and histogram recording | ✅ Done |
| Add `api-service` + Redis + redis_exporter + cAdvisor | ✅ Done |
| Write `prometheus/rules.yml` and `alertmanager/alertmanager.yml` | ✅ Done |
| Implement `injector/injector.py` with ground-truth logging | ✅ Done |
| Skeleton gateway: `/alerts` → print → WebSocket broadcast | ✅ Code done, smoke-tested; Docker end-to-end test pending (Step 4) |

> Everything was tested locally against the real Flask services, Prometheus 2.54.1 and Alertmanager 0.27.0 binaries.
> **Not yet run under Docker** because the daemon was off. Container-level parts (cAdvisor, the CPU/memory alerts, `docker stop` scenarios) are covered by unit tests or a fake Docker client only. First thing to do: `docker compose up --build` and check `localhost:9090/targets`.

---

## Next steps

In order. Owners follow the work split in `SUGGESTED_PLAN.md` §9.

### A. Close out Phase 2 (before starting the gateway)
- [ ] **Run the stack under Docker for the first time.** `docker compose up --build`, then check that all 4 targets are `UP` at `localhost:9090/targets` (`frontend`, `api-service`, `redis`, `cadvisor`).
- [ ] **Check cAdvisor's labels on macOS.** The CPU/memory rules match `name=~"frontend|api-service"`. Confirm at `localhost:9090/graph` with `container_memory_working_set_bytes{name="api-service"}`. If the series is missing or named differently, fix `rules.yml` *and* `rules_test.yml`.
- [ ] **Run each scenario once for real** and note the alert and detection time: `docker compose run --rm injector run <1-9> --duration 180`. Scenarios 1, 2, 3, 6 and 7 have never fired on real containers.
- [ ] **Scenario 8 should not fire HighMemory early.** It is meant to be caught by ML only. Check how long the ramp stays under 80%.
- [ ] **Decide scoring for scenario 3:** accept `reset_faults` as well as `restart_container`, or only the restart. Write the decision into §10 of the plan.
- [ ] **Update the §6.1 table in `SUGGESTED_PLAN.md`** to the real windows (30 s rate, `for: 20s`) and fault caps (600 s, 450 MB).

### B. Phase 3, part 1: skeleton gateway (§15, last item). Owner: Shayaan
Detailed checklist in [Step 4](#step-4-skeleton-event-gateway--to-do-later) below. Summary:
- [x] `gateway/` FastAPI service: `POST /alerts`, `GET /health`, WebSocket `/ws/events`
- [x] Compose service named `gateway` on port 8000
- [ ] End-to-end test: injector → Prometheus → Alertmanager → gateway → WebSocket client
- [x] Tick the last box in §15 of `SUGGESTED_PLAN.md`

### C. Phase 3, part 2 (Oct week 4 – Nov week 1)
- [ ] Grouping: events within 60 s along `frontend → api-service → redis` become one incident with an `incident_id`
- [ ] Context builder: last 10 min of CPU, memory, p95, error rate and `upstream_p95` per service, through the Prometheus HTTP API
- [ ] Emit the full `IncidentEvent` JSON (§6.3), with `fault_*` metrics filtered out
- [ ] `POST /anomalies` stub for the ML detector, and the `/ws/responses` channel

### D. Can start in parallel
- [ ] **Riddhima:** LLM prompt and `ResponsePlan` schema (§6.4), using hand-written `IncidentEvent` samples; YAML runbooks for scenarios 1–9 (these are also baseline B1)
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
