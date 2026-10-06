# Intelligent DevOps Monitoring & Incident Response System
### Final Year Project — Suggested Plan (Hybrid: Patent-Aligned + ML Enhancements)

**Team:** Muhammad Shayaan Ali · Riddhima Sharma · Shruti Tyagi
**Guide:** Ashish Kumar (Assistant Professor, CSE), Sharda University
**Plan date:** 1 Oct 2026 · **Target completion:** Apr 2027

> This plan uses the patent-aligned design (`PATENT_ALIGNED_PLAN.md`) as its base and adds three ideas from the ML-centric plan (`PROJECT_PLAN.md`). The reasoning is in `PLAN_COMPARISON.md`.
> 1. An **ML anomaly detector** that runs alongside the Prometheus alert rules
> 2. A **multi-service demo app** (3 services), so finding the root cause is a real problem
> 3. **YAML runbooks** used both as the fallback when the LLM fails and as the "no LLM" baseline

---

## 1. Core Idea

```
Monitor → Detect → Analyze → Decide → Respond → Verify  (→ loop)

Prometheus rules + ML detector → WebSocket layer → LLM Analysis Engine
        → Safety/Policy Validator → Response System → Verification
```

**Problem.** Conventional monitoring only raises alerts. Engineers still correlate the metrics across services, find the cause, choose a fix, apply it and check the result by hand. That leaves a gap between *detection* and *resolution*.

**Solution.** An intelligent layer between the monitoring stack and the response stack. It has three parts:
- **Detects problems in two ways**: fixed rules for known failures and ML for unknown ones.
- **Analyzes with an LLM**: reads the context across services, finds the probable root-cause service, and proposes a structured fix.
- **Responds safely**: a policy validator, an executor, a verifier, and a re-analysis loop with an attempt limit.

### Novel elements to claim in the patent
1. **Context builder**: when an alert fires, automatically collects the related metrics *across all dependent services* from the time window around it.
2. **Safety validator between the LLM and the executor**: an allowlist of actions, schema validation, a confidence threshold, cooldowns and human approval. The LLM never runs anything directly.
3. **Re-analysis that remembers past attempts**: if verification fails, the actions already tried go back into the LLM, the attempt count is capped, and then the incident is escalated.
4. **Two detectors (rules + ML) feeding one incident format**, with deterministic runbooks as the fallback when the LLM fails.

---

## 2. Objectives

| # | Objective | Target |
|---|-----------|--------|
| O1 | Monitor all 3 services and their containers | 100% of services instrumented |
| O2 | Detect injected faults (rules + ML) | Recall ≥ 0.90, false positives ≤ 10% |
| O3 | Identify the correct root-cause service and fault type | ≥ 80% accuracy |
| O4 | Recommend a safe, correct action | ≥ 85% correct; 0 unsafe actions executed |
| O5 | Resolve faults without human help | ≥ 60% auto-resolved and verified |
| O6 | Reduce MTTR | ≥ 50% faster than fixing by hand |

---

## 3. Current Status

| Component | Status | Notes |
|-----------|--------|-------|
| `app/` Flask test app | ✅ Done | `/`, `/health`, `/metrics`, `/inject`, `/reset` |
| Prometheus | ✅ Done | Scrapes the app every 5 s |
| `docker-compose.yml` | ✅ Done | app + Prometheus |
| `injector/` | ⚠️ Empty | |
| Alert rules / Alertmanager / cAdvisor | ❌ | |
| Additional services (API, Redis) | ❌ | |
| Gateway, ML detector, LLM engine, Responder, Verifier, Dashboard | ❌ | |

### Fixes needed in the existing code
1. **`latency` and `error` faults ignore `duration`** and never clear themselves. Add a timer thread.
2. **Errors and slow requests are not recorded properly.** The latency histogram is skipped on the error path. Use `REQUEST_LATENCY.labels(...).time()` or a `finally` block.
3. **`fault_*_active` gauges are ground truth.** Never pass them to the LLM or the ML detector; use them only for scoring.
4. **No container metrics.** Add cAdvisor.
5. **No restart policy or healthcheck.** Add `restart: unless-stopped` and a `healthcheck`.

