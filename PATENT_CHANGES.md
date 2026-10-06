# Changes to `patent .pdf` (Invention Disclosure Form) per `SUGGESTED_PLAN.md`

Ordered by page. Each item gives **what is there now**, **what to change**, and (where useful) **text you can paste in**.

---

## A. Page 1: Particulars of Inventors (corrections)

| # | Current | Change to |
|---|---------|-----------|
| A1 | Riddhima's email `2023567320.riddhima@ug.shardac.in` | `2023567320.riddhima@ug.sharda.ac.in` (missing dot) |
| A2 | Ashish Kumar: Email blank | Fill in the guide's official email |
| A3 | Ashish Kumar: Official Address blank | e.g. "Dept. of CSE, Sharda University, Greater Noida" |
| A4 | Address column reads "Student,Greater Noida,Sharda University" | Add spaces: "Student, Greater Noida, Sharda University" (cosmetic) |

---

## B. Page 2: Abstract

**B1. Add the dual detection (rules + ML).** After "...using Prometheus", add:

> Abnormal behaviour is detected by two complementary detectors: configured rule-based alert conditions for known failure patterns, and a machine-learning anomaly detector (for example, Isolation Forest combined with rolling statistical scoring) for deviations that no predefined rule covers. Both detectors emit events in a single, common incident format.

**B2. Add the context builder.** After "...to an intelligent analysis component", add:

> Before analysis, a context builder automatically collects the related metrics of every service in the dependency chain of the affected service over a time window around the event, so that the analysis can separate the root-cause service from services that only show symptoms.

**B3. Add the safety layer and the bounded loop.** Replace the sentence "The generated response is subsequently passed to a response/incident handling system, which can execute or initiate predefined remediation actions..." with:

> The LLM produces a structured, schema-validated response plan and never executes actions directly. A policy validator placed between the LLM and the executor checks every proposed action against an action allowlist, a known-target list, a confidence threshold, cooldown rules and approval requirements before it runs. After execution, a verifier re-evaluates the triggering conditions; if the incident is unresolved, it is re-analyzed together with the record of actions already attempted, up to a configured maximum number of attempts, after which it is escalated to a human operator. When the LLM is unavailable, times out, returns invalid output or reports low confidence, deterministic runbooks provide a fallback response.

**B4. Typo.** The plan flags "alertanalysis". In the PDF this is "alert-" + line break + "analysis", which reads correctly. Check the source Word file: if it is typed as one word, change it to "alert-analysis".

---

## C. Page 2: Field of Invention

Machine learning is already named here, but nothing in the description uses it. Replace the "More particularly..." paragraph with:

> More particularly, the invention relates to an intelligent monitoring and incident-response mechanism that combines Prometheus-based metric collection, **rule-based and machine-learning-based anomaly detection**, **dependency-aware context building across multiple services**, real-time event communication, Large Language Model-based root-cause analysis, **a policy-based safety validation layer between the analysis engine and the action executor**, and **a verification and bounded re-analysis loop** for detecting and handling operational issues in software and computing infrastructure.

---

## D. Pages 2–4: Prior Art

