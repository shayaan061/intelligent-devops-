# Intelligent DevOps Monitoring & Incident Response System
### Final Year Project — Project Plan (aligned with the Invention Disclosure / patent draft)

**Team:** Muhammad Shayaan Ali · Riddhima Sharma · Shruti Tyagi
**Guide:** Ashish Kumar (Assistant Professor, CSE), Sharda University
**Plan date:** 1 Oct 2026

---

## 1. Core Idea (from the patent draft)

A continuous pipeline that turns raw monitoring data into a verified fix:

```
Monitor → Detect → Analyze → Decide → Respond → Verify  (→ loop)

Prometheus → WebSocket layer → LLM Analysis Engine → Response System → Verification
```

**Problem.** Conventional monitoring only raises alerts. Engineers still correlate the metrics, find the cause, choose a fix, apply it and check the result by hand. That leaves a gap between *detection* and *resolution*.

**Solution.** An intelligent layer between the monitoring stack and the response stack:
1. An LLM interprets the alerts together with their surrounding metric context.
2. It identifies the probable cause and generates a structured response.
3. A separate, policy-governed Response System runs or escalates that response.
4. Prometheus re-checks the system to confirm the incident is resolved.

---

## 2. Current Status (what already exists in the repo)

| Component | Status | Notes |
|-----------|--------|-------|
| `app/` Flask test app | ✅ Done | `/`, `/health`, `/metrics`, `/inject` (cpu, memory, latency, error), `/reset` |
| Prometheus metrics | ✅ Done | `http_requests_total`, `http_request_duration_seconds`, `fault_*_active` gauges |
| `prometheus/prometheus.yml` | ✅ Done | Scrapes `app:5000` every 5 s |
| `docker-compose.yml` | ✅ Done | app (1 CPU, 512 MB) + Prometheus |
| `injector/` | ⚠️ Empty | Files exist but contain no code |
| Alert rules / Alertmanager | ❌ Missing | Needed for the patent's "Alert Generation" step |
| WebSocket layer, LLM engine, Response System, Verifier, Dashboard | ❌ Not started | |

### Fixes needed in the existing code
1. **`latency` and `error` faults never clear themselves.** `duration` is read but ignored, so these stay on until `/reset` is called. Add a timer thread, as the CPU and memory faults already have.
2. **Errors and slow requests are not recorded properly.** The latency histogram is skipped on the error path. Use `with REQUEST_LATENCY.labels("/").time():` or a `finally` block.
3. **The `fault_*_active` gauges reveal the answer.** They are ground truth, so they **must never be sent to the LLM**. Use them only to score results.
4. **There are no container-level metrics.** Add **cAdvisor** (and node-exporter if needed) so CPU, memory and restart metrics come from the infrastructure, not from the app reporting on itself.
5. **The app has no restart policy.** Add `restart: unless-stopped` and a Docker `healthcheck` so the Response System has something real to act on.

---

## 3. System Architecture

```
 ┌──────────────────────────────────────────────────────────┐
 │  DevOps Infrastructure (Docker Compose)                   │
 │  test-app (Flask)  ·  cAdvisor  ·  node-exporter          │
 └──────────────┬───────────────────────────────────────────┘
                │ metrics (scrape 5s)
                ▼
 ┌──────────────────────────┐   rules.yml    ┌──────────────┐
 │       Prometheus          │──────────────▶│ Alertmanager │
 └──────────────┬───────────┘                └──────┬───────┘
                │ PromQL (context queries)          │ webhook
                ▼                                   ▼
 ┌──────────────────────────────────────────────────────────┐
 │  Event Gateway (FastAPI)                                  │
 │  • receives alerts  • groups/dedups  • builds context      │
 │  • WebSocket hub  /ws/events  /ws/responses                │
 └──────────────┬───────────────────────────────────────────┘
                │ WebSocket: IncidentEvent (JSON)
                ▼
 ┌──────────────────────────────────────────────────────────┐
 │  LLM Analysis Engine                                      │
 │  incident detection · context analysis · root cause ·      │
 │  response generation → structured JSON (schema-validated)  │
 └──────────────┬───────────────────────────────────────────┘
                │ WebSocket: ResponsePlan (JSON)
                ▼
 ┌──────────────────────────────────────────────────────────┐
 │  Response System                                          │
 │  Safety/Policy Validator → Executor (Docker SDK / API)     │
 │              └────────→ Human approval (dashboard/Slack)   │
 └──────────────┬───────────────────────────────────────────┘
                │ action applied
                ▼
 ┌──────────────────────────────────────────────────────────┐
 │  Verifier: re-query Prometheus after T seconds             │
 │  resolved → close incident │ not resolved → re-analyze     │
 │  (max N loops, then escalate)                              │
 └──────────────┬───────────────────────────────────────────┘
                ▼
     Incident Store (SQLite/PostgreSQL) + Live Dashboard (React)
```