---

## 4. Demo Application (multi-service)

```
   Locust load
       │
       ▼
 ┌───────────┐  HTTP   ┌────────────┐  TCP   ┌─────────┐
 │  frontend │ ──────▶ │ api-service│ ─────▶ │  redis  │
 │  (Flask)  │         │  (Flask)   │        │ (cache) │
 └───────────┘         └────────────┘        └─────────┘
   existing app          new, small           off-the-shelf
```

- **frontend**: the existing `app/`. It calls `api-service` for its data.
- **api-service**: a new small Flask service with the same `/metrics`, `/inject` and `/reset` endpoints. It reads and writes Redis.
- **redis**: monitored with **redis_exporter**.
- Each service exposes `http_requests_total`, `http_request_duration_seconds`, and `upstream_request_duration_seconds` (time spent calling the next service).
- **Why bother:** a fault in `api-service` or `redis` also shows up as latency or errors in `frontend`. The system has to point to the *real* cause, not the service showing the symptom.

---

## 5. System Architecture

```
 ┌─────────────────────────────────────────────────────────────────┐
 │ DevOps Infrastructure (Docker Compose)                           │
 │ frontend · api-service · redis · cAdvisor · redis_exporter       │
 └───────────────┬─────────────────────────────────────────────────┘
                 │ metrics (5s)
                 ▼
 ┌─────────────────────────┐  rules.yml  ┌──────────────┐
 │       Prometheus         │───────────▶│ Alertmanager │──┐ webhook
 └──────┬──────────┬───────┘             └──────────────┘  │
        │ PromQL   │ PromQL (poll 15s)                      │
        │          ▼                                        │
        │   ┌────────────────────┐  anomaly event           │
        │   │  ML Anomaly        │──────────────────────┐   │
        │   │  Detector          │                      │   │
        │   │ (IsolationForest + │                      ▼   ▼
        │   │  z-score)          │          ┌───────────────────────────┐
        │   └────────────────────┘          │ Event Gateway (FastAPI)    │
        └──────────────────────────────────▶│ dedup · group · context    │
                                            │ builder · WebSocket hub    │
                                            └─────────────┬─────────────┘
                                                          │ IncidentEvent (WS)
                                                          ▼
                                            ┌───────────────────────────┐
                                            │ LLM Analysis Engine        │
                                            │ root cause · response plan │
                                            │ fallback: YAML runbooks    │
                                            └─────────────┬─────────────┘
                                                          │ ResponsePlan (WS)
                                                          ▼
                                            ┌───────────────────────────┐
                                            │ Response System            │
                                            │ Policy Validator → Executor│
                                            │        └─▶ Human approval  │
                                            └─────────────┬─────────────┘
                                                          ▼
                                            ┌───────────────────────────┐
                                            │ Verifier → resolved?       │
                                            │ no → re-analyze (max 3)    │
                                            │ then escalate              │
                                            └─────────────┬─────────────┘
                                                          ▼
                                       Incident Store (SQLite/Postgres) + Dashboard
```

---

## 6. Module Design

### 6.1 Monitoring & Rule-Based Detection
`prometheus/rules.yml` (one rule per service where it applies):

| Alert | Example expression | For |
|-------|--------------------|-----|
| HighCPU | `rate(container_cpu_usage_seconds_total{name=~"frontend\|api-service"}[1m]) > 0.8` | 30s |
| HighMemory | `container_memory_usage_bytes / container_spec_memory_limit_bytes > 0.8` | 30s |
| HighLatency | `histogram_quantile(0.95, sum by (le, job) (rate(http_request_duration_seconds_bucket[1m]))) > 1` | 30s |
| HighErrorRate | `sum by (job) (rate(http_requests_total{status=~"5.."}[1m])) / sum by (job) (rate(http_requests_total[1m])) > 0.1` | 30s |
| ServiceDown | `up == 0` | 15s |
| RedisDown | `redis_up == 0` | 15s |

