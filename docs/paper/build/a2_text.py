"""Paper A2 body text, 28 Oct 2026: the authors' reworded chunks (paperA2_chunks/, edited
12:39-12:43), corrected against the original text wherever the rewording changed a fact,
a number or the meaning. build_paper_a2.py puts these strings into the paper in order.
Tables, captions of tables, headings and references are not taken from the chunks.
"""

TITLE = ("Policy-Guarded Recovery of Known and Unknown Microservice Faults "
         "with a Local Large Language Model")

# The template forbids symbols and math in the abstract: no %, no ~.
ABSTRACT = (
    "Large language models (LLMs) can interpret monitoring data and suggest corrective actions "
    "for failing services, but executing these actions on live systems carries risks: a plan may "
    "reference the wrong service, include an invented action, or be malformed. This work "
    "describes a closed-loop incident response system for microservices in which an anomaly "
    "detector and alerting rules identify faults, a locally hosted LLM or rule-based runbooks "
    "suggest actions, and a deterministic policy validator alone determines which actions may "
    "run. Every executed fix is checked, and an incident that persists is re-analyzed until "
    "three attempts have failed and is then escalated. We compare the runbooks, the LLM and the full system over {n_total} "
    "fault-injection runs spanning 18 scenarios on a three-service containerized application, "
    "partitioned into faults for which a runbook had been written and faults for which none "
    "had, and we test the validator with 29 adversarial plans. No unsafe action was executed in "
    "any run or adversarial case. On known faults, runbooks were preferable: the LLM identified "
    "the same root causes but chose a less suitable fix in {llm_wrong_word} percent of runs and "
    "added about {llm_cost} seconds to recovery. On four unknown faults, the full system resolved "
    "{nautopct_S} percent of runs versus {nautopct_B1} percent for the runbooks: the detector "
    "identified faults below the alerting thresholds and the LLM chose a fix where no rule "
    "applied, while with the LLM disabled the same detections could only be escalated. Faults "
    "that every variant misdiagnosed were escalated after a bounded number of attempts. Our "
    "results suggest runbooks for known faults, the LLM where they end, and one guard for both.")

KEYWORDS = ("Keywords—incident response, large language models, AIOps, automated remediation, "
            "safety, microservices")

CONTRIBUTIONS = [
    "1) A closed-loop design (monitor, detect, analyze, decide, respond, verify) in which the LLM "
    "has no access to the system and a policy validator is the only path to execution, enforcing "
    "an action allowlist, known targets, a confidence threshold, a cross-incident cooldown, "
    "per-incident limits, human approval of destructive actions, and bounded re-analysis with "
    "escalation.",
    "2) An adversarial set of 29 hallucinated, malformed and malicious plans executed against "
    "the real responder, revealing four input-handling defects in the responder and the gateway "
    "that were corrected prior to the evaluation.",
    "3) A test on real containers with {n_total} fault-injection runs across 18 scenarios in "
    "three groups, known faults, misleading, below-threshold and recurring faults, and faults "
    "without a runbook, and four system variants, including one where the LLM is not available.",
    "4) A comparison of the detector, the LLM and the runbooks under the same guard, showing that "
    "each covers a different part of the problem: the runbooks the known faults, the detector the "
    "subtle ones, and the LLM the faults no runbook matches.",
]

FIG1_CAPTION = "The architecture of the proposed system."
FIG2_CAPTION = "Mean time to recover per core scenario (20 runs per bar)."