---

## 4. Module Design

### 4.1 Monitoring & Alert Generation (Patent §1–2)
- Prometheus collects data from the app, cAdvisor and node-exporter.
- `prometheus/rules.yml` defines the alerts:

| Alert | Example expression | For |
|-------|--------------------|-----|
| HighCPU | `rate(container_cpu_usage_seconds_total{name="devops-test-app"}[1m]) > 0.8` | 30s |
| HighMemory | `container_memory_usage_bytes{name=...} / container_spec_memory_limit_bytes > 0.8` | 30s |
| HighLatency | `histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[1m])) > 1` | 30s |
| HighErrorRate | `sum(rate(http_requests_total{status=~"5.."}[1m])) / sum(rate(http_requests_total[1m])) > 0.1` | 30s |
| ServiceDown | `up{job="test-app"} == 0` | 15s |

- Alertmanager sends each alert to the Event Gateway through a webhook (`POST /alerts`).
- **Optional ML step** (fits the "machine learning" field in the patent): a lightweight Isolation Forest / z-score detector that catches anomalies with no rule. Its output becomes the same kind of `IncidentEvent`.

### 4.2 Real-Time Event Transmission (Patent §3)
- The **Event Gateway** is a FastAPI service with a WebSocket hub.
- On each alert it:
  1. Removes duplicate alerts and groups those within a 60 s window into one incident.
  2. Builds the **context**: runs PromQL queries for the related metrics over the last 10 minutes, plus recent actions and container state.
  3. Publishes an `IncidentEvent` on `/ws/events`.

```json
{
  "incident_id": "inc-0042",
  "timestamp": "2026-11-10T12:30:05Z",
  "service": "devops-test-app",
  "alerts": [{"name": "HighLatency", "value": 5.02, "threshold": 1, "status": "firing"}],
  "context": {
    "cpu_1m": 0.12, "mem_ratio": 0.31, "p95_latency_s": 5.02,
    "error_rate": 0.0, "rps": 4.1, "restarts_10m": 0,
    "series": {"p95_latency_s": [0.01, 0.01, 4.9, 5.0, 5.02]}
  },
  "history": {"previous_actions": [], "attempt": 1}
}
```

### 4.3 LLM Analysis Engine (Patent §4–6)
- Subscribes to `/ws/events` and publishes on `/ws/responses`.
- The prompt contains: the system role, the list of allowed actions, the incident event, and a few examples (few-shot).
- **Structured output** is required and validated with Pydantic:

```json
{
  "incident_id": "inc-0042",
  "incident_type": "latency_degradation",
  "severity": "high",
  "probable_cause": "Request handler is blocking (~5s delay) while CPU and memory are normal, indicating an application-level delay rather than resource exhaustion.",
  "evidence": ["p95 latency 5.02s vs 0.01s baseline", "CPU 12%", "no errors"],
  "confidence": 0.82,
  "recommended_action": {"type": "reset_faults", "target": "devops-test-app", "params": {}},
  "fallback_action": {"type": "restart_container", "target": "devops-test-app"},
  "explanation": "..."
}
```

- **LLM options:** the Claude API, or a local model through **Ollama** (works offline and costs nothing for demos).
- **Fallback:** if the LLM times out or returns invalid JSON, use a rule-based mapping, e.g. HighCPU → restart.

### 4.4 Decision & Response System (Patent §5–7)
This keeps **decision generation separate from action execution**, which is a key point in the patent.

**Safety/Policy Validator** (`policies.yaml`). An action runs only if all of these pass:
- The action type is on the **allowlist**. The LLM can never run arbitrary shell commands.
- The target is a known service.
- `confidence ≥ 0.7`; otherwise it goes to a human.
- Cooldown: no repeat of the same action on the same target within 5 minutes.
- Limit: at most 3 automatic actions per incident.
- Each action is tagged `auto` or `requires_approval`.