Alertmanager sends each alert to the gateway as a `POST /alerts` webhook.

### 6.2 ML Anomaly Detector (from Plan A)
- **Input**: every 15 s, polls these features per service through PromQL: CPU, memory ratio, p95 latency, error rate, requests per second, upstream latency.
- **Models**:
  - **Rolling z-score / EWMA** for each metric. Simple and easy to explain.
  - **Isolation Forest** across all the metrics together, trained on 1–2 hours of normal traffic.
- **Output**: an `IncidentEvent` with `source: "ml"`, an anomaly score and the top contributing features.
- **Value**: catches anomalies that no rule covers, such as a gradual memory rise or small increases in latency and errors at the same time. It is also the ML part claimed in the patent's field of invention.
- Saved with `joblib`. Retraining is a script (`ml/train.py`).

### 6.3 Event Gateway & WebSocket Layer
- FastAPI service with:
  - `POST /alerts` (Alertmanager)
  - `POST /anomalies` (ML detector)
  - WebSocket `/ws/events` and `/ws/responses`
- **Dedup and grouping**: events within a 60 s window that share a dependency chain become one incident.
- **Context builder**: for every service in the chain, collects the last 10 minutes of the key metrics, container state and restarts, recent actions, and the dependency map.

```json
{
  "incident_id": "inc-0042",
  "timestamp": "2026-11-10T12:30:05Z",
  "sources": ["rule", "ml"],
  "alerts": [
    {"name": "HighLatency", "service": "frontend", "value": 5.1, "threshold": 1}
  ],
  "ml_anomalies": [
    {"service": "api-service", "score": 0.91, "top_features": ["p95_latency", "upstream_latency"]}
  ],
  "topology": {"frontend": ["api-service"], "api-service": ["redis"], "redis": []},
  "context": {
    "frontend":    {"cpu": 0.10, "mem": 0.30, "p95": 5.1, "err": 0.0, "upstream_p95": 5.0},
    "api-service": {"cpu": 0.12, "mem": 0.28, "p95": 5.0, "err": 0.0, "upstream_p95": 0.002},
    "redis":       {"up": 1, "ops": 40}
  },
  "history": {"attempt": 1, "previous_actions": []}
}
```

### 6.4 LLM Analysis Engine
- Subscribes to `/ws/events` and publishes on `/ws/responses`.
- The prompt contains: the system role, the topology, the list of allowed actions, a few examples, and the incident event.
- **The output is validated with Pydantic:**

```json
{
  "incident_id": "inc-0042",
  "root_cause_service": "api-service",
  "incident_type": "latency_degradation",
  "severity": "high",
  "probable_cause": "api-service handler is delayed ~5s; its upstream (redis) is healthy, so frontend latency is a downstream symptom.",
  "evidence": ["api-service p95 5.0s", "api-service upstream_p95 2ms", "frontend upstream_p95 ≈ its own p95"],
  "confidence": 0.84,
  "recommended_action": {"type": "reset_faults", "target": "api-service"},
  "fallback_action": {"type": "restart_container", "target": "api-service"},
  "explanation": "..."
}
```

- **Models**: the Claude API, or a local model through **Ollama**. Compare both in the evaluation.
- **Fallback runbooks** (`runbooks/*.yaml`, from Plan A) are used when the LLM times out, returns invalid JSON, or reports low confidence:

```yaml
- name: service-down
  match: { alert: ServiceDown }
  root_cause: "{{alert.service}}"
  action: restart_container
  requires_approval: false

- name: high-error-rate
  match: { alert: HighErrorRate }
  root_cause: deepest_service_with_errors
  action: reset_faults
  fallback: restart_container

- name: high-memory
  match: { alert: HighMemory }
  action: restart_container
```

