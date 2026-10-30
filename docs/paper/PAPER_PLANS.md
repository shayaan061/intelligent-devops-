# Two conference papers: plans

Written 26 Oct 2026. Every number below is from `experiments/RESULTS.md` (section given) and the
files in `experiments/results/`. Recheck each one against its source file before it goes into a paper.

| | Paper A: response | Paper B: detection |
|---|---|---|
| Question | Can an LLM drive remediation on live containers safely, and does it beat runbooks? | Does a label-free detector trained on minutes of normal traffic find faults earlier than threshold rules, without false alarms? |
| Venue | **EmergIN 2027** (IEEE, NIET, 6 pages, A4 Word template, CMT) | **DAL 2026** (IIIT Sri City, Springer LNNS, long paper ≤ 10 pages, double-blind, Word allowed, CMT) |
| Deadline | **Fri 30 Oct, 23:59 IST** | **Sat 7 Nov AoE** (8 Nov ~17:30 IST); upload by **Fri 6 Nov** |
| Decision | 20 Nov | 20 Nov |
| Starting point | Current draft (`build/build_paper.py`), narrowed | New text; reuses only data and the template |
| Metrics it owns | action correctness, MTTR, verification, escalation, unsafe actions, adversarial suite, LLM cost | recall, MTTD, who detects first, false alarms |

