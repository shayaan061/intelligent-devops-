# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A final-year project (Sharda University) and patent disclosure: an "Intelligent DevOps Monitoring & Incident Response System". The loop is Monitor → Detect (Prometheus rules + ML) → Analyze (LLM) → Decide (policy validator) → Respond (executor) → Verify (re-analyze up to 3 times, then escalate).

**`SUGGESTED_PLAN.md` is the plan that drives the work.** It contains the architecture, the JSON schemas (`IncidentEvent`, `ResponsePlan`), the alert rules, the policies, the target repo layout and the checklist of next steps (§15). The other plan files feed into it: `PATENT_ALIGNED_PLAN.md` is the base, `PROJECT_PLAN.md` is the ML-centric alternative, and `PLAN_COMPARISON.md` explains the choice. `PATENT_CHANGES.md` lists edits to `patent .pdf`. When you finish an item, tick it in §15.

## Current state

The base layer and the 3-service demo app exist. Alert rules, Alertmanager, the fault injector and Locust load exist too. The Event Gateway (`gateway/`, port 8000), the analyzer (`analyzer/` + `runbooks/`) and the responder with verifier (`responder/`, port 8001) exist, and the loop closes on real containers. A minimal UI is at `dashboard/index.html` (served by the gateway). The ML detector and the full dashboard are still planned. See `PROGRESS.md` Steps 5–7.

Gateway → analyzer contract (`analyzer/schemas.py` is the source of truth):
- Alerts and ML anomalies (`POST /anomalies`) are grouped into incidents (`gateway/incidents.py`): one open incident per chain, open while an alert fires or an anomaly is < 60 s old. After a 10 s settle the gateway broadcasts `{"type": "incident", "status": "open|updated|resolved", ...}` on `/ws/events` with the 10-minute context from `gateway/context.py`. Never add a `fault_*` query there; an import-time assert enforces it.
- The analyzer turns `open`/`updated` incidents into a `ResponsePlan` and POSTs it to `/responses`, which is broadcast on `/ws/responses`. It uses Ollama on the host (`OLLAMA_URL`, default `host.docker.internal:11434`; installed with Homebrew as a launchd service, model `llama3.1:8b`, about 15–25 s per plan on this Mac) and falls back to the YAML runbooks; `ANALYZER_MODE=runbook` is baseline B1. It only recommends, never executes.
- The responder is the only thing that executes actions: plans from `/ws/responses` → pre-check (alerts still active?) → `responder/policy.py` (rules in `responder/policies.yaml`, mounted, restart to apply) → `responder/executor.py` → verify after 45 s → `POST /incidents/{id}/reanalyze` (attempt+1) → escalate after 3 attempts. It reports every outcome to the gateway's `POST /actions`; executed/failed ones become `history.previous_actions` (`[{"type", "target", ...}]`). One plan per incident at a time; stale-attempt plans are ignored. New action types go in `policies.yaml` *and* `executor.py`.
- Prompt changes (`analyzer/llm.py` SYSTEM_PROMPT): rerun `experiments/compare_analyzers.py --repeat 2` on all samples before keeping one. A rule that fixed scenario 5 broke scenario 1 (the model anchors on the few-shot examples, which mostly blame api-service).
- Untrusted plans: anything can POST to the gateway's `/responses`, so the responder must not rely on the analyzer's schema. Keep `experiments/safety_suite.py` at 29/29 when touching `policy.py`, `executor.py` or `handle_plan`; add a case for every new action type. Gateway inputs reject NaN/Infinity (`strict_loads`).
- The 5-minute cooldown is across incidents: back-to-back scenarios that need the same action get the fallback or an escalation. Decided 6 Oct: keep 300 s and run suites with `--gap 300` (SUGGESTED_PLAN.md §10).
- The gateway writes every broadcast message to SQLite (`INCIDENT_DB`, `experiments/incidents.db` in compose; `GET /history/{id}`). Grouping state is still in memory.
- On macOS, cAdvisor only gets the `name` label if Docker Desktop's containerd image store is off; otherwise HighCPU/HighMemory never fire and context `cpu`/`mem` are null (PROGRESS.md, Next steps A).

