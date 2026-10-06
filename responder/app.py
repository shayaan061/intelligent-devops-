"""Response System + Verifier (SUGGESTED_PLAN.md §6.5, §6.6).

Listens to ResponsePlans on the gateway's /ws/responses, runs each through
the policy validator (policy.py) and then:
  execute   -> executor.py, then verify
  approval  -> queued for a human: GET /approvals, POST /approvals/{id}/approve|reject
  escalate  -> recorded, nothing runs (optional ESCALATION_WEBHOOK)

Pre-check: right before executing, the incident's alerts are re-checked;
if they have already cleared the action is skipped ("skipped"), so a late
plan never restarts a healthy service.

Verifier: verify_delay_seconds after an action, the incident's alerts are
re-checked in Prometheus (ALERTS, pending or firing). Resolved -> "verified"
with the time since the incident opened. Not resolved -> the gateway re-sends
the incident with attempt + 1 and the actions already tried, so the analyzer
proposes something else. After max_attempts -> escalate.

One plan per incident at a time: while an action is running, being verified
or waiting for approval, further plans for that incident are skipped, and
plans from an earlier attempt are ignored (an "updated" incident can arrive
while a fix is being verified).

Every outcome is POSTed to the gateway's /actions (broadcast on
/ws/responses as type "action") and kept in GET /actions.

RESPONDER_MODE=auto (default) or dry_run (validate and report, never
execute: alerts-only baseline B0).

Usage:
  uvicorn app:app --host 0.0.0.0 --port 8001
"""