**Action catalogue (Executor using the Docker SDK / HTTP)**

| Action | Implementation | Mode |
|--------|----------------|------|
| `reset_faults` | `POST /reset` on the app | auto |
| `restart_container` | `docker.containers.get(..).restart()` | auto |
| `scale_out` | `docker compose up --scale app=N` (needs a load balancer) | approval |
| `update_resources` | `container.update(cpu_quota=..., mem_limit=...)` | approval |
| `escalate` | Dashboard and Slack/Discord alert with the LLM summary | always allowed |

**Human-in-the-loop:** the dashboard shows the proposed action with **Approve** and **Reject** buttons, matching the patent's "Valid Response? → No → Escalate" branch.

### 4.5 Verification & Re-analysis Loop (Patent §8–9, Fig. 2)
1. After an action, wait for a stabilisation window (e.g. 30–60 s).
2. Re-query the same PromQL expressions and compare them with the threshold and the pre-incident baseline.
3. **Resolved:** mark the incident `resolved` and record the MTTR.
4. **Not resolved:** send an updated `IncidentEvent` (`attempt += 1`, with the previous action included) back to the LLM.
5. **After N = 3 attempts:** escalate to a human. This stops the infinite loop that Fig. 2 currently allows.

### 4.6 Fault Injector (`injector/`)
- A script that injects faults on a schedule or at random through `/inject`, with load generated by **Locust**.
- Writes the **ground truth** (fault type, start and end time) to `experiments/ground_truth.csv`, which is used for scoring.

### 4.7 Dashboard
- React (or a simple HTML/JS page at first) connected to the gateway over WebSocket.
- Views:
  - live metrics (Grafana embed)
  - incident feed
  - incident detail: alerts → LLM analysis → action → verification result
  - approval queue
  - statistics: MTTD, MTTR, auto-resolve %

---

## 5. Tech Stack

| Layer | Technology |
|-------|------------|
| Infrastructure | Docker, Docker Compose (Kubernetes optional, later) |
| Monitoring | Prometheus, Alertmanager, cAdvisor, node-exporter, Grafana |
| Event layer | FastAPI + WebSockets (`websockets`/Starlette) |
| LLM | Claude API **or** Ollama (Llama 3 / Mistral), Pydantic for schema validation |
| Response | Docker SDK for Python, httpx |
| Storage | SQLite (dev) → PostgreSQL |
| Frontend | React + Tailwind (or plain HTML/JS for the MVP) |
| Testing / load | Locust, pytest |
| Notifications | Slack / Discord webhook (optional) |

---

## 6. Repository Structure (target)

```
intellegent-devops/
├── app/                    # ✅ test application
├── injector/               # fault injection + ground-truth logger
├── prometheus/
│   ├── prometheus.yml
│   └── rules.yml           # alert rules
├── alertmanager/
│   └── alertmanager.yml    # webhook → gateway
├── gateway/                # FastAPI: /alerts webhook, context builder, WebSocket hub
├── analyzer/               # LLM engine: prompts, schema, fallback rules
├── responder/              # policy validator, executor, verifier
│   └── policies.yaml
├── dashboard/              # web UI
├── experiments/            # scenarios, results, evaluation scripts
├── docs/                   # report, patent draft, diagrams
└── docker-compose.yml
```

---

## 7. Timeline (Oct 2026 → Apr 2027)

| Phase | Dates | Work | Deliverable |
|-------|-------|------|-------------|
| **1. Base setup** | ✅ Sep 2026 | Test app, Prometheus, Compose | Done |
| **2. Monitoring hardening** | Oct wk 1–2 | Fix app bugs, cAdvisor, alert rules, Alertmanager, injector + Locust | Alerts fire for all 4 fault types |
| **3. Event Gateway** | Oct wk 3 – Nov wk 1 | FastAPI webhook, grouping, PromQL context builder, WebSocket hub | `IncidentEvent` streamed live |
| **4. LLM Analysis Engine** | Nov wk 2 – Dec wk 1 | Prompt design, structured output, validation, fallback, Ollama + API | Correct analysis for injected faults |
| **5. Response System** | Dec wk 2 – Jan wk 2 | Policy validator, action catalogue, executor, approval flow | Auto-fix + human approval working |
| **6. Verification loop** | Jan wk 3–4 | Verifier, re-analysis, max-attempt escalation, incident store | Full closed loop (Fig. 2) |
| **Mid-term review** | Late Jan | End-to-end demo | |
| **7. Dashboard** | Feb | Live feed, incident detail, approvals, stats | Web UI |
| **8. Evaluation** | Mar | Experiments vs baseline, tuning, optional ML detector | Results chapter |
| **9. Final** | Apr | Report, demo video, paper/patent filing support | Final submission |

