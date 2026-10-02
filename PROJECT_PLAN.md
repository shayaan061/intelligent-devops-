# Intelligent DevOps Monitoring & Response System
### Final Year Project — Project Plan

---

## 1. Overview

**Problem.** Modern applications run as many small services on containers and Kubernetes. When something breaks, engineers get a flood of alerts, dig through dashboards and logs by hand, and fix the problem with manual steps. This slows down detection (MTTD) and recovery (MTTR) and causes alert fatigue.

**Solution.** A system that:
1. **Monitors**: collects metrics, logs and traces from a running microservice application.
2. **Detects**: uses machine learning to find unusual behaviour instead of relying only on fixed thresholds.
3. **Diagnoses**: links related anomalies and points to the most likely root-cause service.
4. **Responds**: runs automated fixes (restart, scale, rollback) under safety rules, and notifies people with a short incident summary.
5. **Learns**: keeps incident history and operator feedback to improve detection over time.

**One-line pitch:** *"A self-monitoring, self-healing layer for Kubernetes microservices that detects, explains and fixes incidents with minimal human effort."*

---

## 2. Objectives

| # | Objective | Measurable target |
|---|-----------|-------------------|
| O1 | Collect metrics, logs and traces from a demo microservice app | ≥ 95% of services instrumented |
| O2 | Detect anomalies in metrics and logs with ML | F1-score ≥ 0.80 on injected faults |
| O3 | Find the root-cause service | Correct service in Top-3 for ≥ 75% of incidents |
| O4 | Fix common faults automatically | ≥ 60% of injected faults fixed with no human action |
| O5 | Cut detection and recovery time | ≥ 50% lower MTTD/MTTR than a threshold-only baseline |
| O6 | Give a single dashboard and ChatOps alerts | Live dashboard + Slack/Discord bot |

---

## 3. Scope

**In scope**
- A demo microservice app on a local Kubernetes cluster (kind/minikube/k3s)
- Metrics, logs and traces pipeline
- ML anomaly detection on metrics and logs
- Root-cause analysis based on correlation and the service dependency graph
- Rule-based automated remediation with safety checks
- Incident summaries written by an LLM
- Web dashboard and chat notifications
- Fault injection to test and evaluate the system

**Out of scope**
- Production-scale multi-cluster deployment
- Security intrusion detection (SIEM)
- Support for every cloud provider (one cloud or local only)

---

## 4. System Architecture

```
 ┌────────────────────────────────────────────────────────────────────┐
 │                  Demo Microservice App (Kubernetes)                 │
 │   frontend ── cart ── checkout ── payment ── db   (+ OpenTelemetry) │
 └───────┬──────────────────┬───────────────────────┬─────────────────┘
         │ metrics          │ logs                  │ traces
         ▼                  ▼                       ▼
   ┌───────────┐     ┌────────────┐          ┌────────────┐
   │Prometheus │     │ Loki / ELK │          │   Jaeger   │
   └─────┬─────┘     └─────┬──────┘          └─────┬──────┘
         └─────────────────┼───────────────────────┘
                           ▼
              ┌─────────────────────────┐
              │  Data Ingestion Service │  (Python, scheduled pulls / Kafka)
              └────────────┬────────────┘
                           ▼
              ┌─────────────────────────┐
              │   Anomaly Detection     │  metrics: Isolation Forest / LSTM-AE
              │        Engine           │  logs:    Drain parsing + ML
              └────────────┬────────────┘
                           ▼
              ┌─────────────────────────┐
              │ Correlation & Root-Cause│  service graph + time grouping
              │        Analysis         │  + ranking
              └────────────┬────────────┘
                           ▼
              ┌─────────────────────────┐
              │   Decision / Policy     │  confidence, blast radius,
              │        Engine           │  cooldowns, human approval
              └──────┬───────────┬──────┘
                     ▼           ▼
       ┌──────────────────┐  ┌───────────────────────┐
       │ Remediation      │  │ Notification + LLM    │
       │ Executor (K8s API│  │ summary (Slack/Discord│
       │ restart/scale/   │  │ email)                │
       │ rollback)        │  └───────────────────────┘
       └────────┬─────────┘
                ▼
       ┌──────────────────────────────────────────┐
       │ Incident Store (PostgreSQL) + Dashboard   │
       │ (React + Grafana embeds) + Feedback loop  │
       └──────────────────────────────────────────┘
```