If acceptance is needed with margin before 20 Nov, Paper A could go to ICIDA instead (decision
10 Nov, Springer LNNS ≥ 10 pages, due 30 Oct, can't be withdrawn). That costs about a day to port
it to `template/springer_lnns/word/splnproc2510_mac.docm`. Paper A can't go to both.

---

## Rules for keeping two separate papers

1. **Each paper reports only its own metrics** (table above). A gives detection one paragraph and
   no MTTD analysis. B gives remediation one paragraph (scenario 8 MTTR and scenario 12 fixed) and
   no policy or LLM analysis.
2. **Write all text fresh in each paper.** The testbed and scenario descriptions overlap
   unavoidably; write them separately and keep them short. No copied sentences between A, B, the
   IDF, the project report or the PPT.
3. **Different figures.** A: loop architecture, MTTR / outcomes. B: detector pipeline, MTTD
   distribution, opening-source bars. No figure appears in both.
4. **Cross-citation.** A cites B as "submitted". B is double-blind: it describes the response
   system in the third person ("the incidents were handled by a policy-guarded responder") and
   leaves out the citation until the camera-ready version.
5. **Before uploading B,** run a similarity check of A against B as well as against the IDF and
   the report.
6. **Patent:** file the application before either paper is submitted, if it isn't filed already.
   A paper can count as prior art once it is public.

---

## Paper A: policy-guarded LLM remediation (EmergIN 2027)

### Title

**Policy-Guarded Remediation of Microservice Incidents Using a Local Large Language Model**

The template forbids subtitles, symbols and math in the title and abstract. An alternative is
*Keeping a Large Language Model Behind a Policy Validator for Automated Incident Response*.

### Claim

Letting an LLM choose remediation actions on live systems is safe when a deterministic policy
layer, not the model, decides what runs and a verify loop checks every fix. In our tests the LLM
found the same root cause as the runbooks on known faults but chose a weaker action in 7.8% of runs and
was about 30 s slower, so the runbooks were better there; the guard is what bounded its mistakes.

### Research questions

- **RQ1 Safety.** Can an LLM-recommended remediation loop run on real containers without an unsafe
  action, including when the plan is malformed or malicious?
- **RQ2 Value.** With identical detection, does the LLM diagnose and act better than rule-based
  runbooks? (B1 vs B2)
- **RQ3 Robustness.** What happens when the diagnosis is wrong, the fault is outside the runbooks or
  recurs, or the LLM is unavailable? (verify loop, scenarios 10/11/14, SF)

### Contributions

1. An architecture in which the LLM only recommends. A policy validator alone decides:
   allowlisted action types, known targets, confidence ≥ 0.7, a 300 s cooldown, at most 3 actions
   per incident, and approval for destructive actions (`flush_cache`, `update_resources`). A
   verify loop checks each fix after 45 s, re-analyses up to 3 times, then escalates.
2. An adversarial plan suite of 29 cases (invented actions, shell text, out-of-scope targets,
   NaN/∞/boolean confidence, malformed fields). Result: 29/29 passed, 0 unsafe. 5 cases would have
   passed the LLM's output schema and were caught only by the responder. The suite found 4
   vulnerabilities, fixed before the evaluation (RESULTS §5, §7).
3. A live evaluation on real containers: **730 fault-injection runs** over 14 scenarios and four
   variants. Results: **0 unsafe actions** and 0 false-positive incidents.
4. An honest comparison. On known faults the runbooks were better: same root cause (100% both),
   more correct actions (100% vs 92.2%) and about 30 s faster (MTTR without scenario 8: 53.0 vs 82.3 s).
   On misleading faults the LLM also blamed the symptom service. The result points to a hybrid
   design: deterministic rules for known patterns, the LLM for the rest, both behind the same guard.

### Section plan (6 pages ≈ 3,600 words + 2 figures + 4 tables)

| § | Words | Content | Source |
|---|---|---|---|
| Abstract | 180 | Problem, design (LLM behind a validator), 730 runs, 0 unsafe, 29/29, runbooks beat the LLM on known faults (same diagnosis, better actions, faster), the guard bounds misdiagnosis | §18a/b, §5 |
| I Introduction | 450 | On-call practice; LLMs can reason over telemetry, but acting is risky; the gap (no live evaluation of the safety boundary); RQ1–3; contributions | — |
| II Related Work | 400 | AIOps [Dang 2019]; LLM root cause analysis and mitigation for cloud incidents [Ahmed ICSE'23; Chen EuroSys'24]; agent benchmarks for operations (AIOpsLab, ITBench); tools that recommend or act (k8sgpt, HolmesGPT); LLM guardrails (NeMo Guardrails); chaos engineering for fault injection [Basiri 2016]. Gap: guards untested against adversarial plans, and no live remediation loop with verification | refs below |
| III Architecture | 650 + **Fig. 1** | The loop Monitor → Detect → Analyze → Decide → Respond → Verify. Detection in 3 sentences (rules plus an anomaly detector; cites Paper B). Gateway: grouping and 10-min context, no ground-truth metrics. Analyzer: local llama3.1:8b, JSON plan, runbook fallback. Responder: pre-check → validator → executor → verify | existing text |
| IV Safety Design | 450 + **Table I** | Policy rules from `responder/policies.yaml`; untrusted-plan assumption (anything can POST a plan); defence in depth (schema + validator + approval + attempt limit); what "unsafe" means (outside allowlist, unknown target, missing required approval) | `responder/policies.yaml`, §5 |
| V Evaluation Setup | 400 + **Table II** | Testbed (3 services, Docker, Locust at 5 req/s); 14 scenarios with their expected action; variants B1 (runbooks), B2 (LLM), S (full system), SF (LLM down); 20 rounds core, 10 extra, interleaved, 300 s gaps, voiding rule; metrics | §18 setup |
| VI Results | 850 + **Table III**, **Fig. 2**, **Table IV** | A. Safety. B. LLM vs runbooks. C. Wrong diagnoses and the verify loop. D. Faults outside the runbooks. E. LLM unavailable. F. Cost (details below) | §18a/b |
| VII Discussion and Limitations | 350 | Where the LLM is (not) useful; interaction races; validity (laptop, one model, injected faults, `reset_faults` stands in for rollback, no manual baseline) | §17, §18b |
| VIII Conclusion | 120 | — | — |

### Results subsections and their numbers

- **A. Safety (RQ1).**
  - 0 unsafe actions in 730 runs (core 540, extra 190) and 29/29 adversarial plans.
  - State it honestly: in the extra set the variants executed *collateral* actions (allowed actions
    on a non-root-cause service) 43 / 35 / 36 times (B1 / B2 / S). These are within policy and
    bounded, but they are not free.
  - The approval path was never triggered live: no plan proposed `flush_cache`. It is exercised
    only by the adversarial suite.
- **B. LLM vs runbooks (RQ2), Table III.**

  | | B1 | B2 | S |
  |---|---|---|---|
  | Root cause correct | 100% | 100% | 97.2% |
  | Executed action correct | 100% | 92.2% | 93.9% |
  | Auto-resolved | 100% | 100% | 99.4% |
  | MTTR mean (s) | 75.3 | 104.9 | 74.1 |
  | MTTR mean without scenario 8 (s) | 53.0 | 82.3 | 70.8 |
  | Plan latency | 0.4 ms | 28.4 s | 27.0 s |
  | Tokens per incident (in / out) | – | 2917 / 180 | 4284 / 261 |

  All 14 of B2's wrong actions were on scenario 5 (restart instead of reset). The root cause was
  right and the restart also cleared the fault, so the error cost time, not safety.
- **C. Wrong diagnoses and the verify loop (RQ3).**
  - All 4 wrong first diagnoses in S were repaired on the 2nd attempt: scenario 6 (api-service
    blamed for Redis) and scenario 4 (frontend blamed for api-service). MTTR was 124–140 s, with
    no harm and no escalation.
  - 7 S runs needed a 2nd attempt.
  - The one escalation (run `a84a748a`) was a race: an early runbook plan escalated before the LLM
    plan arrived.
- **D. Faults outside the runbooks, Table IV.**
  - Misleading Redis faults (10, 11): all 60 runs blamed the API service, then escalated after the
    attempt limit.
  - Recurring fault (14): escalated in 30/30 runs, as designed.
  - S escalated 68.9% of detected extra runs (B1 / B2: 100%).
- **E. LLM unavailable (SF).**
  - Runbook fallback resolved 34/40 runs (scenarios 3, 6, 8: 30/30, MTTR 35–70 s).
  - Latency (scenario 4): 6/10 escalated early, because no runbook covers an ML-only latency
    incident.
- **F. Cost.** Plan latency 27–32 s on the laptop; ~2.9–4.3k prompt tokens per incident (core),
  ~6.4–7.3k (extra).

### Figures and tables

- **Fig. 1:** the loop architecture, redrawn for one column (`docs/paper/build/figures.py`, existing).
- **Fig. 2:** MTTR per core scenario for B1 / B2 / S (`docs/results/figures/fig2_core_mttr.png`).
  Replaces the current MTTD+MTTR figure: MTTD belongs to Paper B.
- **Table I:** policy rules. **Table II:** scenarios 1–14 with fault, target and expected action.
  **Table III:** core results. **Table IV:** extra scenarios and SF (detected / resolved / escalated).

### Changes to `docs/paper/build/build_paper.py`

1. Retitle; rewrite the abstract and conclusion around safety and RQ2/RQ3; drop "halves MTTD".
   Replace "the LLM matched but did not improve on them" (line ~247) and "Runbooks remained as
   accurate as the LLM" (line ~567): the LLM matched on root cause only; on actions it was worse
   (92.2% vs 100%) and slower.
2. Detection: cut the subsection under Architecture to 3 sentences. In Results, replace the
   "Detection" subsection with "Safety" and drop the MTTD rows from Table III.
3. Add the verify-loop finding (C) and the collateral-action caveat (A).
4. Fix stale text:
   - soak: 10 h / 19 events → 22 h / 42 events (lines ~246, 287, 458, 495);
   - SF: "the remaining one" → 6/10 latency runs (line ~528);
   - drop the `[[...]]` markers (lines 456, 504, 523, 528).
5. Fig. 2 → MTTR figure. Build without `--provisional`.

### Optional (30 min)

A Mann–Whitney U test on MTTR, B1 vs B2 (core, per scenario and pooled). It lets the paper say the
~28 s LLM cost is significant, not noise.

### Reviewer questions to answer in the text

- "Why use an LLM if the runbooks are as good?" That is the finding. The guard makes it safe to try
  the LLM where no runbook exists. Showing that benefit needs faults outside the runbooks (future work).
- "Small testbed." Three services on one laptop, but 730 live runs with interleaved systems and
  fixed seeds. Say so plainly in Validity.
- "Why an 8B local model?" Data stays on-premises and there is no per-token cost. Larger models
  are future work.
- "How is 'unsafe' defined?" Define it once, in Section IV.

---

## Paper B: label-free detection (DAL 2026)

### Title

**Label-Free Per-Service Anomaly Detection for Early Detection of Slow and Subtle Faults in Microservices**

Alternative: *Robust Z-Scores and Isolation Forest Versus Threshold Alerting for Microservice Fault Detection*.

### Claim

A per-service detector (one-sided robust z-scores plus an Isolation Forest, trained on 78 minutes
of normal traffic with no labels) detects faults earlier and more consistently than
production-style threshold rules. It finds faults below the rule thresholds and raised no false
alarm in 22 h of fault-free operation with restarts and load changes. Its blind spots are
predictable.

### Research questions

- **RQ1 Delay.** How much earlier than threshold rules does the detector find faults, and for which
  fault types?
- **RQ2 Coverage.** Does it find faults that never cross an alert threshold?
- **RQ3 False alarms.** How often does it fire during normal operation, including restarts and load
  levels it was not trained on?
- **RQ4 Limits.** Which faults can't it see, and why?
- (**RQ5 Ablation**, optional, see below.)

### Contributions

1. A detector design for small-data operations:
   - one-sided robust z-scores with per-metric floors (only "worse" counts);
   - an Isolation Forest over the z-vector;
   - a two-poll persistence rule;
   - training on 945 samples of normal traffic, with no labels and no GPU;
   - an explicit guard against ground-truth leakage (the fault gauges are never features).
2. Integration semantics for a live alerting pipeline. A repeat anomaly refreshes the open
   incident instead of opening a new one. The 20 s freshness window, and why 25 s failed (RESULTS §12b).
3. A live evaluation against the threshold rules: 180 + 180 core runs, 50 + 50 extra runs, plus
   held-out data, an offline replay and 22 h of soak tests.
4. A description of the blind spots: stopped containers, symptom-vs-cause, intermittent faults.

### Section plan (LNNS long paper ≤ 10 pages ≈ 4,200 words + 3 figures + 4 tables)

| § | Words | Content | Source |
|---|---|---|---|
| Abstract + keywords | 200 | LNNS asks for 150–250 words | — |
| 1 Introduction | 600 | Threshold alerting needs hand-set limits and rate windows; it misses slow leaks and below-limit degradation and reacts late to gradual change. Deep detectors need lots of data. RQs, contributions | — |
| 2 Related Work | 600 | Threshold alerting in practice [SRE book]; anomaly detection surveys [Chandola 2009]; robust statistics / MAD [Rousseeuw & Croux 1993; Leys 2013]; Isolation Forest [Liu 2008]; deep multivariate detectors (Donut, OmniAnomaly, USAD); microservice anomaly detection and RCA (Soldani & Brogi survey, MicroRCA, Eadro); logs [DeepLog]. Gap: small-data, label-free, evaluated live against the rules it would sit next to | refs below |
| 3 Setting and Data | 400 + **Table 1** | Three services, Prometheus + cAdvisor + redis_exporter, 15 s poll; features per service (Table 1); training data: 78 min normal traffic at 5 users, 315 samples per service; filtering near faults/alerts | §12, `docs/ml_training_notes.txt` |
| 4 Method | 800 + **Fig. 1** + **Algorithm 1** | z-score formula with floor, one-sided; Isolation Forest (200 trees, 99.5% training quantile); decision rule (z ≥ 4, or forest ∧ z ≥ 2); 2-poll persistence; re-post and refresh; freshness window; retraining policy. Thresholds fixed before the evaluation, not tuned on it | `ml/model.py`, `ml/detector.py` |
| 5 Experimental Setup | 500 + **Table 2** | Fault scenarios relevant to detection (1–9, 10–14); baseline = threshold rules (30 s windows, `for: 20s`); treatment = rules + detector; protocol (20 / 10 rounds, interleaved, 300 s gaps); offline replay; soak; metrics: recall, MTTD, opening source, false-positive incidents per hour | §18 setup, §16, §19 |
| 6 Results | 1,100 + **Table 3**, **Fig. 2**, **Fig. 3**, (**Table 4**) | 6.1–6.6 (details below) | §12, §18a–c, §16, §19 |
| 7 Discussion and Threats | 450 | Blind spots and why (RQ4); trained at one load level but held at 2–10 users; single testbed; injected faults; n = 10 for the extra set | §12a, §18b |
| 8 Conclusion | 200 | — | — |

### Results subsections and their numbers

- **6.1 Detection delay (RQ1), Table 3 + Fig. 2.**

  MTTD in s, rules (B2) vs rules + detector (S), mean of 20:

  | Scenario | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
  |---|---|---|---|---|---|---|---|---|---|
  | Rules | 46 | 46 | 27 | 29 | 26 | 22 | 26 | 225 | 29 |
  | + Detector | 31 | 30 | 24 | 27 | 24 | 21 | 27 | 51 | 27 |

  Pooled: mean 52.8 → 29.0 s (−45%), sd 61.6 → 9.1 s, p90 220.2 → 45.5 s, max 230.1 → 60.1 s
  (§18a, §18c). **Fig. 2:** MTTD distribution per system (box plot or ECDF) from `eval_stage3_*_runs.csv`.
- **6.2 Who detects first, Fig. 3.** Stacked bars per scenario from `eval_stage3_S_open_sources.csv`:
  - Core rounds 5–20 (n = 144): detector alone opened 53% of incidents, both within the first
    10 s 36%, rules alone 11%.
  - The rules-only incidents are all scenario 7.
  - The detector alone opened every run of scenarios 1, 2, 8 and 12 (§18c).
- **6.3 Slow and subtle faults (RQ2).**
  - Gradual leak (8): 225 → 51 s mean over 20 runs; the detector alone opened all 16 runs in the
    store (§18c).
  - Subtle latency (12, 0.6 s): detected 10/10, rules 0/10.
  - Subtle errors (13, 5%): detected 5/10, late (159.7 s), rules 0/10 (§18b).
- **6.4 False alarms (RQ3).**
  - Held-out normal data: 0 of 63 samples flagged per service (§12).
  - Offline replay: 0 false-positive episodes in 1.07 h (§12a).
  - 0 false-positive incidents in the 270 S/SF fault runs.
  - Soak tests: 22 h, 42 harmless events (11 frontend restarts, 11 api-service restarts, 11 load
    increases to 10 users, 9 decreases to 2 users; training was at 5 users only): 0 incidents
    (§16, §19).
  - Say why in the text: request rate isn't a scored metric, doubling the load moves CPU and
    latency far less than z = 4, and restarts are shorter than the 2-poll persistence (§16). This
    also bounds the claim: a much larger or burstier load change is untested.
- **6.5 Downstream effect** (one paragraph only; remediation analysis belongs to Paper A).
  Scenario 8 MTTR 285 → 100 s; scenario 12 fixed in 10/10.
- **6.6 Ablation (optional, Table 4).** See below.

### Blind spots to report (RQ4)

- **Stopped container (scenario 7):** no metrics arrive, and missing values look typical. The
  rules' ServiceDown covers it (replay 8/9, §12a).
- **Symptom vs cause (scenario 6):** with Redis stopped, the detector sees api-service errors, not
  Redis.
- **Intermittent faults (scenario 13):** 5% errors trip the persistence rule only sometimes, so
  detection is late and partial.

### Optional ablation (RQ5): makes B a stronger "learning" paper

Replay the evaluation period offline (`ml/replay.py`) with variants:
- z-score only, forest only, combined;
- z threshold 3 / 4 / 5;
- persistence 1 / 2 / 3 polls.

Report recall, mean delay and false-positive episodes per hour for each. No new live runs are needed.

**This is time-critical.** Prometheus keeps 15 days of data by default, and `docker-compose.yml`
gives it no named volume (only the image's anonymous one). The 19–23 Oct data is deleted from about
3–7 Nov once Prometheus runs again, and it's unknown whether the anonymous volume survived. Steps:
1. Start Docker and check that the data is there.
2. Export it right away, with nothing else running:
   `python experiments/record_baseline.py --start 2026-10-19T15:37:00Z --keep-all --out experiments/results/replay_19-23oct.csv`
3. Replay against the stage-3 ground truth.

Never train on a `--keep-all` export. If the data is gone, skip the ablation; the paper stands
without it.

### Optional statistics (30 min)

- Mann–Whitney U on MTTD, B2 vs S, per scenario.
- Bootstrap 95% CI of the mean MTTD reduction.

### Double-blind checklist

- No author names, university, city, project name, patent, GitHub or dashboard URLs, or
  screenshots that show them.
- Refer to Paper A in the third person, or leave it out until the camera-ready version.
- Remove the Word document properties (File → Inspect Document).

### Reviewer questions to answer in the text

- "Why not a deep model?" Only 945 training samples and no labels. The point is a detector a
  small team can train in an hour. Deep detectors are related work, compared qualitatively.
- "Thresholds tuned on the test?" No. They were fixed on 9 Oct, before the 11–22 Oct evaluation.
- "Only one load level." The soak tests moved load between 2 and 10 users with 0 false alarms.
  Retraining for other traffic is future work.

---

## References to verify (venue, year, pages) before use

These are from memory. Check each one on DBLP or Google Scholar before citing it, and drop any
that can't be found.

Both papers: Liu, Ting, Zhou, "Isolation forest", ICDM 2008 · Beyer et al., *Site Reliability Engineering*,
O'Reilly 2016 · Dang, Lin, Huang, "AIOps: real-world challenges and research innovations", ICSE-C 2019 ·
Prometheus documentation.

Paper A: Ahmed et al., "Recommending root-cause and mitigation steps for cloud incidents using LLMs",
ICSE 2023 · Chen et al., "Automatic root cause analysis via LLMs for cloud incidents" (RCACopilot),
EuroSys 2024 · Chen et al., "AIOpsLab" (arXiv 2025) · Jha et al., "ITBench" (2025) · Rebedea et al.,
"NeMo Guardrails", EMNLP demo 2023 · Yao et al., "ReAct", ICLR 2023 · Grattafiori et al., "The Llama 3
herd of models", arXiv 2024 · k8sgpt, HolmesGPT (GitHub) · Basiri et al., "Chaos engineering", IEEE
Software 2016.

Paper B: Chandola, Banerjee, Kumar, "Anomaly detection: a survey", ACM CSUR 2009 · Rousseeuw, Croux,
"Alternatives to the median absolute deviation", JASA 1993 · Leys et al., "Detecting outliers: do not use
standard deviation around the mean, use absolute deviation around the median", JESP 2013 · Xu et al.,
"Donut", WWW 2018 · Su et al., "OmniAnomaly", KDD 2019 · Audibert et al., "USAD", KDD 2020 · Soldani,
Brogi, "Anomaly detection and failure root cause analysis in microservice-based cloud applications: a
survey", ACM CSUR 2022 · Wu et al., "MicroRCA", NOMS 2020 · Lee et al., "Eadro", ICSE 2023 · Du et al.,
"DeepLog", CCS 2017.

---

## Schedule

| Date | Paper A (EmergIN, due 30 Oct) | Paper B (DAL, due 7 Nov) |
|---|---|---|
| Mon 26 Oct | Confirm the split, venues and patent status. Create CMT accounts. Narrow `build_paper.py` + stale fixes. | (If the ablation is wanted: start Docker, check and export the Prometheus data.) |
| Tue 27 | Results subsections A–F, Fig. 2 swap, final build; open in Word and fit to 6 pages | Outline in `splnproc2510_mac.docm`; Table 1 (features) |
| Wed 28 | Authors and affiliations, references checked, **to guide** | Sections 3–4 (setting, method, Fig. 1, Algorithm 1) |
| Thu 29 | Guide's edits, similarity check, **upload** | Section 5 (setup, Table 2) |
| Fri 30 | Buffer; deadline 23:59 IST | Figs. 2–3 and Table 3 |
| Sat 31 – Mon 2 Nov | — | Section 6 (+ ablation and stats if done) |
| Tue 3 – Wed 4 | — | Sections 1, 2, 7, 8; references checked; abstract |
| Thu 5 | — | **To guide**; similarity check against Paper A; anonymise |
| Fri 6 | — | **Upload** (deadline 7 Nov AoE) |

Suggested split for a team of three: one person leads A, one leads B, and one does figures,
references and similarity checks for both. The guide reviews A on 28 Oct and B on 5 Nov.

## Risks

- **Both decisions are on 20 Nov, with no margin.** If an acceptance must be in hand before then,
  send Paper A to ICIDA (decision 10 Nov) instead of EmergIN.
- **Dual submission:** one paper per venue; ICIDA submissions can't be withdrawn.
- **Patent:** file before submitting.
- **Ablation data may already be gone:** the paper doesn't depend on it.
- **Page limits:** A is tight at 6 pages. If it overflows, cut Related Work to 300 words and merge
  Table IV into the text.