### Suggested work split
| Member | Ownership |
|--------|-----------|
| Shayaan | Gateway + WebSocket layer, Response System / executor, integration |
| Riddhima | LLM Analysis Engine: prompts, schema, fallback, model comparison |
| Shruti | Monitoring (rules, cAdvisor, Alertmanager), injector, verifier, evaluation |
| All | Dashboard, report, presentation |

---

## 8. Evaluation Plan

**Scenarios** (each repeated at least 20 times under Locust load):

| Injected fault | Expected alert | Expected cause | Expected action |
|----------------|----------------|----------------|-----------------|
| CPU | HighCPU (+ latency) | CPU exhaustion | reset / restart |
| Memory | HighMemory | Memory pressure / leak | restart |
| Latency | HighLatency | App-level blocking | reset |
| Error | HighErrorRate | Application failure | reset / restart |
| Container stop | ServiceDown | Service unavailable | restart |
| Combined (CPU + latency) | Multiple | CPU causing latency | single correct action |

**Metrics**
- **Diagnosis accuracy:** the LLM's `incident_type` matches the ground truth.
- **Action correctness:** the recommended action is suitable for the fault.
- **Invalid or unsafe action rate:** proposals rejected by the validator, i.e. hallucinations.
- **MTTD:** time from fault start to alert.
- **MTTA:** time from alert to analysis (LLM latency).
- **MTTR:** time from fault start to verified resolution.
- **Auto-resolution rate** and **escalation rate**.
- **Cost / tokens per incident** (API) vs local model.

**Baselines**
1. Alerts only, with a human fixing the fault by hand: time a team member doing it.
2. A static rule-based mapping from alert to action, with no LLM.
3. Optional: comparing LLMs (Claude vs a local Llama/Mistral).

This comparison is what will **prove** the patent's claim of "faster and more consistent response".

---

## 9. Risks & Mitigation

| Risk | Mitigation |
|------|------------|
| The LLM hallucinates or suggests a dangerous action | Action allowlist, schema validation, confidence threshold, human approval |
| LLM latency or cost | Ollama locally, alert grouping, caching repeated incident types |
| LLM unavailable | Rule-based fallback path |
| Fault labels leaking into the context | Never send `fault_*_active` metrics to the LLM |
| Infinite re-analysis loop | Max attempts plus escalation |
| Only a single service, so root cause is trivial | Add 2–3 services (e.g. app → API → Redis/DB) so multi-component correlation is meaningful |
| Scope creep (Kubernetes, ML) | Keep these as stretch goals after the closed loop works on Compose |

---

## 10. MVP vs Stretch

**MVP (by mid-term):** alert rules → gateway → WebSocket → LLM JSON analysis → validator → restart/reset → verifier, with a minimal UI.

**Stretch goals:**
- A multi-service demo app for real root-cause analysis
- An ML anomaly detector
- Log context through Loki
- Kubernetes executor (pod restart, scale, rollout undo)
- Slack ChatOps approvals
- A memory of past incidents (retrieval-augmented, RAG) so the LLM learns from previous fixes

---

## 11. Report Outline
1. Introduction: problem, motivation, objectives
2. Literature Survey: monitoring, AIOps, LLMs for operations, existing tools
3. Requirements and System Design: architecture (Fig. 1), workflow (Fig. 2), schemas, sequence diagrams
4. Implementation: one section per module
5. Safety and Policy Design
6. Evaluation and Results: comparison with the baselines
7. Conclusion and Future Work
8. References and Appendix (prompts, policies, setup guide)

---

## 12. Immediate Next Steps
- [ ] Fix the latency/error fault duration bug and the histogram recording in `app/app.py`
- [ ] Add cAdvisor, `rules.yml` and Alertmanager to `docker-compose.yml`
- [ ] Write `injector/injector.py` with ground-truth logging
- [ ] Build a skeleton gateway: `/alerts` webhook → print → broadcast over WebSocket
- [ ] Draft the LLM prompt and the JSON schema; test them by hand on 4 sample events
