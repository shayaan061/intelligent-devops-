# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A final-year project (Sharda University) and patent disclosure: an "Intelligent DevOps Monitoring & Incident Response System". The loop is Monitor → Detect (Prometheus rules + ML) → Analyze (LLM) → Decide (policy validator) → Respond (executor) → Verify (re-analyze up to 3 times, then escalate).

**`SUGGESTED_PLAN.md` is the plan that drives the work.** It contains the architecture, the JSON schemas (`IncidentEvent`, `ResponsePlan`), the alert rules, the policies, the target repo layout and the checklist of next steps (§15). The other plan files feed into it: `PATENT_ALIGNED_PLAN.md` is the base, `PROJECT_PLAN.md` is the ML-centric alternative, and `PLAN_COMPARISON.md` explains the choice. `PATENT_CHANGES.md` lists edits to `patent .pdf`. When you finish an item, tick it in §15.

## Current state

The base layer and the 3-service demo app exist. Alert rules, Alertmanager, the fault injector and Locust load exist too. The gateway, ML detector, LLM analyzer, responder, verifier and dashboard are still planned.

Request path: `frontend` (`app/`, host port 5001) → `GET api-service:5000/data` (`api-service/`, host port 5002) → `redis` (`INCR hits`).
- Both Flask services contain the same fault-injection, `/health`, `/metrics`, `/inject` and `/reset` code, copied into each one (the Docker build contexts are separate). A fix to that code must be made in both files.
- `/inject` body: `{"fault": "cpu|memory|latency|error", "duration": 1-600, "size_mb": 10-450, "ramp_seconds": 0-duration}`. With `ramp_seconds` the memory fault grows in 10 MB chunks, for the gradual-leak scenario. The caps are deliberately high. A fault has to outlast detection (~40 s) plus analysis and remediation, or the verify loop has nothing to fix. A memory fault has to be able to cross 80% of the 512 MB limit.
- Failures propagate upstream: Redis down → `api-service` returns 503 → `frontend` returns 502. A latency fault in `api-service` → `frontend` is slow too. Each service's `upstream_request_duration_seconds{upstream=...}` is how you tell the root cause from a symptom.
- The `api-service` Redis client has retries **disabled** on purpose. With redis-py's default retries, Redis being down shows up as about 4 s of latency instead of an error.
- Compose container names (`frontend`, `api-service`, `redis`, …) are the names the planned cAdvisor rules match on (`name=~"frontend|api-service"`), so don't rename them. The Prometheus job names are `frontend`, `api-service`, `redis` (the redis_exporter, port 9121) and `cadvisor`.

Alerting: `prometheus/rules.yml` → Alertmanager (`alertmanager/alertmanager.yml`, port 9093) → webhook `POST http://gateway:8000/alerts`. The gateway isn't built yet, so until it is, Alertmanager logs failed deliveries.
- Every alert has a `service` label (`frontend | api-service | redis`; `monitoring` for ExporterDown). Container rules take it from cAdvisor's `name` label and HTTP rules take it from `job`, both via `label_replace`. The gateway relies on this label.
- Rate windows are 30 s with `for: 20s`, so detection takes about 40 s. Don't go back to the plan's 1-minute window: a 30 s CPU fault would never fire.
- HTTP rules only look at `endpoint=~"/|/data"` (healthchecks are excluded) and need live traffic. With no requests the rate is NaN and nothing fires.
- A downstream fault makes alerts fire on the symptom service too (`api-service` latency → HighLatency on both; `api-service` down → ServiceDown on `api-service` plus HighErrorRate on `frontend`). Separating cause from symptom is the gateway's and LLM's job, using `upstream_request_duration_seconds`. Alertmanager only inhibits latency and error alerts for the *same* service when it is down.
- `send_resolved: true` is set for the verifier. Resolved notifications carry the annotation text from the last time the alert fired (old values), so don't read values from them.