**D1. Add a subsection "6) Existing AI-assisted operations tools"** (the plan's literature survey lists these). Describe each and say how this invention differs:

> Recent tools such as k8sgpt, HolmesGPT and Datadog Bits AI apply LLMs to diagnose infrastructure problems. These tools mainly explain or summarize issues, and either leave remediation to the engineer or carry out actions without a separate, deterministic safety layer. They also do not combine rule-based and ML-based detection into a common incident format with runbook fallback, or bound re-analysis using the history of attempted actions. Statistical anomaly detection methods (e.g., Isolation Forest, Liu et al., ICDM 2008) and graph-based root-cause methods (e.g., MicroRCA, Wu et al., NOMS 2020) detect or localize faults, but do not generate and safely execute a verified remediation.

**D2. Add three limitations** to the list in "4) Limitations of Existing Systems":
- Threshold rules cannot detect gradual or multi-metric deviations (for example, a slow memory rise) before a hard limit is reached.
- In multi-service systems, the alerting service is often only a downstream symptom, not the root cause.
- Applying LLM output directly to infrastructure is unsafe without validation, because LLMs can produce incorrect or hallucinated actions.

**D3. Extend "5) Gap and Motivation"** with one sentence: there is a need to use LLM reasoning for incident response **while guaranteeing that no unvalidated action reaches the infrastructure, and that remediation attempts are bounded and verified**.

---

## E. New section: Summary of Invention / Technical Advancement (insert before "Disclose working of invention", page 5)

The IDF header asks you to "distinctly highlight... the technical advancement". Right now there is no section that does this. Add:

> **Summary of the Invention and Technical Advancement**
>
> The invention provides the following technical advancements over existing systems:
>
> 1. **Dependency-aware context builder.** When an event is received, the system automatically collects the metrics, container states, restart counts and recent actions of all services in the dependency chain of the affected service over a time window around the event, together with the service topology. This lets the analysis engine tell the root-cause service apart from services that only show the symptom.
> 2. **Policy-based safety validator between the LLM and the executor.** The LLM outputs a structured response plan that is validated against a schema. An action is executed only if it is on an action allowlist, its target is a known service, its confidence is at or above a configured threshold, it does not violate a cooldown period, and the per-incident action limit has not been reached. Otherwise it is routed for human approval. The LLM never executes commands directly.
> 3. **History-aware, bounded re-analysis loop.** If verification shows the incident is unresolved, the incident is re-analyzed with the attempt number and the list of previously attempted actions and their outcomes, so a failed action is not repeated. After a maximum number of attempts (e.g., 3), the incident is escalated to a human.
> 4. **Dual detection with a unified incident format and deterministic fallback.** Rule-based alerts and ML-detected anomalies are converted into one common incident event. Deterministic runbooks provide a fallback response, which keeps the system working when the LLM fails, and also serve as a non-LLM baseline for comparison.

---

## F. Page 5: Fig. 1, System Architecture (redraw)

Current: Infrastructure → Prometheus → WebSocket → LLM Engine → Response System → Infrastructure.

Changes:
1. **Add an "Alert Rules / Alertmanager" block** after Prometheus (rule-based path).
2. **Add an "ML Anomaly Detector" block** in parallel, reading metrics from Prometheus (Isolation Forest + z-score).
3. Both feed an **"Event Gateway: dedup / grouping / context builder"** block, which then feeds the WebSocket layer.
4. Inside or beside the LLM Engine, add **"Fallback: Deterministic Runbooks"**.
5. Split "Response System" into **"Policy / Safety Validator" → "Action Executor"**, with a side branch **"Human Approval"**.
6. Add a **"Verifier"** block after remediation. Its "not resolved" arrow goes back to the **LLM Analysis Engine** (carrying the attempt history), and an "attempts exhausted" arrow goes to **Escalation**.
7. Optional: an **"Incident Store + Dashboard"** block.
8. The feedback arrow currently labelled "Prometheus" should be labelled "Continuous monitoring / verification metrics".

You can base the new figure on the architecture diagram in §5 of `SUGGESTED_PLAN.md`.

---

## G. Pages 5–8: Working of the Invention, steps 1–9

| Step | Change |
|------|--------|
| **1) Monitoring Data Collection** | Add: container-level metrics (via a container metrics exporter such as cAdvisor), dependency metrics (e.g., cache/database exporters), and **upstream call latency** between services. |
| **2) Monitoring and Alert Generation** | Rename to **"Detection (Rule-based and ML-based)"**. Keep the rule text and add a paragraph on the ML detector: it polls per-service features (CPU, memory ratio, p95 latency, error rate, request rate, upstream latency) at fixed intervals, scores them with a model trained on normal behaviour, and raises an event only when the anomaly persists for at least 2 consecutive windows. Add to the event fields: **event source (rule/ML), anomaly score, top contributing features, incident ID**. |
| **New 2a) Event Correlation and Context Building** | Insert as a new step. Events within a time window that share a dependency chain are grouped into one incident. The context builder attaches the topology, the last N minutes of key metrics for every service in the chain, container state and restarts, recent actions, and the attempt history. Add the sentence: *"Ground-truth or fault-labelling signals, where present, are excluded from the analysis context."* |
| **3) Real-Time Event Transmission** | Minor: say there are separate channels for incident events and for response plans (e.g., `/ws/events`, `/ws/responses`). |
| **4) Intelligent Incident Analysis** | Add: the prompt includes the topology and the **list of allowed actions**. The output is **structured** (root-cause service, incident type, severity, probable cause, evidence, confidence score, recommended action, fallback action, explanation) and is validated against a schema. Add the **runbook fallback** paragraph: it is used on timeout, invalid output or confidence below the threshold. |
| **5) Incident Classification / Decision** | Define the decision criteria explicitly (this is what Fig. 2's "Valid Response?" means). A response is valid only if: (a) it passes schema validation, (b) the action type is on the allowlist, (c) the target is a known service, (d) confidence ≥ threshold (e.g., 0.7), (e) the same action on the same target has not been taken within the cooldown period (e.g., 5 min), (f) the per-incident action limit has not been reached, and (g) the action is not classed as risky. If it is risky, it needs human approval. |
| **6) Response Generation** | **Remove or reword "Commands or operational actions."** Free-form commands contradict the safety design. Replace with: *"Selection of a predefined operational action from an allowlist (e.g., reset faults, restart container, flush cache, update resource limits, escalate)."* State that arbitrary shell commands are never executed. |
| **7) Response System** | Describe the two sub-components, **Policy Validator** and **Executor**. Give the action table with modes: reset/restart = automatic; cache flush and resource update = approval required; escalate = always allowed. |
| **8) Incident Resolution** | Rename to **"Verification and Re-analysis"**. After a settling period (30–60 s), re-evaluate the conditions that fired and the ML score for the root-cause service and the services that depend on it. **Resolved:** close the incident and record MTTR. **Not resolved:** re-analyze with `attempt + 1` and the previous actions. **After the maximum number of attempts:** escalate. |
| **9) Continuous Monitoring** | No change needed. Update the pipeline line to: Prometheus → Rules + ML Detector → Gateway/Context Builder → WebSocket → LLM Analysis (with runbook fallback) → Policy Validator → Executor → Verifier. |

