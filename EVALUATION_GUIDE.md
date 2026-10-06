# Evaluation Guide: What's Built, How to Use It, What to Show

**Project:** Intelligent DevOps Monitoring & Incident Response System (Sharda University, final year)
**Covers:** Phase 1 (base setup) and Phase 2 (monitoring + multi-service), as of 4 Oct 2026
**Detailed log:** `PROGRESS.md` · **Plan:** `SUGGESTED_PLAN.md`

---

## 1. Where we are in the full system

The full system is a closed loop:

```
Monitor → Detect → Analyze (LLM) → Decide (policy validator) → Respond → Verify
  ✅        ✅ rules     ⏳             ⏳                         ⏳         ⏳
            ⏳ ML
```

What is built so far is the **Monitor** and **Detect (rules)** stages, plus the **test environment** used to evaluate the rest:

| Part | What it does | Status |
|---|---|---|R˳
| Demo app (3 services) | A small realistic system to monitor and break | ✅ |
| Fault injection API | Lets us break any service in a controlled way | ✅ |
| Prometheus + exporters | Collects app, container and Redis metrics | ✅ |
| Alert rules | 7 alerts covering CPU, memory, latency, errors, downtime | ✅ |
| Alertmanager | Groups alerts and sends them to the gateway | ✅ |
| Fault injector + ground truth | Runs the 9 evaluation scenarios and logs what really happened | ✅ |
| Load generator (Locust) | Steady user traffic, needed for the HTTP alerts | ✅ |
| Event Gateway + WebSocket | Receives alerts, groups them into incidents | ⏳ Next (Phase 3) |
| LLM analyzer, validator, executor, verifier, ML detector, dashboard | | ⏳ Phases 4–8 |

---

## 2. What each part is

### 2.1 Demo application

```
Locust (load) → frontend :5001 → api-service :5002 → redis :6379
```

- **frontend** (`app/`): a Flask service. `GET /` calls `api-service`.
- **api-service** (`api-service/`): a Flask service. `GET /data` increments a counter in Redis.
- **redis**: the data store.

Each Flask service also has:

| Endpoint | Purpose |
|---|---|
| `/health` | Healthcheck; also reports which faults are active |
| `/metrics` | Prometheus metrics |
| `POST /inject` | Start a fault: `cpu`, `memory`, `latency` or `error` |
| `POST /reset` | Stop all faults immediately |

**Failures travel upstream, like in real systems.** If Redis stops, `api-service` returns 503 and `frontend` returns 502. If `api-service` is slow, `frontend` is slow too. Each service records `upstream_request_duration_seconds`, the time spent waiting on the next service. **This is what lets the system tell the root cause from a symptom**, which is the core of the later LLM analysis.

### 2.2 Monitoring

| Component | Port | Collects |
|---|---|---|
| Prometheus | 9090 | Everything below, every few seconds |
| cAdvisor | 8080 | Container CPU and memory |
| redis_exporter | 9121 | Whether Redis is up, operations per second |
| Flask `/metrics` | 5001, 5002 | Request count, latency histogram, status codes, upstream latency |

### 2.3 Alert rules (`prometheus/rules.yml`)

| Alert | Fires when | Severity |
|---|---|---|
| HighCPU | CPU > 80% of the container limit | warning |
| HighMemory | Memory > 80% of the 512 MB limit | warning |
| HighLatency | p95 latency > 1 s | warning |
| HighErrorRate | > 10% of requests return 5xx | critical |
| ServiceDown | Prometheus can't reach `frontend` or `api-service` | critical |
| RedisDown | Redis is unreachable | critical |
| ExporterDown | A monitoring exporter itself has stopped | warning |

- Every alert carries a `service` label so the gateway knows where it came from.
- **Detection takes about 35–40 s** (30 s rate window + 20 s `for`). The plan's original 1-minute window was too slow for short faults, so we tuned it.
- All rules are unit-tested with `promtool` (each alert fires, and a healthy system stays silent).

### 2.4 Alertmanager (`alertmanager/alertmanager.yml`, port 9093)

- Groups alerts by `alertname` + `service` and sends them to `http://gateway:8000/alerts`.
- Sends a "resolved" notification when a problem clears (the verifier will use this).
- If a service is down, its own latency and error alerts are suppressed to cut noise.

