"""Responder tests: policy validator, executor, execute/verify/re-analyze loop.

Run from responder/:  pip install -r requirements-dev.txt && pytest -q
The gateway and Prometheus are faked with httpx.MockTransport; no Docker.
"""

import asyncio
import json
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as rapp  # noqa: E402
from executor import Executor  # noqa: E402
from policy import APPROVAL, ESCALATE, EXECUTE, decide, load_policies  # noqa: E402

POLICY_FILE = os.path.join(os.path.dirname(__file__), "..", "policies.yaml")
P = load_policies(POLICY_FILE)


def plan(rec=("reset_faults", "api-service"), fb=("restart_container", "api-service"),
         confidence=0.85, attempt=1, incident_id="inc-1"):
    return {"type": "response_plan", "incident_id": incident_id, "root_cause_service": "api-service",
            "confidence": confidence, "attempt": attempt, "source": "runbook",
            "recommended_action": {"type": rec[0], "target": rec[1]} if rec else None,
            "fallback_action": {"type": fb[0], "target": fb[1]} if fb else None}


# -----------------------------
# Policy validator
# -----------------------------

def test_valid_confident_plan_executes():
    d = decide(plan(), P, 0, {}, 1000)
    assert d.kind == EXECUTE and d.action == {"type": "reset_faults", "target": "api-service"}


def test_unknown_action_type_falls_back():
    d = decide(plan(rec=("rm_rf", "api-service")), P, 0, {}, 1000)
    assert d.kind == EXECUTE and d.action["type"] == "restart_container"
    assert "not on the allowlist" in d.reasons[0]


def test_reset_on_redis_not_allowed_falls_back():
    d = decide(plan(rec=("reset_faults", "redis"), fb=("restart_container", "redis")), P, 0, {}, 1000)
    assert d.kind == EXECUTE and d.action == {"type": "restart_container", "target": "redis"}


def test_unknown_target_and_no_fallback_escalates():
    d = decide(plan(rec=("restart_container", "prometheus"), fb=None), P, 0, {}, 1000)
    assert d.kind == ESCALATE and d.action["type"] == "escalate"


def test_low_confidence_needs_approval():
    d = decide(plan(confidence=0.5), P, 0, {}, 1000)
    assert d.kind == APPROVAL and d.action["type"] == "reset_faults"


def test_missing_confidence_needs_approval():
    p = plan()
    del p["confidence"]
    assert decide(p, P, 0, {}, 1000).kind == APPROVAL


def test_risky_action_needs_approval_even_when_confident():
    d = decide(plan(rec=("flush_cache", "redis"), confidence=0.99), P, 0, {}, 1000)
    assert d.kind == APPROVAL and d.action["type"] == "flush_cache"


def test_cooldown_falls_back_then_escalates():
    last = {("reset_faults", "api-service"): 1000}
    d = decide(plan(), P, 0, last, 1100)
    assert d.kind == EXECUTE and d.action["type"] == "restart_container"
    last[("restart_container", "api-service")] = 1000
    assert decide(plan(), P, 0, last, 1100).kind == ESCALATE
    assert decide(plan(), P, 0, last, 1000 + P["cooldown_seconds"]).kind == EXECUTE


def test_max_actions_per_incident_escalates():
    d = decide(plan(), P, P["max_actions_per_incident"], {}, 1000)
    assert d.kind == ESCALATE and "max" in d.reasons[-1]


def test_escalate_plan_executes_nothing():
    d = decide(plan(rec=("escalate", None), fb=None), P, 0, {}, 1000)
    assert d.kind == ESCALATE and d.action == {"type": "escalate", "target": None}


def test_cooldown_env_override(monkeypatch):
    monkeypatch.setenv("COOLDOWN_SECONDS", "30")
    assert load_policies(POLICY_FILE)["cooldown_seconds"] == 30.0


# -----------------------------
# Executor
# -----------------------------

def run(coro):
    return asyncio.run(coro)


def test_executor_reset_posts_to_service():
    seen = []

    def handler(request):
        seen.append((request.method, str(request.url)))
        return httpx.Response(200, json={"status": "reset"})

    ex = Executor(P, transport=httpx.MockTransport(handler))
    assert run(ex.run({"type": "reset_faults", "target": "api-service"})) == (True, "faults reset")
    assert seen == [("POST", "http://localhost:5002/reset")]