**Safeguards against hallucination (checklist item).** Add a short paragraph, either in step 4 or as a new step:

> Safeguards against incorrect or fabricated LLM output include: a constrained action vocabulary supplied in the prompt; strict schema validation of the output; rejection of unknown services or actions; a confidence threshold; required evidence fields that cite metrics from the supplied context; deterministic runbook fallback; and human approval for risky actions.

---

## H. Page 8: Fig. 2, Project Workflow (redraw)

1. "Alert / Anomaly Detected" → split into **"Rule Alert"** and **"ML Anomaly"**, merging into **"Build Incident Context"** before "Event Sent via WebSocket".
2. After "Generate Response", add a decision **"LLM output valid / confident?"**. On **No**, go to **"Apply Runbook Fallback"**.
3. Label the "Valid Response?" diamond **"Passes Policy Validator?"**, with the criteria from step 5. Add a third branch: **"Risky → Human Approval"**, where approve → execute and reject → escalate.
4. **Fix the loop:** the "Re-analyze" box currently returns to "Monitor System Again", so the LLM is never called again. It should return to **"LLM Receives Context"**, carrying the attempt history.
5. Before "Re-analyze", add a decision **"Attempts < Max (3)?"**. On **No**, go to **"Escalate to Human"** → END.
6. On "Incident Resolved? → Yes", add **"Record MTTR / Store Incident"** before END, or "return to normal monitoring".

---

## I. Page 9: "How it works" paragraph

Rewrite to match the new Fig. 2, adding: both detectors, the context builder, the validator criteria, the runbook fallback, re-analysis with the history of attempted actions, and the attempt limit followed by escalation. Remove the open-ended wording "another response can be generated" and use the bounded loop instead.

---

## J. Pages 9–10: Applications and Advantages

**Applications.** Add: *"Microservice environments in which faults propagate across dependent services and the alerting service differs from the root-cause service."*

**Advantages.** Add these bullets:
- Detects both known failures (rules) and unknown or gradual anomalies (ML) before hard thresholds are crossed.
- Identifies the root-cause service, not just the service showing the symptom, by using dependency-aware context.
- No unvalidated LLM output reaches the infrastructure: there is an allowlist, schema, confidence threshold, cooldown and approval.
- Bounded remediation with no infinite loops: a maximum number of attempts, then escalation.
- Keeps working when the LLM is unavailable, through deterministic runbook fallback.
- Each incident's evidence, reasoning, action and verification result is recorded, giving an auditable trail.

Optional: once evaluation is done, add measured results (MTTR reduction vs manual handling, auto-resolution rate, 0 unsafe actions executed). Do not add numbers before they are measured.

---

## K. New section: Claims (insert before the Disclaimer, page 11)