### 6.5 Response System
**Policy Validator** (`responder/policies.yaml`). An action runs only if all of these pass:
- The action type is on the allowlist (no arbitrary shell commands).
- The target is in the known service list.
- `confidence ≥ 0.7`; otherwise it goes to a human.
- Cooldown: no repeat of the same action on the same target within 5 minutes.
- At most 3 automatic actions per incident.
- Risky actions need approval.

**Executor (Docker SDK / HTTP)**

| Action | Implementation | Mode |
|--------|----------------|------|
| `reset_faults` | `POST /reset` on the target | auto |
| `restart_container` | `client.containers.get(name).restart()` | auto |
| `flush_cache` | `redis-cli FLUSHALL` via exec (demo only) | approval |
| `update_resources` | `container.update(mem_limit=..., cpu_quota=...)` | approval |
| `escalate` | Dashboard alert and Slack/Discord webhook | always |

### 6.6 Verifier & Re-analysis Loop
1. Wait 30–60 s for the system to settle.
2. Re-run the PromQL expressions that fired, and the ML score, for the root-cause service and the services that depend on it.
3. **Resolved:** close the incident and record MTTR.
4. **Not resolved:** send the incident back to the LLM with `attempt += 1` and the previous actions included.
5. **After 3 attempts:** escalate to a human.

### 6.7 Fault Injector
- `injector/injector.py`: scheduled or random faults on **any service**, plus `docker stop redis` for dependency failures.
- **Locust** generates background load.
- Ground truth goes to `experiments/ground_truth.csv`: `fault, target_service, start, end`.

### 6.8 Dashboard
- React (a plain HTML/JS page is fine for the MVP), connected over WebSocket.
- Views:
  - service map with health colours
  - live incident feed
  - incident detail: alerts and ML anomalies → LLM reasoning → action → verification
  - approval queue
  - statistics: MTTD, MTTR, auto-resolve %, LLM vs runbook usage

---

## 7. Tech Stack

| Layer | Technology |
|-------|------------|
| Infrastructure | Docker, Docker Compose |
| Monitoring | Prometheus, Alertmanager, cAdvisor, redis_exporter, Grafana |
| ML | scikit-learn (Isolation Forest), NumPy/pandas, joblib |
| Event layer | FastAPI + WebSockets |
| LLM | Claude API **or** Ollama (Llama 3 / Mistral), Pydantic |
| Response | Docker SDK for Python, httpx, PyYAML |
| Storage | SQLite → PostgreSQL |
| Frontend | React + Tailwind (or HTML/JS MVP) |
| Testing / load | Locust, pytest |
| Notifications | Slack / Discord webhook (optional) |

---

## 8. Repository Structure

```
intellegent-devops/
├── app/                    # ✅ frontend service (existing)
├── api-service/            # new downstream service
├── injector/               # fault injection + ground truth
├── prometheus/
│   ├── prometheus.yml
│   └── rules.yml
├── alertmanager/
│   └── alertmanager.yml
├── ml/                     # anomaly detector: train.py, detector.py, models/
├── gateway/                # FastAPI: webhooks, context builder, WebSocket hub
├── analyzer/               # LLM engine: prompts, schema, runbook fallback
├── runbooks/               # YAML runbooks (fallback + baseline)
├── responder/              # validator, executor, verifier, policies.yaml
├── dashboard/
├── experiments/            # scenarios, ground truth, evaluation scripts
├── docs/                   # report, patent draft, diagrams
└── docker-compose.yml
```

---

## 9. Timeline (Oct 2026 → Apr 2027)