Request path: `frontend` (`app/`, host port 5001) → `GET api-service:5000/data` (`api-service/`, host port 5002) → `redis` (`INCR hits`).
- Both Flask services contain the same fault-injection, `/health`, `/metrics`, `/inject` and `/reset` code, copied into each one (the Docker build contexts are separate). A fix to that code must be made in both files.
- `/inject` body: `{"fault": "cpu|memory|latency|error", "duration": 1-600, "size_mb": 10-450, "ramp_seconds": 0-duration}`. With `ramp_seconds` the memory fault grows in 10 MB chunks, for the gradual-leak scenario. The caps are deliberately high. A fault has to outlast detection (~40 s) plus analysis and remediation, or the verify loop has nothing to fix. A memory fault has to be able to cross 80% of the 512 MB limit.
- Failures propagate upstream: Redis down → `api-service` returns 503 → `frontend` returns 502. A latency fault in `api-service` → `frontend` is slow too. Each service's `upstream_request_duration_seconds{upstream=...}` is how you tell the root cause from a symptom.
- The `api-service` Redis client has retries **disabled** on purpose. With redis-py's default retries, Redis being down shows up as about 4 s of latency instead of an error.
- Compose container names (`frontend`, `api-service`, `redis`, …) are the names the planned cAdvisor rules match on (`name=~"frontend|api-service"`), so don't rename them. The Prometheus job names are `frontend`, `api-service`, `redis` (the redis_exporter, port 9121) and `cadvisor`.

Alerting: `prometheus/rules.yml` → Alertmanager (`alertmanager/alertmanager.yml`, port 9093) → webhook `POST http://gateway:8000/alerts` → broadcast on `ws://localhost:8000/ws/events` (`GET /events` for the last 100).
- Every alert has a `service` label (`frontend | api-service | redis`; `monitoring` for ExporterDown). Container rules take it from cAdvisor's `name` label and HTTP rules take it from `job`, both via `label_replace`. The gateway relies on this label.
- Rate windows are 30 s with `for: 20s`, so detection takes about 40 s. Don't go back to the plan's 1-minute window: a 30 s CPU fault would never fire.
- HTTP rules only look at `endpoint=~"/|/data"` (healthchecks are excluded) and need live traffic. With no requests the rate is NaN and nothing fires.
- A downstream fault makes alerts fire on the symptom service too (`api-service` latency → HighLatency on both; `api-service` down → ServiceDown on `api-service` plus HighErrorRate on `frontend`). Separating cause from symptom is the gateway's and LLM's job, using `upstream_request_duration_seconds`. Alertmanager only inhibits latency and error alerts for the *same* service when it is down.
- `send_resolved: true` is set for the verifier. Resolved notifications carry the annotation text from the last time the alert fired (old values), so don't read values from them.

Evaluation tooling:
- `load/locustfile.py` runs as the `load` service by default (`LOAD_USERS`, default 5, gives ~5 req/s). The HTTP alerts depend on it.
- `injector/injector.py` runs the 9 scenarios from §10 of the plan. HTTP faults go to each service's `/inject` and container stops use the Docker SDK. Each run appends a row to `experiments/ground_truth.csv` with `start`, `planned_end`, the actual `end` and an `end_reason`: `expired`, `remediated` (the fault was gone before `planned_end`, so the system fixed it; this is what MTTR and auto-resolve are scored on) or `cleanup` (the injector had to undo it). The `end` time comes from polling the target's `/health` fault flags or the container status. `MIN_DURATION` forces scenario 8 to at least 300 s so the ramp completes.
- `injector/web.py` is a browser control panel for the injector (compose service `injector-ui`, port 8088, started by default; same image, different entrypoint). Scenario runs call `run_scenario(..., cancel=Event)`. A cancelled run is undone and writes no CSV row. Manual faults and container actions are demo-only (not logged) and are refused while a run is active. "Reset all" cancels the run first, so the reset isn't scored as `remediated`.
- The injector is a compose service under the `tools` profile, so `docker compose up` doesn't start it. Inside compose it uses service-name URLs and the mounted Docker socket. On the host it defaults to `localhost:5001/5002` (override with `FRONTEND_URL`, `API_SERVICE_URL`, `GROUND_TRUTH_PATH`).