def test_executor_refuses_what_policy_forbids():
    ex = Executor(P)
    assert run(ex.run({"type": "reset_faults", "target": "redis"}))[0] is False
    assert run(ex.run({"type": "escalate", "target": None}))[0] is False
    assert run(ex.run({"type": "shell", "target": "api-service"}))[0] is False


def test_executor_restart_without_docker_fails_cleanly():
    ok, detail = run(Executor(P).run({"type": "restart_container", "target": "frontend"}))
    assert ok is False and "docker socket not available" in detail


def test_executor_update_resources_not_implemented():
    ok, detail = run(Executor(P).run({"type": "update_resources", "target": "frontend"}))
    assert ok is False and "not implemented" in detail


# -----------------------------
# Execute -> verify -> re-analyze loop
# -----------------------------

class FakeExecutor(Executor):
    def __init__(self, world, ok=True):
        super().__init__(P)
        self.world = world
        self.ok = ok
        self.calls = []

    async def run(self, action):
        self.calls.append((action["type"], action["target"]))
        if self.ok and self.world.fixed_by_action:
            self.world.still_firing = False
        return self.ok, "done" if self.ok else "boom"


class FakeWorld:
    """The gateway and Prometheus, as seen through HTTP."""

    def __init__(self):
        self.firing = ["HighLatency/api-service"]
        self.still_firing = True      # what Prometheus ALERTS returns now
        self.fixed_by_action = False  # does executing clear the alerts
        self.reports = []
        self.reanalyze = []
        self.resolved_at = None

    def handler(self, request):
        path = request.url.path
        if path == "/actions":
            self.reports.append(json.loads(request.content))
            return httpx.Response(200, json={"accepted": True})
        if path.endswith("/reanalyze"):
            self.reanalyze.append(json.loads(request.content)["attempt"])
            return httpx.Response(200, json={})
        if path == "/incidents":
            return httpx.Response(200, json=[{"incident_id": "inc-1", "opened_at": "2026-10-06T10:00:00Z",
                                              "resolved_at": self.resolved_at, "firing": self.firing}])
        if path == "/api/v1/query":
            result = [{"metric": {}, "value": [0, "1"]}] if self.still_firing else []
            return httpx.Response(200, json={"status": "success", "data": {"result": result}})
        return httpx.Response(404)

    def statuses(self):
        return [r["status"] for r in self.reports]


async def no_sleep(_):
    return None


def make(ok=True):
    world = FakeWorld()
    ex = FakeExecutor(world, ok)
    r = rapp.Responder(P, ex, clock=lambda: 1_791_000_000.0, sleep=no_sleep,
                       transport=httpx.MockTransport(world.handler))
    return r, ex, world


def test_fix_verified_closes_incident():
    r, ex, world = make()
    world.fixed_by_action = True
    assert run(r.handle_plan(plan())) == EXECUTE
    assert ex.calls == [("reset_faults", "api-service")]
    assert world.statuses() == ["executed", "verified"]
    assert world.reports[-1]["open_to_verified_s"] is not None
    assert run(r.handle_plan(plan())).startswith("skipped")


def test_unresolved_triggers_reanalysis_then_next_attempt():
    r, ex, world = make()
    run(r.handle_plan(plan()))
    assert world.statuses() == ["executed", "unresolved"]
    assert world.reanalyze == [2]
    # A late plan from attempt 1 (e.g. an "updated" incident) is ignored
    assert run(r.handle_plan(plan())).startswith("skipped: stale")
    world.fixed_by_action = True
    run(r.handle_plan(plan(rec=("restart_container", "api-service"), fb=None, attempt=2)))
    assert ex.calls == [("reset_faults", "api-service"), ("restart_container", "api-service")]
    assert world.statuses()[-1] == "verified"


def test_escalates_after_max_attempts():
    r, ex, world = make()
    run(r.handle_plan(plan(attempt=3)))
    assert world.statuses() == ["executed", "escalated"]
    assert world.reanalyze == []
    assert r.state("inc-1").done


def test_failed_execution_reanalyzes_without_waiting():
    r, ex, world = make(ok=False)
    slept = []

    async def sleep(s):
        slept.append(s)

    r.sleep = sleep
    run(r.handle_plan(plan()))
    assert world.statuses() == ["failed", "unresolved"] and slept == [] and world.reanalyze == [2]


def test_already_cleared_alerts_skip_the_action():
    r, ex, world = make()
    world.still_firing = False  # fault gone before the plan arrived
    run(r.handle_plan(plan()))
    assert ex.calls == [] and world.statuses() == ["skipped"]
    assert r.last_run == {} and not r.state("inc-1").done and not r.state("inc-1").busy