| Phase | Dates | Work | Deliverable |
|-------|-------|------|-------------|
| **1. Base setup** | ✅ Sep 2026 | Test app, Prometheus, Compose | Done |
| **2. Monitoring + multi-service** | Oct wk 1–3 | Fix app bugs, add `api-service` + Redis, cAdvisor, exporters, alert rules, Alertmanager, injector + Locust | Alerts fire for every fault on every service |
| **3. Event Gateway** | Oct wk 4 – Nov wk 1 | Webhooks, grouping, context builder across the services, WebSocket hub | Live `IncidentEvent` stream |
| **4. LLM Engine + Runbooks** | Nov wk 2 – Dec wk 1 | Prompts, schema, validation, YAML runbook fallback, Ollama + API | Correct root cause on test events |
| **5. Response System** | Dec wk 2 – Jan wk 1 | Validator, executor, approval flow | Safe auto-remediation |
| **6. Verification loop** | Jan wk 2–3 | Verifier, re-analysis, escalation, incident store | Full closed loop |
| **Mid-term review** | Late Jan | End-to-end demo (rules-based detection) | |
| **7. ML Detector** | Feb wk 1–2 | Collect normal data, train z-score + Isolation Forest, connect to the gateway | Detection by rules + ML |
| **8. Dashboard** | Feb wk 3 – Mar wk 1 | Service map, incident views, approvals, statistics | Web UI |
| **9. Evaluation** | Mar wk 2 – Apr wk 1 | All scenarios × baselines, tuning | Results chapter |
| **10. Final** | Apr | Report, demo video, paper, patent revision | Final submission |

### Work split
| Member | Ownership |
|--------|-----------|
| **Shayaan** | Event Gateway + WebSocket, Response System (validator, executor), integration, Compose |
| **Riddhima** | LLM Analysis Engine (prompts, schema, model comparison), YAML runbooks, dashboard |
| **Shruti** | Monitoring (rules, exporters, Alertmanager), `api-service`, injector, ML detector, verifier, evaluation |
| **All** | Report, patent revision, presentation |

---

## 10. Evaluation Plan

### Scenarios (each run at least 20 times under Locust load)

| # | Fault | Target | Symptom seen at | Expected root cause | Expected action |
|---|-------|--------|-----------------|---------------------|-----------------|
| 1 | CPU | frontend | frontend | frontend | reset / restart |
| 2 | CPU | api-service | api-service + frontend | api-service | reset / restart |
| 3 | Memory | api-service | api-service | api-service | restart |
| 4 | Latency | api-service | api-service + frontend | api-service | reset |
| 5 | Error | api-service | api-service + frontend | api-service | reset |
| 6 | Redis stopped | redis | api-service + frontend errors | redis | restart redis |
| 7 | Container stopped | frontend | frontend | frontend | restart |
| 8 | Gradual memory rise (no rule fires early) | api-service | — | api-service (ML) | restart before limit |
| 9 | Combined CPU + latency | api-service | multiple | api-service | single correct action |

**Scoring decisions (6 Oct 2026):**
- Scenario 3 (memory): only `restart_container` counts as correct. `experiments/score.py` encodes the accepted actions per row of this table; scenarios 1 and 2 accept reset or restart.
- The responder's 5-minute cooldown stays at 300 s (the policy under test). Suites run with `--gap 300`, so back-to-back scenarios needing the same action aren't blocked by the previous run's cooldown: `injector suite --scenarios 1-9 --repeat 3 --shuffle --gap 300`.

### Systems compared
| ID | System | Purpose |
|----|--------|---------|
| B0 | Alerts only, fixed by hand (a team member, timed) | Conventional practice |
| B1 | Rules + YAML runbooks, no LLM | Is the LLM worth adding? |
| B2 | Rules + LLM | Patent design, core version |
| **S** | **Rules + ML + LLM + runbook fallback (full system)** | **Proposed system** |
| — | S with Claude vs S with a local Ollama model | Model trade-off |