## Commands

```bash
docker compose up --build            # full stack; check targets at localhost:9090/targets
docker compose config -q             # validate compose file
cd prometheus && promtool test rules rules_test.yml   # alert rule unit tests (fire + no-false-positive cases)
promtool check rules prometheus/rules.yml
amtool check-config alertmanager/alertmanager.yml

curl localhost:5001/                   # full request path
websocat ws://localhost:8000/ws/events # live alert stream from the gateway
websocat ws://localhost:8000/ws/responses # plans + responder actions
curl localhost:8000/history            # incident store; /history/<id> for the timeline
curl localhost:8001/approvals          # pending approvals; POST .../approvals/<id>/approve|reject
open http://localhost:8000/dashboard/  # minimal UI: service map, incidents, approvals
RESPONDER_MODE=dry_run docker compose up -d responder   # validate only, never execute (baseline B0)
python experiments/score.py --system B1 --since <ISO>   # §10 metrics from ground_truth.csv + incidents.db
python experiments/safety_suite.py                       # 29 adversarial plans; must be 29/29, 0 unsafe
OLLAMA_URL=http://localhost:11434 python experiments/compare_analyzers.py   # runbooks vs LLM on the 9 samples
python experiments/record_baseline.py --last 2h          # ML training data (no faults/alerts); before rebuilding prometheus
curl -X POST localhost:5002/inject -H 'Content-Type: application/json' -d '{"fault":"latency","duration":30}'
curl -X POST localhost:5002/reset
docker stop redis                      # dependency-failure scenario

open http://localhost:8088                                              # injector web UI
docker compose run --rm injector list                                   # scenarios 1-9
docker compose run --rm injector run 4 --duration 180                   # one scenario
docker compose run --rm injector suite --scenarios 1-9 --repeat 3 --shuffle --seed 1 --gap 300   # gap >= the 300 s cooldown
docker compose run --rm injector reset                                  # clear faults, start stopped containers
pip install -r injector/requirements.txt && python injector/injector.py list   # or from the host
```

Tests: the rule tests above, `cd gateway && pytest -q`, `cd analyzer && python -m pytest tests` and `cd responder && pytest -q`, `pytest experiments/tests` (scorer + safety suite) (install each one's `requirements-dev.txt`). There is no linter. Get `promtool` and `amtool` from the Prometheus and Alertmanager GitHub release tarballs; they aren't installed. To smoke-test the app without Docker, run `pip install flask prometheus-client`, then drive it with `app.app.test_client()`. Run each service in its own process: both register the same metric names in prometheus_client's global registry, so importing both into one process raises `DuplicateTimeseries`.

## Invariants to preserve

- **`fault_*_active` gauges are ground truth.** Use them only to score the evaluation. Never pass them to the ML detector, the LLM context or the alert rules; filter them out in the gateway and the detector.
- **Changing `rules.yml` means updating `rules_test.yml`.** Expected labels and annotation text are matched exactly.
- **Fault lifecycle in `app.py`:** each fault has a generation counter (`fault_generation`) under `state_lock`. Start a fault with `activate_fault()`. Workers loop while `is_current(name, gen)` is true and finish by calling `deactivate_fault(name, gen)`, so `/reset` stops them early and an old timer can't clear a newer fault. New fault types must follow this pattern and auto-clear after `duration`.
- **Route instrumentation:** decorate request-serving routes with `@instrumented("<endpoint>")`, below `@app.route`. It records `http_requests_total` and `http_request_duration_seconds` on every path, error paths included. The planned rules and the ML features depend on these metric names and on `upstream_request_duration_seconds`, which must be recorded in a `finally` block around every call to the next service.
- **The memory fault must touch its pages** (it fills with non-zero bytes). Otherwise cAdvisor won't see the memory usage rise.
- **The LLM never executes actions directly.** Every action passes through the policy validator: allowlisted action types, known targets, confidence ≥ 0.7, a 5-minute cooldown, at most 3 actions per incident, and approval for risky actions. YAML runbooks are the fallback when the LLM fails and also the "no LLM" baseline (B1).
- The demo targets a laptop running Docker Compose. Kubernetes is out of scope.