Evaluation tooling:
- `load/locustfile.py` runs as the `load` service by default (`LOAD_USERS`, default 5, gives ~5 req/s). The HTTP alerts depend on it.
- `injector/injector.py` runs the 9 scenarios from §10 of the plan. HTTP faults go to each service's `/inject` and container stops use the Docker SDK. Each run appends a row to `experiments/ground_truth.csv` with `start`, `planned_end`, the actual `end` and an `end_reason`: `expired`, `remediated` (the fault was gone before `planned_end`, so the system fixed it; this is what MTTR and auto-resolve are scored on) or `cleanup` (the injector had to undo it). The `end` time comes from polling the target's `/health` fault flags or the container status. `MIN_DURATION` forces scenario 8 to at least 300 s so the ramp completes.
- The injector is a compose service under the `tools` profile, so `docker compose up` doesn't start it. Inside compose it uses service-name URLs and the mounted Docker socket. On the host it defaults to `localhost:5001/5002` (override with `FRONTEND_URL`, `API_SERVICE_URL`, `GROUND_TRUTH_PATH`).

## Commands

```bash
docker compose up --build            # full stack; check targets at localhost:9090/targets
docker compose config -q             # validate compose file
cd prometheus && promtool test rules rules_test.yml   # alert rule unit tests (fire + no-false-positive cases)
promtool check rules prometheus/rules.yml
amtool check-config alertmanager/alertmanager.yml

curl localhost:5001/                   # full request path
curl -X POST localhost:5002/inject -H 'Content-Type: application/json' -d '{"fault":"latency","duration":30}'
curl -X POST localhost:5002/reset
docker stop redis                      # dependency-failure scenario

docker compose run --rm injector list                                   # scenarios 1-9
docker compose run --rm injector run 4 --duration 180                   # one scenario
docker compose run --rm injector suite --scenarios 1-9 --repeat 3 --shuffle --seed 1 --gap 60
docker compose run --rm injector reset                                  # clear faults, start stopped containers
pip install -r injector/requirements.txt && python injector/injector.py list   # or from the host
```

Apart from the rule tests there is no test suite, linter or git repo yet. Get `promtool` and `amtool` from the Prometheus and Alertmanager GitHub release tarballs; they aren't installed. To smoke-test the app without Docker, run `pip install flask prometheus-client`, then drive it with `app.app.test_client()`. Run each service in its own process: both register the same metric names in prometheus_client's global registry, so importing both into one process raises `DuplicateTimeseries`.

## Invariants to preserve

- **`fault_*_active` gauges are ground truth.** Use them only to score the evaluation. Never pass them to the ML detector, the LLM context or the alert rules; filter them out in the gateway and the detector.
- **Changing `rules.yml` means updating `rules_test.yml`.** Expected labels and annotation text are matched exactly.
- **Fault lifecycle in `app.py`:** each fault has a generation counter (`fault_generation`) under `state_lock`. Start a fault with `activate_fault()`. Workers loop while `is_current(name, gen)` is true and finish by calling `deactivate_fault(name, gen)`, so `/reset` stops them early and an old timer can't clear a newer fault. New fault types must follow this pattern and auto-clear after `duration`.
- **Route instrumentation:** decorate request-serving routes with `@instrumented("<endpoint>")`, below `@app.route`. It records `http_requests_total` and `http_request_duration_seconds` on every path, error paths included. The planned rules and the ML features depend on these metric names and on `upstream_request_duration_seconds`, which must be recorded in a `finally` block around every call to the next service.
- **The memory fault must touch its pages** (it fills with non-zero bytes). Otherwise cAdvisor won't see the memory usage rise.
- **The LLM never executes actions directly.** Every action passes through the policy validator: allowlisted action types, known targets, confidence ≥ 0.7, a 5-minute cooldown, at most 3 actions per incident, and approval for risky actions. YAML runbooks are the fallback when the LLM fails and also the "no LLM" baseline (B1).
- The demo targets a laptop running Docker Compose. Kubernetes is out of scope.