### Metrics
- **Detection**: recall, precision, and MTTD. Also report how many incidents were caught only by ML (scenario 8).
- **Root cause**: accuracy of `root_cause_service`, and accuracy of `incident_type`.
- **Response**: action correctness, unsafe actions blocked by the validator, unsafe actions executed (target: 0).
- **Resolution**: MTTR, auto-resolution rate, average attempts, escalation rate.
- **Cost**: LLM latency, and tokens and cost per incident.

---

## 11. Risks & Mitigation

| Risk | Mitigation |
|------|------------|
| The LLM hallucinates or suggests an unsafe action | Allowlist, schema validation, confidence threshold, human approval |
| LLM down, slow or too expensive | YAML runbook fallback; Ollama locally; grouping alerts reduces calls |
| ML false positives | Require a sustained anomaly (≥ 2 windows); tune the contamination setting; ML events start as low severity |
| Not enough normal data to train on | Run Locust for 1–2 hours of steady traffic; retrain with a script |
| Ground truth leaking into the inputs | Strip `fault_*` metrics from the LLM and ML inputs |
| Infinite remediation loop | Max 3 attempts + cooldown + escalation |
| Laptop resources | Compose only (no Kubernetes); small containers; Grafana optional |
| Scope creep | Freeze the scope after mid-term; stretch goals only once the evaluation is done |

---

## 12. MVP vs Stretch

**MVP (mid-term, late Jan)**
- 3-service app, alert rules, gateway + WebSocket
- LLM analysis with runbook fallback
- Validator + restart/reset executor
- Verifier loop and a minimal UI

**Full system (Mar)**
- ML detector, full dashboard, complete evaluation against all baselines

**Stretch goals (future work)**
- Log context via Loki
- Kubernetes executor
- Slack ChatOps approvals
- A memory of past incidents (retrieval-augmented, RAG)
- LSTM autoencoder
- Trace-based root-cause ranking (MicroRCA)

---

## 13. Report Outline
1. Introduction: problem, motivation, objectives
2. Literature Survey: monitoring, AIOps, ML anomaly detection, LLMs for operations, existing tools (k8sgpt, HolmesGPT, Datadog Bits AI)
3. Requirements and System Design: architecture, workflow, schemas, sequence diagrams
4. Implementation: one section per module
5. Safety and Policy Design
6. Evaluation and Results: B0/B1/B2 vs S
7. Conclusion and Future Work
8. References and Appendix (prompts, runbooks, policies, setup guide)

### Key references
- Liu et al., *Isolation Forest*, ICDM 2008
- Wu et al., *MicroRCA*, NOMS 2020 (related work for root-cause analysis)
- Lin et al., *DeepLog*, CCS 2017 (related work / future scope)
- Google SRE Book: *Monitoring Distributed Systems*
- Prometheus and Alertmanager documentation

---

## 14. Patent Revision Checklist
- [ ] Add a **Claims** section built on the four novel elements in §1
- [ ] Define the "Valid Response?" criteria in Fig. 2 (allowlist, confidence, cooldown)
- [ ] Add a maximum-attempts limit and an escalation step to the re-analyze loop in Fig. 2
- [ ] Add the ML detector and runbook fallback to Fig. 1
- [ ] Describe the safeguards against the LLM making things up
- [ ] Fix Riddhima's email (`ug.sharda.ac.in`), fill in the guide's email and address and the date, and fix the "alertanalysis" typo

---

## 15. Immediate Next Steps (this week)
- [x] Fix the `latency`/`error` duration bug and the histogram recording in `app/app.py`
- [x] Add `api-service` + Redis + redis_exporter + cAdvisor to `docker-compose.yml`
- [x] Write `prometheus/rules.yml` and `alertmanager/alertmanager.yml`
- [x] Implement `injector/injector.py` with ground-truth logging
- [x] Build a skeleton gateway: `/alerts` → print → broadcast over WebSocket (code done; Docker end-to-end test still pending)