def test_resolved_incident_skips_the_action():
    r, ex, world = make()
    world.resolved_at = "2026-10-06T10:01:00Z"
    run(r.handle_plan(plan()))
    assert ex.calls == [] and world.statuses() == ["skipped"]


def test_unreachable_prometheus_still_executes():
    r, ex, world = make()
    handler = world.handler

    def broken(request):
        if request.url.path == "/api/v1/query":
            return httpx.Response(500)
        return handler(request)

    r.transport = httpx.MockTransport(broken)
    run(r.handle_plan(plan()))
    assert ex.calls == [("reset_faults", "api-service")]
    assert world.statuses() == ["executed", "unresolved"]


def test_plan_while_busy_is_skipped():
    async def scenario():
        r, ex, world = make()
        gate = asyncio.Event()

        async def sleep(_):
            await gate.wait()

        r.sleep = sleep
        world.fixed_by_action = True
        first = asyncio.create_task(r.handle_plan(plan()))
        await asyncio.sleep(0.01)
        second = await r.handle_plan(plan())
        gate.set()
        await first
        return second, ex.calls

    second, calls = run(scenario())
    assert second.startswith("skipped: an action") and calls == [("reset_faults", "api-service")]


def test_approval_flow_approve():
    async def scenario():
        r, ex, world = make()
        world.fixed_by_action = True
        assert await r.handle_plan(plan(confidence=0.4)) == "pending approval"
        assert (await r.handle_plan(plan(confidence=0.9))).startswith("skipped")  # waiting for a human
        (approval_id,) = r.approvals
        assert await r.approve(approval_id) == "executing"
        await asyncio.gather(*r.tasks)
        return ex.calls, world.statuses(), r.state("inc-1")

    calls, statuses, st = run(scenario())
    assert calls == [("reset_faults", "api-service")]
    assert statuses == ["pending_approval", "approved", "executed", "verified"]
    assert st.done and not st.busy


def test_approval_flow_reject():
    r, ex, world = make()
    run(r.handle_plan(plan(rec=("flush_cache", "redis"), fb=None)))
    (approval_id,) = r.approvals
    assert run(r.reject(approval_id)) == "rejected"
    assert ex.calls == [] and world.statuses() == ["pending_approval", "rejected"]
    assert run(r.reject(approval_id)) is None


def test_approved_action_still_respects_cooldown():
    async def scenario():
        r, ex, world = make()
        await r.handle_plan(plan(confidence=0.4, incident_id="inc-1"))
        r.last_run[("reset_faults", "api-service")] = r.clock()  # ran elsewhere meanwhile
        (approval_id,) = r.approvals
        return await r.approve(approval_id), ex.calls

    result, calls = run(scenario())
    assert result == "escalated" and calls == []


def test_dry_run_never_executes(monkeypatch):
    monkeypatch.setattr(rapp, "MODE", "dry_run")
    r, ex, world = make()
    run(r.handle_plan(plan()))
    assert ex.calls == [] and world.statuses() == ["dry_run"]


def test_cors_allows_only_the_dashboard_origin():
    from fastapi.testclient import TestClient
    c = TestClient(rapp.app)  # no `with`: lifespan (WebSocket consumer) not started
    ok = c.get("/approvals", headers={"Origin": "http://localhost:8000"})
    assert ok.status_code == 200 and ok.headers.get("access-control-allow-origin") == "http://localhost:8000"
    evil = c.get("/approvals", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in evil.headers


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "0.99", 1.5, -0.1, None])
def test_invalid_confidence_needs_approval(bad):
    assert decide(plan(confidence=bad), P, 0, {}, 1000).kind == APPROVAL


@pytest.mark.parametrize("action", [{"type": ["restart_container"], "target": "api-service"},
                                    {"type": "restart_container", "target": ["api-service"]}])
def test_malformed_action_is_skipped_not_crashing(action):
    p = plan(fb=None)
    p["recommended_action"] = action
    assert decide(p, P, 0, {}, 1000).kind == ESCALATE


@pytest.mark.parametrize("attempt", ["1", -1, 0, True, 1.5])
def test_malformed_attempt_is_ignored(attempt):
    r, ex, world = make()
    assert run(r.handle_plan(plan(attempt=attempt))).startswith("ignored")
    assert ex.calls == []