### 2.5 Fault injector (`injector/injector.py`) — the evaluation harness

Runs the 9 scenarios from §10 of the plan:

| # | Scenario | Target | Correct fix |
|---|---|---|---|
| 1 | CPU spike | frontend | reset_faults |
| 2 | CPU spike | api-service | reset_faults |
| 3 | Memory spike (420 MB) | api-service | restart_container |
| 4 | Latency (5 s per request) | api-service | reset_faults |
| 5 | Errors (HTTP 500) | api-service | reset_faults |
| 6 | Redis stopped | redis | restart_container |
| 7 | Container stopped | frontend | restart_container |
| 8 | Slow memory leak (440 MB over 240 s) | api-service | restart_container |
| 9 | CPU + latency together | api-service | reset_faults |

**Ground truth:** each run appends a row to `experiments/ground_truth.csv` with the scenario, start time, planned end, actual end and an `end_reason`:

| `end_reason` | Meaning |
|---|---|
| `expired` | The fault ran its full time; nothing fixed it |
| `remediated` | The fault disappeared early, so **our system fixed it** |
| `cleanup` | The injector had to undo it itself |

MTTR and the auto-resolve rate are computed from the `remediated` rows. The `fault_*_active` gauges are used **only** for this scoring and are never shown to the detector or the LLM, so the system can't cheat.

### 2.6 Load generator (`load/locustfile.py`)

About 5 requests per second to `frontend`, always running. Latency and error alerts need real traffic to measure.

---

## 3. How to use it

### Start everything

```bash
docker compose up --build
```

| Open | URL |
|---|---|
| Prometheus targets (all should be UP) | http://localhost:9090/targets |
| Prometheus alerts | http://localhost:9090/alerts |
| Alertmanager | http://localhost:9093 |
| cAdvisor | http://localhost:8080 |
| frontend | http://localhost:5001 |
| api-service | http://localhost:5002/data |

### Break things by hand

```bash
curl localhost:5001/                     # normal request through all 3 services
curl localhost:5002/health               # see active faults

curl -X POST localhost:5002/inject -H 'Content-Type: application/json' \
     -d '{"fault":"latency","duration":120}'
curl -X POST localhost:5002/inject -H 'Content-Type: application/json' \
     -d '{"fault":"memory","duration":180,"size_mb":420}'
curl -X POST localhost:5002/reset        # stop all faults

docker stop redis                        # dependency failure
docker start redis
```

`/inject` options: `fault` = `cpu | memory | latency | error`, `duration` 1–600 s, `size_mb` 10–450, `ramp_seconds` (memory grows gradually).

### Run scenarios with the injector

**From the browser:** open http://localhost:8088 (the `injector-ui` service starts with `docker compose up`). From there you can run one scenario or a suite, cancel a run, inject manual faults, stop or start containers, and reset everything. You can also watch the Prometheus alerts and the latest ground-truth rows. Scenario runs write to `ground_truth.csv` just like the CLI. Manual faults are demo-only, aren't logged, and are disabled while a run is in progress.

**From the terminal:**

```bash
docker compose run --rm injector list                     # show scenarios 1–9
docker compose run --rm injector run 4 --duration 180     # one scenario
docker compose run --rm injector suite --scenarios 1-9 --repeat 3 --shuffle --seed 1 --gap 60
docker compose run --rm injector random --count 5         # random scenarios
docker compose run --rm injector reset                    # undo everything
```

Results land in `experiments/ground_truth.csv`.

### Run the rule tests

```bash
cd prometheus && promtool test rules rules_test.yml
promtool check rules prometheus/rules.yml
amtool check-config alertmanager/alertmanager.yml
```

(`promtool` and `amtool` come from the Prometheus and Alertmanager GitHub release downloads.)

---

## 4. What to show at the evaluation

About 10 minutes. Start the stack **5 minutes before** so Prometheus has data and the load is running.

### Demo 1 — The system is healthy (1 min)
1. Open http://localhost:9090/targets: all targets are UP.
2. `curl localhost:5001/` → 200, the request went frontend → api-service → redis.
3. http://localhost:9090/alerts: nothing firing.

**Say:** "This is a 3-service system with real traffic. Prometheus is watching app metrics, container metrics and Redis."