import asyncio
import itertools
import json
import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from executor import Executor
from policy import APPROVAL, ESCALATE, EXECUTE, action_key, decide, load_policies

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8000")
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
POLICY_FILE = os.environ.get("POLICY_FILE", os.path.join(os.path.dirname(__file__), "policies.yaml"))
MODE = os.environ.get("RESPONDER_MODE", "auto")
ESCALATION_WEBHOOK = os.environ.get("ESCALATION_WEBHOOK")
# The dashboard (served by the gateway) calls /approvals from this origin
DASHBOARD_ORIGINS = os.environ.get("DASHBOARD_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("responder")

POLICIES = load_policies(POLICY_FILE)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


class IncidentState:
    def __init__(self):
        self.next_attempt = 1
        self.busy = False       # executing, verifying or awaiting approval
        self.executed = 0       # actions run for this incident
        self.done = False       # verified, escalated or handed to a human


class Responder:
    def __init__(self, policies, executor, clock=time.time, sleep=asyncio.sleep, transport=None):
        self.policies = policies
        self.executor = executor
        self.clock = clock
        self.sleep = sleep
        self.transport = transport      # tests inject httpx.MockTransport
        self.incidents = {}             # incident_id -> IncidentState
        self.last_run = {}              # (type, target) -> time, across incidents (cooldown)
        self.approvals = {}             # approval_id -> pending approval
        self.records = deque(maxlen=200)
        self._ids = itertools.count(1)
        self.tasks = set()              # approved actions running in the background

    def state(self, incident_id):
        return self.incidents.setdefault(incident_id, IncidentState())

    def client(self):
        return httpx.AsyncClient(timeout=10, transport=self.transport)

    # -----------------------------
    # Reporting
    # -----------------------------

    async def report(self, plan, status, action=None, reason=None, **extra):
        rec = {"incident_id": plan["incident_id"], "status": status, "action": action,
               "attempt": plan.get("attempt", 1), "plan_source": plan.get("source"),
               "reason": reason, "at": now_iso(), **extra}
        self.records.append(rec)
        log.info("%s %s %s %s", rec["incident_id"], status,
                 f'{action["type"]}/{action["target"]}' if action else "-", reason or "")
        try:
            async with self.client() as c:
                await c.post(f"{GATEWAY_URL}/actions", json=rec)
        except Exception as e:
            log.warning("could not report to gateway: %s", e)
        return rec

    async def escalate(self, plan, st, action, reason):
        st.done = True
        await self.report(plan, "escalated", action, reason)
        if ESCALATION_WEBHOOK:
            text = f"Incident {plan['incident_id']} escalated: {reason}"
            try:
                async with self.client() as c:
                    await c.post(ESCALATION_WEBHOOK, json={"text": text, "content": text})
            except Exception as e:
                log.warning("escalation webhook failed: %s", e)

    # -----------------------------
    # Plans
    # -----------------------------

    async def handle_plan(self, plan):
        incident_id = plan.get("incident_id")
        if not incident_id or not isinstance(incident_id, str):
            return "ignored: no incident_id"
        attempt = plan.get("attempt", 1)
        # Plans can reach /ws/responses without the analyzer's schema check
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
            return f"ignored: malformed attempt {attempt!r}"
        st = self.state(incident_id)
        if st.done:
            return "skipped: incident already handled"
        if st.busy:
            return "skipped: an action for this incident is in progress"
        if attempt < st.next_attempt:
            return f"skipped: stale attempt {attempt} < {st.next_attempt}"

        st.busy = True  # set before any await: plans arrive concurrently
        try:
            d = decide(plan, self.policies, st.executed, self.last_run, self.clock())
            reason = "; ".join(d.reasons)
            if MODE == "dry_run":
                await self.report(plan, "dry_run", d.action, f"{d.kind}: {reason}")
                st.done = True
            elif d.kind == ESCALATE:
                await self.escalate(plan, st, d.action, reason)
            elif d.kind == APPROVAL:
                approval_id = f"apr-{next(self._ids)}"
                self.approvals[approval_id] = {"approval_id": approval_id, "plan": plan,
                                               "action": d.action, "reason": reason, "created_at": now_iso()}
                await self.report(plan, "pending_approval", d.action, reason, approval_id=approval_id)
                return "pending approval"  # stays busy until a human decides
            elif d.kind == EXECUTE:
                await self.execute_and_verify(plan, st, d.action, reason)
            st.busy = False
            return d.kind
        except Exception:
            st.busy = False
            raise

    async def execute_and_verify(self, plan, st, action, reason):
        # Alerts trail the fault by up to a 30 s rate window, so a plan can
        # arrive after the fault is already gone. Don't touch a healthy service.
        cleared, why = await self.check_resolved(plan["incident_id"])
        if cleared:
            await self.report(plan, "skipped", action, f"not executed, already cleared: {why}")
            return
        self.last_run[action_key(action)] = self.clock()
        st.executed += 1
        ok, detail = await self.executor.run(action)
        await self.report(plan, "executed" if ok else "failed", action, reason, detail=detail)

        resolved, why = False, detail
        if ok:
            await self.sleep(self.policies["verify_delay_seconds"])
            resolved, why = await self.check_resolved(plan["incident_id"])

        if resolved:
            st.done = True
            await self.report(plan, "verified", action, why, mttr_seconds=await self.time_open(plan["incident_id"]))
            return

        attempt = plan.get("attempt", 1)
        if attempt >= self.policies["max_attempts"]:
            await self.escalate(plan, st, {"type": "escalate", "target": action["target"]},
                                f"not resolved after {attempt} attempts ({why})")
            return
        st.next_attempt = attempt + 1
        await self.report(plan, "unresolved", action, why)
        await self.request_reanalysis(plan, st, st.next_attempt)

    async def request_reanalysis(self, plan, st, attempt):
        try:
            async with self.client() as c:
                r = await c.post(f"{GATEWAY_URL}/incidents/{plan['incident_id']}/reanalyze", json={"attempt": attempt})
        except Exception as e:
            await self.escalate(plan, st, None, f"re-analysis request failed: {e}")
            return
        if r.status_code == 409:  # resolved meanwhile
            st.done = True
            await self.report(plan, "verified", None, "incident resolved before re-analysis")
        elif r.status_code >= 300:
            await self.escalate(plan, st, None, f"re-analysis request -> {r.status_code}")

    # -----------------------------
    # Verification
    # -----------------------------

    async def incident_summary(self, incident_id):
        async with self.client() as c:
            r = await c.get(f"{GATEWAY_URL}/incidents")
            r.raise_for_status()
        return next((i for i in r.json() if i["incident_id"] == incident_id), None)

    async def check_resolved(self, incident_id):
        """(resolved, reason). Re-checks the alerts that were firing (§6.6)."""
        try:
            summary = await self.incident_summary(incident_id)
            if summary is None:
                return False, "incident unknown to the gateway"
            if summary["resolved_at"]:
                return True, "incident resolved"
            still = []
            async with self.client() as c:
                for item in summary["firing"]:
                    name, service = item.split("/", 1)
                    q = f'ALERTS{{alertname="{name}", service="{service}"}}'
                    r = await c.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": q})
                    r.raise_for_status()
                    if r.json()["data"]["result"]:
                        still.append(item)
        except Exception as e:
            return False, f"verification failed: {e.__class__.__name__}"
        if still:
            return False, "still firing: " + ", ".join(still)
        return True, "alerts no longer firing"

    async def time_open(self, incident_id):
        try:
            summary = await self.incident_summary(incident_id)
            opened = parse_iso(summary["opened_at"]) if summary else None
        except Exception:
            opened = None
        return round(self.clock() - opened, 1) if opened else None

    # -----------------------------
    # Human approval
    # -----------------------------

    async def approve(self, approval_id):
        pending = self.approvals.pop(approval_id, None)
        if pending is None:
            return None
        plan, action = pending["plan"], pending["action"]
        st = self.state(plan["incident_id"])
        # A human overrides confidence and requires_approval, not the hard limits
        problem = None
        if not self.executor.allowed(action):
            problem = "not on the allowlist"
        elif st.executed >= self.policies["max_actions_per_incident"]:
            problem = "max actions per incident reached"
        elif self.clock() - self.last_run.get(action_key(action), float("-inf")) < self.policies["cooldown_seconds"]:
            problem = "in cooldown"
        if problem:
            await self.escalate(plan, st, action, f"approved but refused: {problem}")
            st.busy = False
            return "escalated"
        await self.report(plan, "approved", action, "approved by a human")
        # Verification takes verify_delay_seconds; don't hold the HTTP request
        task = asyncio.create_task(self._run_approved(plan, st, action))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return "executing"

    async def _run_approved(self, plan, st, action):
        try:
            await self.execute_and_verify(plan, st, action, "approved by a human")
        finally:
            st.busy = False

    async def reject(self, approval_id):
        pending = self.approvals.pop(approval_id, None)
        if pending is None:
            return None
        plan = pending["plan"]
        st = self.state(plan["incident_id"])
        st.done, st.busy = True, False  # a human owns it now
        await self.report(plan, "rejected", pending["action"], "rejected by a human")
        return "rejected"


# -----------------------------
# Service
# -----------------------------

def docker_or_none():
    try:
        import docker
        client = docker.from_env()
        client.ping()
        return client
    except Exception as e:
        log.warning("docker unavailable: restart/flush will fail (%s)", e.__class__.__name__)
        return None


responder = Responder(POLICIES, Executor(POLICIES))


async def consume():
    """Read plans from the gateway's /ws/responses, reconnecting with backoff."""
    from websockets.asyncio.client import connect

    url = GATEWAY_URL.replace("http", "ws", 1) + "/ws/responses"
    delay = 1
    while True:
        try:
            async with connect(url) as ws:
                log.info("connected to %s", url)
                delay = 1
                async for text in ws:
                    try:
                        # NaN/Infinity aren't JSON and would break /approvals responses
                        msg = json.loads(text, parse_constant=_reject_constant)
                    except ValueError:
                        log.warning("skipped a message that is not valid JSON")
                        continue
                    if msg.get("type") != "response_plan" or msg.get("replay"):
                        continue
                    task = asyncio.create_task(responder.handle_plan(msg))
                    task.add_done_callback(_log_result(msg.get("incident_id")))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("%s: %s; retrying in %ds", url, e, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)


def _reject_constant(name):
    raise ValueError(f"{name} is not valid JSON")


def _log_result(incident_id):
    def done(task):
        if task.cancelled():
            return
        if task.exception():
            log.error("plan for %s crashed: %r", incident_id, task.exception())
        elif str(task.result()).startswith("skipped"):
            log.info("%s %s", incident_id, task.result())
    return done


@asynccontextmanager
async def lifespan(_app):
    responder.executor.docker = await asyncio.to_thread(docker_or_none)
    log.info("mode=%s gateway=%s cooldown=%ss verify_delay=%ss", MODE, GATEWAY_URL,
             POLICIES["cooldown_seconds"], POLICIES["verify_delay_seconds"])
    task = asyncio.create_task(consume())
    yield
    task.cancel()


app = FastAPI(title="Responder", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=DASHBOARD_ORIGINS, allow_methods=["GET", "POST"])


@app.get("/health")
async def health():
    return {"status": "ok", "mode": MODE, "docker": responder.executor.docker is not None,
            "pending_approvals": len(responder.approvals)}


@app.get("/actions")
async def actions():
    return list(responder.records)


@app.get("/approvals")
async def approvals():
    return list(responder.approvals.values())


@app.post("/approvals/{approval_id}/approve")
async def approve(approval_id: str):
    result = await responder.approve(approval_id)
    if result is None:
        return JSONResponse({"error": "unknown approval"}, status_code=404)
    return {"result": result}


@app.post("/approvals/{approval_id}/reject")
async def reject(approval_id: str):
    result = await responder.reject(approval_id)
    if result is None:
        return JSONResponse({"error": "unknown approval"}, status_code=404)
    return {"result": result}