---

## 5. Modules in Detail

### 5.1 Demo Application (target system)
- Use **Google Online Boutique** or **DeathStarBench**, or build a small 4–5 service app (FastAPI/Node + PostgreSQL + Redis).
- Add **OpenTelemetry** for traces and Prometheus client libraries for custom metrics.
- Use **Locust** or **k6** to generate realistic traffic with daily-style patterns.

### 5.2 Observability Stack
| Signal | Tool | Notes |
|--------|------|-------|
| Metrics | Prometheus + node-exporter + kube-state-metrics + cAdvisor | CPU, memory, latency (p50/p95/p99), error rate, restarts |
| Logs | Loki + Promtail (lighter) **or** ELK | Structured JSON logs |
| Traces | Jaeger / Grafana Tempo | Builds the service dependency graph |
| Visualisation | Grafana | Base dashboards |

### 5.3 Data Ingestion & Feature Engineering
- Python service pulls from the Prometheus HTTP API and the Loki API every 15–30 s.
- Features: rolling mean/std, rate of change, golden signals (latency, traffic, errors, saturation) for each service.
- Optional: **Kafka/Redis Streams** as a buffer for streaming.
- Store training windows in **TimescaleDB** or Parquet files.

### 5.4 Anomaly Detection Engine
| Data | Approach | Models |
|------|----------|--------|
| Single metric | Statistical baseline | Z-score, EWMA, seasonal decomposition (STL) |
| Multiple metrics | Unsupervised ML | **Isolation Forest**, **LSTM Autoencoder** (main), Prophet for forecasting |
| Logs | Template mining + sequences | **Drain3** log parsing → template counts → Isolation Forest / **DeepLog**-style LSTM |

- Combine the scores from all detectors into one anomaly score with a confidence value.
- Compare against a **baseline**: fixed thresholds as in Prometheus Alertmanager.
- Track and version models with **MLflow**.

### 5.5 Correlation & Root-Cause Analysis
1. **Group alerts by time**: anomalies within a short window (e.g. 2 min) become one incident.
2. **Use the dependency graph**: build the service call graph from traces.
3. **Rank candidates**: graph walk (Personalized PageRank / random walk, as in *MicroRCA*) weighted by anomaly scores. Errors flow upstream, so the root cause is usually the deepest anomalous service.
4. **Output**: a ranked list of suspect services and the metrics behind each one.

### 5.6 Decision / Policy Engine
- Map each incident type to a **runbook** (YAML), for example:

```yaml
- name: pod-crashloop
  match: { metric: kube_pod_container_status_restarts_total, trend: increasing }
  action: restart_deployment
  max_auto_attempts: 2
  cooldown: 10m
  requires_approval: false

- name: high-latency-after-deploy
  match: { anomaly: latency_p99, recent_deploy: true }
  action: rollback_deployment
  requires_approval: true
```
- **Safety rules**: a minimum confidence level, a limit on actions per window, cooldown timers, a dry-run mode, and human approval for risky actions via Slack buttons.

### 5.7 Remediation Executor
Uses the **Kubernetes Python client** to:
- Restart a pod or deployment
- Scale replicas up or down (or adjust the HPA)
- Roll back to the previous ReplicaSet (`kubectl rollout undo`)
- Clear a cache or run a custom script (Ansible playbook)
- Check the fix worked: re-read metrics after the action, and escalate if they have not recovered

### 5.8 LLM Incident Assistant (value-add)
- Feeds the incident context (anomalies, top suspects, log samples, action taken) to an LLM.
- Produces a plain-English **incident summary**, **likely cause** and **suggested next steps**.
- Optional: lets users ask questions in chat, e.g. "why is checkout slow?"
- Keeps the LLM **advisory only**: it never runs actions directly.