PARAGRAPHS = [
    # 0 I
    "Modern web applications are composed of many small services, and a fault propagates along "
    "the call chain. When a database is slow, the service that calls it shows high latency and "
    "the front end returns errors, so the alert that fires first might not be the cause. "
    "Incidents are still handled by an on-call engineer, who receives an alert, looks at "
    "dashboards, reads a written runbook and applies a fix, generally a restart or a rollback "
    "[@sre]. Detection is mature and simple fixes are scripted, but the step in the middle, "
    "deciding what is wrong and which fix is safe, remains a manual and time-consuming process.",
    # 1
    "AIOps (artificial intelligence for IT operations) uses machine learning to find anomalies "
    "and group related alerts [@dang], and recent research shows that LLMs can propose root "
    "causes and remediation steps for cloud incidents [@ahmed, @rcacopilot]. Open-source "
    "assistants such as k8sgpt [@k8sgpt] and HolmesGPT [@holmes] provide natural-language "
    "explanations of problems in a cluster. For the most part, these tools offer "
    "recommendations; when they are allowed to take actions, their safety depends on the output "
    "being correct. An LLM can make up the name of a non-existent service, invent an action, give "
    "a confidence that is not a number, or repeat a fix that has already failed, and executing "
    "such output directly can turn a small incident into an outage.",
    # 2
    "This paper asks whether the remediation step can be handed to an LLM if the model is "
    "treated as an untrusted advisor inside a closed control loop. The LLM gives a plan, a "
    "separate policy validator that does not trust the plan decides whether it may run, each fix "
    "is verified, and the loop terminates after a bounded number of attempts and hands the "
    "incident to a human. We address four questions. RQ1 (safety): can such a loop operate on "
    "live containers without an unsafe action, even when the plans are malformed or malicious? "
    "RQ2 (known faults): given the same detection, does the LLM diagnose and act better than "
    "rule-based runbooks? RQ3 (unknown faults): which component helps when no runbook was "
    "written for the fault? RQ4 (robustness): what happens if the diagnosis is incorrect, the "
    "fault is misleading or recurring, or the LLM is unavailable? The contributions are:",
    # 3
    "The entire system runs on one laptop with a locally hosted 8-billion-parameter model, so "
    "operational data never have to leave the machine and there is no cloud inference. A small "
    "local model also keeps the compute and energy cost of automated operations low, which is "
    "consistent with the sustainability theme of this conference. Section II reviews related "
    "work, Section III describes the system architecture and Section IV the safety design. "
    "Sections V and VI present the evaluation, Section VII discusses limitations, and Section "
    "VIII concludes.",
    # 4 II
    "*AIOps and root-cause localization.* Anomaly detection, alert correlation and fault "
    "localization are performed by learning from metrics, logs and traces [@dang]. In "
    "microservices, a failure in one service produces symptoms in its callers; MicroRCA "
    "[@microrca] ranks candidate causes over a graph of services and hosts. We use a simpler "
    "signal: each service records the time it waits for its downstream call, which is available "
    "to both the runbooks and the LLM.",
    # 5
    "*LLMs for incident management.* Ahmed et al. [@ahmed] demonstrated that fine-tuned LLMs can "
    "recommend root causes and mitigation steps for production cloud incidents, and RCACopilot "
    "[@rcacopilot] combines collected diagnostic data with an LLM to predict the root-cause "
    "category. AIOpsLab [@aiopslab] offers an environment in which LLM agents detect, diagnose "
    "and mitigate injected faults, and it measures how often they succeed. These works assess "
    "the quality of the diagnosis or the success of the agent, not how to limit the damage once "
    "a wrong recommendation is executed.",
    # 6
    "*Guarding LLM output.* Guardrail toolkits such as NeMo Guardrails [@nemo] limit what a "
    "conversational model may say or which tools it may call. Remediation needs checks that "
    "depend on the state of the system: whether the same action was executed minutes ago, how "
    "many actions an incident has already used, and whether the alert is still active. Site "
    "reliability practice [@sre] codifies such rules in runbooks, graded escalation and review, "
    "and chaos engineering [@basiri] injects failures to test them. We turn these rules into a "
    "validator that every action must pass, test it with adversarial plans, and evaluate the "
    "entire loop end to end on real containers.",
    # 7 III
    "The proposed system is organized as a closed control loop, illustrated in Fig. 1. "
    "Monitoring data pass through detection, the event gateway, analysis and the policy "
    "validator to the executor, and the verifier closes the loop by sending unresolved "
    "incidents back for re-analysis.",
    # 8 III-A
    "The target is a three-tier web application: a frontend service calls an api-service, which "
    "reads and increments a counter in Redis. The two Python services export request counts, "
    "latency histograms and an upstream-latency histogram; container CPU and memory metrics "
    "come from cAdvisor, and Prometheus [@prometheus] scrapes all targets every 5 s. Prometheus "
    "alert rules for high CPU, memory, latency, error rate and service unavailability use 30 s "
    "windows with a 20 s hold. A per-service anomaly detector, using robust z-scores [@mad] and "
    "an Isolation Forest [@iforest] trained on fault-free traffic, adds early signals for "
    "faults that grow slowly or stay below the alert thresholds. Each service also exposes a "
    "fault-injection endpoint for the evaluation; its fault-state gauges are removed from every "
    "input of the system and used only for scoring.",
    # 9 III-B
    "Alerts come from Alertmanager via a webhook and anomalies come from the detector. Signals "
    "within 60 s on services of the same call chain are combined into one incident, so a Redis "
    "failure and the resulting API and frontend alerts are handled together. After a settle "
    "period of 10 s, the gateway builds the incident context: for each service the current "
    "values and ten-minute trends of CPU, memory, latency, error rate and upstream latency, the "
    "container status, the topology and the actions attempted so far. The incident is "
    "broadcast over a WebSocket and stored in SQLite.",
    # 10 III-C
    "The analyzer turns each incident into a response plan: root-cause service, incident type, "
    "severity, evidence, confidence, a recommended and a fallback action, and an explanation. It "
    "prompts Llama 3.1 8B [@llama], served locally by Ollama at temperature 0, with a system "
    "prompt, few-shot examples and the incident, and constrains the answer with a JSON schema. "
    "The answer is then checked with strict types; a confidence stated as text or as a Boolean, "
    "for example, is rejected. If the model cannot be reached, times out, produces invalid "
    "output or states a confidence below 0.7, the analyzer falls back to YAML runbooks, "
    "deterministic rules that map alert and anomaly patterns to a plan. The analyzer only makes "
    "recommendations; it has no access to the containers.",
    # 11 III-D
    "The responder is the only component that takes action. For each plan it re-checks that the "
    "incident is still active, passes the plan to the policy validator, executes the permitted "
    "action through the service's reset endpoint or the Docker API, and after 45 s checks "
    "whether the alerts have cleared and no anomaly is still active. If the incident persists, "
    "it asks the gateway to re-analyze it with the attempt number and the actions already "
    "attempted; after the third attempt it escalates to a human. All outcomes are reported back "
    "to the gateway, so the dashboard and the store capture the entire timeline.",
    # 12 IV
    "We treat the output of the analyzer as untrusted input: any client can submit a plan to the "
    "gateway, and the responder does not rely on the analyzer's schema. The policy validator "
    "applies the checks in Table I to the recommended action and then to the fallback action; "
    "the first that passes is used, otherwise the incident is escalated. We call an action "
    "unsafe if it is not on the allowlist, targets a component not permitted for it, or runs "
    "without a required approval.",
    # 13
    "This creates three levels of autonomy: safe and reversible actions run automatically, "
    "destructive or uncertain actions wait in an approval queue, and everything else is passed "
    "to a human together with the incident context and the actions attempted so far. The "
    "executor implements only the allowlisted actions, so there is no path from model text to a "
    "shell command. A pre-check avoids acting on alerts that cleared while the plan was being "
    "generated, and the cooldown breaks restart loops when a fault keeps returning.",
    # 14
    "We built an adversarial suite of 29 plans that pass through the real responder with a "
    "recording executor: invented action types, shell text in fields, targets outside the "
    "application, wrong types (lists, null, Booleans), confidences that are missing, NaN, "
    "infinite or out of range, extra command fields, a valid action in cooldown with a "
    "malicious fallback, and exhausted action limits. Five of these plans would have passed the "
    "analyzer's own output schema, so only the responder's checks stop them. Building the suite "
    "revealed four input-handling defects in the responder and the gateway, which we then "
    "fixed; for instance, a NaN confidence passed the threshold test because NaN < 0.7 is false, "
    "and a Boolean true was read as a confidence of 1.0. After the fixes all 29 cases behave as "
    "specified: the control plan runs, and every adversarial plan is blocked, reduced to its "
    "safe part or sent to a human.",
    # 15 V-A
    "All experiments were performed on one laptop (Apple M4, 10 cores, 16 GB) with Docker "
    "Desktop; the LLM runs on the host. A Locust load generator sends about five requests per "
    "second. A fault injector starts each fault, logs its start and planned end, and polls the "
    "target until the fault is gone. A run counts as remediated if the fault is gone before its "
    "planned end, which only happens if the system fixed it. The scenarios are listed in Table "
    "II.",
    # 15b V-A, after Table II
    "Scenarios 1 to 9 form the core set of known faults, the ones the runbooks were written "
    "for, lasting 180 s (300 s for the leak). Scenarios 10 to 14 form an extra set of "
    "misleading, below-threshold and recurring faults lasting 300 s (480 s for scenario 14). "
    "Scenarios 15, 16, 18 and 19 form a third, unknown set of faults for which no runbook rule "
    "was written, lasting 300 s: subtle faults on the frontend, two faults at once, and a Redis "
    "memory fault. Existing rules still match 18 and 19, but the memory rule's restart cannot "
    "fix 19. We added this set "
    "after the first two had been evaluated and ran it on the unchanged system.",
    # 16 V-B
    "*B1*: alert rules and runbooks, without the LLM or the anomaly detector. *B2*: alert rules "
    "and the LLM with runbook fallback, without the detector. B1 and B2 receive identical "
    "signals, so their difference isolates the analysis step. *S*: the full system. *SF*: the "
    "full system with the LLM unreachable, so that its runbooks act on the detector's "
    "incidents; it was run on scenarios 3, 4, 6 and 8 and on the unknown set. S and SF differ "
    "only in the analysis step, while SF and B1 differ only in the detector. The responder and "
    "the policies are identical across all variants.",
    # 17 V-C
    "Each round runs every scenario once per system in a shuffled order fixed by a seed, with "
    "rounds interleaved across systems and 300 s between consecutive runs, so the cooldown never "
    "carries over. The core set ran for {rounds_min} rounds ({n_B1} runs per system), the extra "
    "set for 10 rounds ({n_extra} runs) and the unknown set for 10 rounds on all four variants "
    "({n_novel} runs); a run the laptop slept through was voided and repeated. We report the "
    "root-cause accuracy of the first plan; the correctness of the executed action against the "
    "expected action; unsafe actions; collateral actions, permitted actions on a service that "
    "was not the cause; the auto-resolution rate; the mean time to recover (MTTR, from fault "
    "start to fault gone, for remediated runs); the share of runs needing a second attempt; the "
    "escalation rate; and the LLM cost as plan latency and tokens per incident.",
    # 18 VI-A
    "In none of the {n_total} runs of the four variants was an unsafe action executed, and no "
    "incident was opened without an injected fault. Safety was not free: on the misleading "
    "faults of the extra set the variants executed {coll_B1}, {coll_B2} and {coll_S} collateral "
    "actions (B1, B2, S), resets and restarts of a healthy service that the policy permits, and "
    "S executed {ncoll_S} more on the unknown set; the cooldown and the action limit capped these "
    "at three per incident. No plan in the live runs proposed a destructive action, so the "
    "approval path was exercised only by the adversarial suite.",
    # 19
    "To see how the policy behaved in practice, we counted its decisions in the "
    "{guard_incidents} incidents recorded by the incident store (core rounds 5 to 20, extra "
    "rounds 2 to 10). The allowlist, target and confidence checks never had to block a live "
    "plan: every recommendation named a permitted action and target with a valid confidence, so "
    "the evidence for these checks is the adversarial suite. The guard intervened through the "
    "cooldown: on the extra set, the LLM variants recommended {cd_B2} (B2) and {cd_S} (S) times "
    "to repeat a reset or restart that had just failed, each time the cooldown blocked it, and "
    "the responder ran the fallback action or escalated. The runbooks never did this, because "
    "their plans for unmatched incidents escalate directly.",
    # 20 VI-B
    "On the core scenarios, summarized in Table III, every variant detected every fault. B1 and "
    "B2 found the root cause in every run, but the executed action was correct in {act_B1} of "
    "runs for B1 and {act_B2} for B2. All of B2's wrong actions were on scenario 5 ({act5_B2} "
    "correct), where the LLM identified the correct service but restarted it rather than "
    "resetting its fault; the restart also cleared the fault, so the mistake cost time rather "
    "than safety.",
    # 21
    "The LLM was also slower: a runbook plan takes milliseconds to produce, while the LLM needed "
    "{lat_B2} s per plan on this laptop. Fig. 2 illustrates the impact on recovery: it plots the "
    "mean time to recover of B1, B2 and S in each of the nine core scenarios, and the B2 bar is "
    "higher than the B1 bar in all of them. Excluding scenario 8, mean MTTR was {mttrx8_B1} s for "
    "B1 and {mttrx8_B2} s for B2, about {llm_cost} s more per incident. The difference is "
    "systematic: in each of the nine core scenarios every B2 run took longer than every B1 run "
    "(Mann-Whitney U = 0, p < {mwu_pmax} per scenario), with a median shift of {hl_min} to "
    "{hl_max} s (Hodges-Lehmann; {hl_pooled} s over scenarios 1 to 7 and 9). On the faults the "
    "runbooks were written for, the runbooks were therefore both more accurate and faster.",
    # 22
    "S achieved the lowest mean MTTR ({mttr_S} s) only because of scenario 8, a gradual memory "
    "leak that its anomaly detector reports long before the memory alert fires ({mttr8_S} s "
    "against {mttr8_B2} s for B2). That advantage comes from detection, not from analysis; "
    "without scenario 8, S ({mttrx8_S} s) lies between B1 and B2. S also had the most "
    "predictable recovery: 90 percent of its runs recovered within {mttrp90_S} s and its slowest "
    "run took {mttrmax_S} s, against {mttrp90_B1} s and {mttrmax_B1} s for B1, because no fault "
    "in S waited for a slow alert before the loop could act.",
    # 23 VI-C
    "The results for the unknown set are listed in Table IV. The subtle frontend faults (15 and "
    "16) remained below the alert thresholds, so neither B1 nor B2 responded. The anomaly "
    "detector found the latency fault (15) in every S and SF run. With the LLM unavailable, SF "
    "had no runbook rule for an anomaly-only latency incident and escalated all ten runs; S "
    "resolved {n15res_S} of 10, {s15_first} after a correct first reset of the frontend in "
    "{s15_fmin} to {s15_fmax} s, and {s15_later} after the verify loop corrected a first plan "
    "that blamed the api-service ({s15_later_t} s); the other {n15esc_S} were escalated. The "
    "detector found this fault and the LLM "
    "fixed it; neither did so alone. The 5 percent error fault (16) is intermittent and was "
    "detected in only {n16det_S} S runs and {n16det_SF} SF run, and it was never resolved.",
    # 24
    "The combined fault (18) fires the usual error alert, and B1, B2 and S resolved it in every "
    "run, one service per attempt (S needed a third attempt once); B1 was fastest "
    "({mttr18_B1} s against {mttr18_S} s for S). SF resolved {n18res_SF}, escalating when its "
    "incident opened on the anomaly before the alert. In the Redis memory fault (19), every "
    "variant named Redis and restarted it, but Redis reloaded the keys from disk, so the fault "
    "remained; no plan, from the LLM or a runbook, suggested flushing the cache. S and SF saw "
    "the anomaly persist and escalated every run. Without the detector, the verifiers of B1 and "
    "B2 accepted the restart in {nfalsever_B1} and {nfalsever_B2} runs because the memory alert "
    "had briefly cleared, and the alert later opened a new incident. Over the 40 runs, S "
    "resolved {nauto_S}, B1 and B2 {nauto_B1} each, and SF {nauto_SF}.",
    # 25 VI-D
    "S identified the wrong root cause in {rcwrong_S} of {n_S} first plans. Its incidents often "
    "open on an early anomaly, before the alerts show the full picture, so the first plan has "
    "less evidence; this is the price of acting earlier. The verify loop repaired {repaired_S} "
    "of these: in scenario 6 the first plan blamed the api-service for the Redis failure, and in "
    "scenario 4 it blamed the frontend for the API latency. The fix did not clear the fault, the "
    "verifier sent the incident back with the failed action in its history, and the second plan "
    "acted on the correct service. These runs recovered in {rep_min} to {rep_max} s instead of "
    "about 70 s, without harm. In the remaining run an early runbook plan escalated the incident "
    "seconds before a correct LLM plan arrived, which the responder then ignored. In all, "
    "{att2_S} S runs needed a second attempt (the other three after a correct fix that the "
    "verifier judged unresolved while an anomaly faded); B1 and B2 never did.",
    # 26 VI-E
    "The results for the extra set are summarized in Table V. In the two misleading Redis "
    "faults (10 and 11), Redis keeps running while the api-service shows the errors or latency. "
    "All variants, the LLM included, blamed the api-service (a single S run blamed the "
    "frontend); no plan proposed flushing the cache or restarting Redis. The cooldown, fallback "
    "and action limit kept the response bounded, and all {esc1011} of these runs were escalated "
    "to a human with the actions already attempted. The recurring fault (14) was escalated in "
    "all {esc14} runs after the reset and the restart failed, as intended. The below-threshold "
    "faults (12 and 13) did not trigger alerts, so B1 and B2 never intervened; through its "
    "anomaly detector, S detected scenario 12 in {det12_S} and scenario 13 in {det13_S} runs, "
    "and resolved scenario 12 in {res12_S} runs. In scenario 13 the intermittent anomaly was "
    "older than the responder's freshness window when four LLM plans arrived, so the pre-check "
    "skipped them as already cleared; the fifth detected run was escalated by a runbook plan.",
    # 27 VI-F
    "With the LLM unreachable, SF fell back to the runbooks and resolved {sf_fixed} of "
    "{sf_runs} known-fault runs, the memory, Redis and leak faults in every run and faster than "
    "S, since no LLM call was made. In {sf4_esc} of 10 latency runs (scenario 4), the incident "
    "opened on an anomaly before the latency alert fired, no runbook matched an anomaly-only "
    "latency incident, and the fallback plan escalated it early; the same gap caused its "
    "escalations in scenarios 15 and 18 of the unknown set. An incident in S used {calls_S} LLM "
    "calls on average, with about {tokin_S} prompt and {tokout_S} completion tokens on the core "
    "set; with a local model this costs time, not money, about {lat_S} s per plan.",
    # 28 VII
    "*What the guard contributes.* The errors made by the LLM were exactly the kinds the guard "
    "was designed for: a weaker action on a known fault, the symptom service blamed for a "
    "misleading fault, and a failed action recommended again on re-analysis ({cd_S} times in S) "
    "although the incident history listed it. In each case the outcome was bounded by the "
    "policy layer and the verify loop, not by the model. Safety therefore did not depend on the "
    "quality of the model, which matters because an operator cannot verify each recommendation "
    "of a model in advance.",
    # 29
    "*Each component has a different role.* On known faults the LLM added latency and no "
    "accuracy, and on the misleading faults it failed in the same way as the runbooks. On the "
    "unknown set it was the only analysis step that resolved the subtle latency fault, and only "
    "because the detector had found it first: the detector without the LLM could only escalate, "
    "and the LLM without the detector never saw the fault. The detector also prevented the "
    "verifier from accepting a restart that had not worked. A deployment should therefore assign "
    "known patterns to runbooks, call the LLM when no runbook applies, and keep the same guard "
    "for both. The LLM is not a universal fix: for the Redis memory fault it suggested the same "
    "useless restart as the runbook.",
    # 30
    "*Validity.* Faults are injected through an endpoint, so the reset action stands in for real "
    "rollbacks or feature-flag switches. The testbed is a single laptop with three services, "
    "synthetic load and one 8-billion-parameter model; a larger model may diagnose the "
    "misleading faults better. The unknown set has four scenarios, created by the authors after "
    "the first evaluation, so it shows where the LLM can help rather than how often it will. A "
    "manual baseline in which an engineer handles the same faults is needed to measure the time "
    "saved against current practice. Future work includes error logs and deployment events in "
    "the incident context, rollback as an action, fine-tuning the model on logged incidents and "
    "testing it on held-out faults, and larger Kubernetes deployments.",
    # 31 VIII
    "We presented a closed-loop incident response system in which a policy layer, not the LLM "
    "itself, decides what runs. On real containers no unsafe action was executed in {n_total} "
    "runs or 29 adversarial plans, the verify loop repaired wrong first diagnoses, and misleading "
    "or recurring faults were escalated after a bounded number of attempts. On known faults the "
    "runbooks outperformed the LLM in both action choice and speed; on faults without a runbook, "
    "the detector and the LLM together resolved {nauto_S} of 40 runs against {nauto_B1} for the "
    "runbooks. Bounded, verified automation with graded human approval enables operators to use "
    "LLMs where runbooks end, without trusting them.",
]
