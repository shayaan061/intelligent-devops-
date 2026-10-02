# Plan Comparison
### `PROJECT_PLAN.md` (Plan A) vs `PATENT_ALIGNED_PLAN.md` (Plan B)

| | Plan A | Plan B |
|---|---|---|
| **File** | `PROJECT_PLAN.md` | `PATENT_ALIGNED_PLAN.md` |
| **Approach** | ML-centric AIOps | LLM-centric, follows the patent |
| **Pipeline** | Ingest → ML detect → Root-cause graph → Runbook → Execute | Prometheus → WebSocket → LLM → Response System → Verify |

---

## 1. Side-by-Side

| Aspect | **Plan A: ML-centric** | **Plan B: matches the patent (LLM-centric)** |
|---|---|---|
| **Main engine** | Trained ML models (Isolation Forest, LSTM autoencoder, Drain3 + DeepLog-style log model) | An LLM reads alerts plus metric context and returns structured JSON |
| **How problems are detected** | ML anomaly scores, no fixed rules | Prometheus alert rules; an ML detector is optional |
| **Root cause** | Ranking over the map of which services call which, built from traces (MicroRCA-style) | The LLM reasons over the metric context (evidence + confidence) |
| **Deciding the fix** | Fixed YAML runbooks that match a pattern | The LLM proposes the fix; a safety check approves or blocks it |
| **Event transport** | Pulling data from the APIs, or Kafka | Alertmanager webhook → WebSocket hub |
| **Infrastructure** | Kubernetes (kind/minikube/k3s), Helm, Chaos Mesh | Docker Compose (already in the repo); Kubernetes is a stretch goal |
| **Data collected** | Metrics, logs, traces (Prometheus, Loki, Jaeger, OpenTelemetry) | Metrics only (Prometheus + cAdvisor); logs are a stretch goal |
| **Demo app** | Online Boutique / DeathStarBench or a 4–5 service app | Your existing Flask app, ideally grown to 2–3 services |
| **Verification** | Re-check metrics, escalate if not fixed | Defined loop: re-check, re-analyze with the fixes already tried, give up after 3 attempts, escalate |
| **Role of the LLM** | Writes summaries only, never acts | The core decision-maker, held in check by the safety rules |
| **Builds on current code** | ❌ Starts from scratch | ✅ Builds on `app/`, Prometheus and Compose |
| **Matches the patent** | ❌ Different architecture | ✅ Follows Fig. 1, Fig. 2 and §1–9 |
| **Difficulty** | High: ML training, labelled data, K8s, three data pipelines | Medium: integration, prompt design, safety logic |
| **Laptop resources needed** | High (K8s + ELK/Loki + Jaeger + models) | Low to medium (Compose + optional local LLM) |
| **Biggest risk** | Not finishing in time; running out of resources | LLM giving wrong answers; weak novelty |
| **Academic depth** | Strong on ML (models, F1, comparisons with published papers) | Strong on system design; ML depth only if the optional detector is added |
| **Evaluation focus** | Detection F1, root-cause Top-3 accuracy, MTTD/MTTR | Diagnosis accuracy, rate of unsafe actions blocked, MTTR vs manual and rule-based baselines |
| **Timeline fit (by Apr 2027)** | Tight | Realistic |

---

## 2. Strengths & Weaknesses

### Plan A: ML-centric
**Strengths**
- Shows more ML depth (unsupervised models, log mining, graph-based root-cause analysis)
- Catches failures nobody wrote a rule for
- Covers logs and traces, not just metrics
- Easy to compare with published research papers

**Weaknesses**
- Does not match the patent draft
- Throws away the existing code
- Large build: three data pipelines, model training, Kubernetes
- Needs labelled data and plenty of compute

### Plan B: matches the patent
**Strengths**
- Follows the patent architecture exactly
- Builds on what is already in the repo
- Can be finished by the deadline with a working end-to-end demo
- The safety check plus verification loop is the strongest patent claim
- Easy to explain and demonstrate

**Weaknesses**
- Heavy reliance on the LLM (wrong answers, delay, cost)
- Novelty is thin unless the safety, context-building and re-analysis mechanisms are made specific
- Little ML depth unless the optional detector is added
- With a single service, finding the root cause is trivial

---

## 3. Recommendation: Plan B as the base, plus three ideas from Plan A

| Take from Plan A | Why |
|------------------|-----|
| **Optional ML anomaly detector** (Isolation Forest / z-score) | Catches problems the alert rules miss, backs up "machine learning" in the patent's field of invention, and adds technical depth |
| **2–3 services instead of one** (app → API → Redis/DB) | Makes cross-service correlation and root-cause analysis meaningful, which is where the patent's claims matter |
| **YAML runbooks** | Serve as the rule-based fallback when the LLM fails, and as the "no LLM" baseline for evaluation |

**Leave as future work:** Kubernetes, trace-based root-cause ranking, LSTM autoencoder, DeepLog, MLflow. These put the April 2027 deadline at risk and do not make the patent stronger.

### Resulting hybrid pipeline
```
Prometheus rules ──┐
                   ├──▶ Event Gateway ──WebSocket──▶ LLM Analysis ──▶ Safety/Policy ──▶ Executor
ML detector (opt) ─┘   (context builder)            (fallback: YAML     Validator          │
                                                      runbooks)                            ▼
                                     ◀──────────── re-analyze (max 3) ◀──── Verifier (Prometheus)
```

---

## 4. Decision Summary

| Criterion | Better plan |
|-----------|-------------|
| Matches the patent | **B** |
| Uses the existing code | **B** |
| Can be finished on time | **B** |
| ML / research depth | **A** |
| Covers metrics, logs and traces | **A** |
| Demo-ability | **B** |
| Safety and human-in-the-loop design | **B** (more detailed) |
| **Overall for this project** | **B + the three additions from A** |