### 5.9 Dashboard & Notifications
- **Backend**: FastAPI (REST + WebSocket).
- **Frontend**: React + Tailwind + Recharts; Grafana panels embedded.
- Pages: live service health map, incident timeline, incident detail (RCA + actions + LLM summary), runbook manager, model metrics.
- **ChatOps**: Slack/Discord bot with Approve, Reject and Mark-as-false-positive buttons. False-positive marks go into the feedback loop.

### 5.10 Fault Injection (for testing and evaluation)
- **Chaos Mesh** or **LitmusChaos**: pod kill, network delay or loss, CPU/memory stress.
- Custom faults: memory leak endpoint, slow DB query, bad deploy (new image that returns errors).
- Each injection is logged with a timestamp, which gives **ground-truth labels** for evaluation.

---

## 6. Tech Stack

| Layer | Technology |
|-------|------------|
| Infrastructure | Docker, Kubernetes (kind / minikube / k3s), Helm |
| IaC / CI-CD | Terraform (optional), GitHub Actions, ArgoCD (optional) |
| Observability | Prometheus, Grafana, Loki, Jaeger, OpenTelemetry |
| ML | Python, scikit-learn, PyTorch/TensorFlow, Drain3, Prophet, MLflow |
| Backend | FastAPI, Celery/APScheduler, PostgreSQL, Redis |
| Frontend | React, Tailwind CSS, Recharts |
| Automation | Kubernetes Python client, Ansible |
| Chaos | Chaos Mesh / LitmusChaos, Locust / k6 |
| LLM | Any LLM API (e.g. Claude) or a local model through Ollama |
| Notifications | Slack / Discord webhooks + bot |

---

## 7. Timeline (≈ 32 weeks / 2 semesters)

| Phase | Weeks | Work | Deliverable |
|-------|-------|------|-------------|
| **0. Research** | 1–3 | Literature survey (AIOps, MicroRCA, DeepLog, LSTM-AE), requirements, tool choice | Synopsis + literature review |
| **1. Infra setup** | 4–6 | K8s cluster, demo app, CI/CD pipeline, load generator | Running demo app |
| **2. Observability** | 7–9 | Prometheus, Loki, Jaeger, Grafana, OTel instrumentation | Full telemetry dashboards |
| **3. Data & baseline** | 10–12 | Ingestion service, feature pipeline, fault injection scripts, labelled dataset, threshold baseline | Dataset + baseline results |
| **4. Anomaly detection** | 13–17 | Metric models (IF, LSTM-AE), log models (Drain3 + LSTM), combined scoring, MLflow | Detection engine + Mid-term review |
| **5. RCA** | 18–20 | Dependency graph from traces, correlation, ranking algorithm | RCA module |
| **6. Remediation** | 21–24 | Policy engine, runbooks, K8s executor, verification, safety rules | Self-healing demo |
| **7. Dashboard & ChatOps** | 25–27 | FastAPI backend, React UI, Slack bot, LLM summaries | Full UI |
| **8. Evaluation** | 28–30 | Chaos experiments, metrics, comparison with baseline, tuning | Results chapter |
| **9. Wrap-up** | 31–32 | Final report, research paper (optional), demo video, presentation | Final submission |

---

## 8. Evaluation Plan

**Experiments.** Run at least 10 fault types, repeated 10+ times each under varying load:

| Fault | Expected detection | Expected action |
|-------|--------------------|-----------------|
| Pod crash / CrashLoopBackOff | Restart spike, error rate up | Restart / alert |
| CPU stress | Saturation, latency up | Scale out |
| Memory leak | Memory trend up | Restart before OOM |
| Network delay | Latency up downstream | Alert + RCA |
| Bad deployment | Error rate up after deploy | Rollback |
| DB slow query | DB latency up, upstream latency up | RCA pinpoints DB |

**Metrics**
- Detection: Precision, Recall, F1, false-positive rate
- RCA: Top-1 and Top-3 accuracy
- Response: MTTD, MTTR, auto-remediation success rate
- System: resource overhead (CPU/RAM) and detection delay
- **Baseline comparison**: fixed thresholds vs the ML system