### Demo 2 — Detection and root cause vs symptom (3 min) ⭐ main demo
1. `docker compose run --rm injector run 4 --duration 180` (latency in `api-service`).
2. `curl localhost:5001/` is now slow (~5 s).
3. In Prometheus, graph `histogram_quantile(0.95, sum by (le, job) (rate(http_request_duration_seconds_bucket[30s])))`: both services are slow.
4. Then graph `upstream_request_duration_seconds` for each service: `frontend`'s upstream is slow, but `api-service`'s Redis call is fast (~4 ms). **So the cause is `api-service`, not `frontend` or Redis.**
5. After ~40 s, http://localhost:9090/alerts shows **HighLatency on both** services, and they appear in Alertmanager (http://localhost:9093).

**Say:** "A rule-based tool raises two alerts and can't tell which is the cause. Our metrics carry the evidence, and the gateway + LLM we build next will use it to name `api-service` as the root cause and fix only that."

### Demo 3 — Dependency failure (2 min)
1. `docker stop redis`
2. `curl localhost:5001/` → 502 instantly; `curl localhost:5002/data` → 503.
3. Alerts: **RedisDown**, plus HighErrorRate on `api-service` and `frontend`.
4. `docker start redis` → alerts send "resolved".

**Say:** "One failure deep in the chain makes three alerts. Grouping them into one incident is Phase 3."

### Demo 4 — Memory and resource faults (1 min, optional)
- `docker compose run --rm injector run 3` and watch http://localhost:8080 or `container_memory_working_set_bytes{name="api-service"}` climb past 80% → **HighMemory**.

### Demo 5 — Evaluation harness (2 min)
1. Open `injector/injector.py` scenario list (`injector list`).
2. Show `experiments/ground_truth.csv` and explain `expired / remediated / cleanup`.
3. Run `promtool test rules rules_test.yml`: all tests pass.

**Say:** "Every experiment is logged with ground truth, so detection time, root-cause accuracy and MTTR will be measured automatically, not by hand. The fault flags are kept out of the detector and LLM so the results are honest."

### Demo 6 — Roadmap (1 min)
Show §9 of `SUGGESTED_PLAN.md`: gateway next, then LLM engine, response system, verify loop (mid-term demo late Jan), ML detector, dashboard, evaluation against baselines B0/B1/B2.

---

## 5. Likely questions and answers

| Question | Answer |
|---|---|
| Why not just use Prometheus alerts? | Alerts say *what* is wrong, not *why*. One fault raises alerts on several services. Our system finds the root cause and fixes it safely. |
| How do you tell cause from symptom? | `upstream_request_duration_seconds`: if a service is slow but its upstream call is fast, the problem is inside that service. |
| Why 30 s windows instead of 1 min? | With 1 min a CPU fault takes ~78 s to alert, so a 30 s fault would never be detected. Now detection is ~40 s. |
| How do you avoid cheating in the evaluation? | `fault_*_active` gauges are ground truth only. They are excluded from rules, the ML detector and the LLM input. |
| What stops the LLM doing something dangerous? | (Planned) The LLM never acts directly. A validator checks an allowlist of actions, known targets, confidence ≥ 0.7, a 5 min cooldown, max 3 actions per incident, and human approval for risky ones. YAML runbooks are the fallback. |
| Why a slow-leak scenario (8)? | It stays under the 80% threshold for a long time, so rules miss it. It shows the value of the ML detector. |
| Why Docker Compose, not Kubernetes? | It runs on a laptop for the demo; Kubernetes is future work. |
| Why were Redis retries turned off? | With retries, Redis being down looked like 4 s of latency instead of an error, which would mislead the analysis. |

---

## 6. Known limitations (be upfront)

- Container-level alerts (CPU, memory, `docker stop`) were tested with unit tests and a fake Docker client; the first full Docker run is the first item in `PROGRESS.md` → Next steps. **Do a full rehearsal under Docker before the evaluation.**
- The gateway isn't built yet, so Alertmanager logs failed deliveries to `gateway:8000`. This is expected.
- HTTP alerts need traffic; if the `load` service is stopped they won't fire.
- "Resolved" notifications repeat the old annotation text, so values in them are stale.