> **Claims**
>
> 1. A system for intelligent monitoring and incident response, comprising: a metrics collection module; a rule-based detector and a machine-learning anomaly detector, each configured to emit events in a common incident format; an event gateway comprising a context builder configured to, on receipt of an event concerning a first service, retrieve metrics of the first service and of every service in its dependency chain over a time window associated with the event; a real-time communication layer; an LLM-based analysis engine configured to output a structured response plan comprising a root-cause service, a confidence score and a recommended action; a policy validator, interposed between the analysis engine and an action executor, configured to permit execution only of actions satisfying an allowlist, a known-target constraint, a confidence threshold and a cooldown constraint; and a verifier configured to re-evaluate the triggering conditions after execution.
> 2. The system of claim 1, wherein, when the verifier determines the incident is unresolved, the incident is resubmitted to the analysis engine together with an attempt count and a record of previously attempted actions, and the incident is escalated to a human operator when the attempt count reaches a configured maximum.
> 3. The system of claim 1, further comprising deterministic runbooks applied when the analysis engine times out, returns output that fails schema validation, or returns a confidence below the threshold.
> 4. The system of claim 1, wherein actions classed as risky are routed to a human approval interface instead of being executed automatically.
> 5. The system of claim 1, wherein the machine-learning anomaly detector emits an event only after an anomaly persists for a configured number of consecutive evaluation windows, and the event includes an anomaly score and top contributing features.
> 6. The system of claim 1, wherein fault-labelling or ground-truth signals are excluded from the context supplied to the analysis engine and the anomaly detector.
> 7. A method corresponding to claims 1–6, comprising the steps of monitoring, dual detection, context building, LLM analysis, policy validation, execution, verification and bounded re-analysis.

(The patent attorney or RDC will reformat these. The goal here is to get the four novel elements into writing.)

---

## L. Page 11: Signature block

- Fill in the **Date**.
- The block only has Muhammad Shayaan Ali. Add signature, name and date lines for **Riddhima Sharma, Shruti Tyagi and Ashish Kumar**, since all four are listed as inventors. Confirm with the RDC whether that is required.

---

## M. Additions from the implementation (6 Oct 2026): extra dependent claims and evidence

Building and testing the system produced mechanisms that the draft doesn't describe. Each one fixed a real failure seen in testing, so each is concrete and defensible. Add them to section G (working of the invention) and as dependent claims after claim 6 in section K:

> 8. The system of claim 1, wherein, immediately before executing a validated action, the triggering conditions are re-evaluated and the action is withheld if they are no longer active, so that an action is not applied to a service that has already recovered. *(Alerts trail the fault by the rule's evaluation window; in testing, an alert that fired after the fault had cleared led to an unnecessary container restart before this check was added.)*
> 9. The system of claim 2, wherein at most one action per incident is in progress (executing, being verified or awaiting approval), and a response plan whose attempt number is lower than the incident's current attempt is discarded, so that a plan produced from an outdated view of the incident cannot trigger an action.
> 10. The system of claim 1, wherein the response plan comprises a recommended action and a fallback action; when the recommended action is rejected by the allowlist, target or cooldown constraint, the fallback action is validated in its place, and when neither passes the incident is escalated.
> 11. The system of claim 1, wherein the policy validator operates independently of the analysis engine's output validation, treating every response plan as untrusted: non-finite or non-numeric confidence values, malformed action fields and malformed attempt identifiers are rejected, and the action executor independently re-checks the allowlist before executing.
> 12. The system of claim 1, wherein the event gateway, on receiving a first event, waits for a configured settle interval before forwarding the incident for analysis, so that events from the root-cause service and from dependent services showing symptoms are analyzed together as one incident.
> 13. The system of claim 1, wherein every event, response plan and action outcome is recorded in an incident store, from which detection time, root-cause accuracy, action correctness and time to resolution are computed against injected-fault ground truth.

**Supporting evidence (preliminary; add to the report, and to the IDF only if the RDC wants data):**
- Closed loop on real containers, runbook mode (scenarios 4, 5, 6, 7): faults detected in about 32–40 s and remediated 38–48 s after injection, against 180 s planned fault durations.
- Re-analysis demonstrated live: after a failed fix, the incident was re-analyzed with the attempted action in its history, a different action was proposed, the cooldown blocked it, and the incident was escalated.
- Adversarial safety suite (`experiments/safety_suite.py`): 29 hallucinated, malformed and malicious plans, 0 unsafe actions executed. 7 of these were caught only by the policy validator (the LLM output schema accepted them), which is the evidence for claim 11.
- These are single runs. Use the §10 evaluation (each scenario at least 20 times, `experiments/score.py`) for the final numbers.

---

### Plan checklist §14 → where it is covered
| Checklist item | Section above |
|---|---|
| Claims built on the 4 novel elements | E, K |
| Define "Valid Response?" criteria | G (step 5), H3 |
| Max-attempts limit + escalation in Fig. 2 | H4, H5, G (step 8) |
| ML detector + runbook fallback in Fig. 1 | F |
| Safeguards against hallucination | G (safeguards paragraph) |
| Email, guide details, date, typo | A, B4, L |
| Implementation-derived claims 8–13 + evidence | M |