---

## 9. Suggested Team Roles (for a 3–4 member team)

| Member | Responsibility |
|--------|----------------|
| A | Infrastructure, Kubernetes, CI/CD, observability stack, chaos |
| B | ML: anomaly detection models, log analysis, MLflow |
| C | RCA, policy engine, remediation executor |
| D | Backend API, dashboard, ChatOps, LLM integration, documentation |

*(If you are working solo, follow the phases in order and treat the LLM assistant and log ML as stretch goals.)*

---

## 10. Risks & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Laptop can't run the full stack | High | Use k3s/kind with small resource limits; use Loki instead of ELK; free cloud credits (GCP/Azure student) |
| No labelled real-world data | High | Generate labelled data with chaos injection; also use public datasets (Loghub, NAB, SMD) |
| Too many false positives | Medium | Combine detectors, tune thresholds, collect feedback |
| Auto-fix causes more damage | High | Dry-run mode, approval gates, cooldowns, rate limits |
| Scope creep | Medium | Get the MVP working first; stretch goals come later |
| LLM cost or availability | Low | Local model via Ollama as a fallback |

---

## 11. MVP vs Stretch Goals

**MVP (must have by mid-term + 4 weeks)**
- Demo app, Prometheus and Grafana
- Isolation Forest metric anomaly detection
- Restart and scale remediation with safety checks
- Slack alerts and a basic dashboard

**Stretch goals**
- LSTM Autoencoder and log anomaly detection (DeepLog-style)
- Graph-based RCA from traces
- LLM incident summaries and chat Q&A
- Predictive alerts (forecast resource exhaustion)
- Feedback loop for retraining from operator labels
- GitOps rollback with ArgoCD

---

## 12. Repository Structure

```
intelligent-devops/
├── infra/                 # k8s manifests, helm charts, terraform
│   ├── demo-app/
│   ├── observability/
│   └── chaos/
├── services/
│   ├── ingestion/         # metric/log collectors
│   ├── detector/          # anomaly detection engine
│   ├── rca/               # correlation & root cause
│   ├── policy-engine/     # runbooks & decisions
│   ├── executor/          # k8s remediation
│   ├── notifier/          # slack/discord + LLM summaries
│   └── api/               # FastAPI backend
├── dashboard/             # React frontend
├── ml/
│   ├── notebooks/         # experiments
│   ├── models/
│   └── datasets/
├── runbooks/              # YAML runbook definitions
├── experiments/           # chaos scenarios + evaluation scripts
├── docs/                  # report, diagrams, paper
├── .github/workflows/     # CI/CD
└── docker-compose.yml     # local dev
```

---

## 13. Final Report Outline

1. Introduction (problem, motivation, objectives)
2. Literature Survey (AIOps, anomaly detection, RCA, self-healing systems)
3. System Requirements (functional and non-functional)
4. System Design (architecture, UML, DFD, sequence diagrams)
5. Implementation (module by module)
6. Testing & Evaluation (experiments, results, baseline comparison)
7. Results & Discussion
8. Conclusion & Future Work
9. References
10. Appendix (runbooks, screenshots, setup guide)

---

## 14. Key References

- Lin et al. *"DeepLog: Anomaly Detection and Diagnosis from System Logs"*, CCS 2017
- Wu et al. *"MicroRCA: Root Cause Localization of Performance Issues in Microservices"*, NOMS 2020
- He et al. *"Drain: An Online Log Parsing Approach"*, ICWS 2017
- Liu et al. *"Isolation Forest"*, ICDM 2008
- Google SRE Book: *Monitoring Distributed Systems* (the four golden signals)
- Loghub datasets: https://github.com/logpai/loghub
- Numenta Anomaly Benchmark (NAB): https://github.com/numenta/NAB

---

## 15. Next Steps (this week)

- [ ] Finalise team roles and get supervisor approval for the scope
- [ ] Set up the GitHub repo using the structure above
- [ ] Spin up a kind/minikube cluster and deploy Online Boutique
- [ ] Install kube-prometheus-stack with Helm
- [ ] Start the literature review document
