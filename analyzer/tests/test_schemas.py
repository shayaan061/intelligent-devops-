"""ResponsePlan is strict; IncidentEvent is tolerant."""

import pytest
from pydantic import ValidationError

from conftest import load_sample
from schemas import Action, IncidentEvent, ResponsePlan

GOOD = {
    "incident_id": "inc-0001", "root_cause_service": "api-service", "incident_type": "latency_degradation",
    "severity": "high", "probable_cause": "slow handler", "evidence": ["p95 5 s"], "confidence": 0.84,
    "recommended_action": {"type": "reset_faults", "target": "api-service"},
    "fallback_action": {"type": "restart_container", "target": "api-service"},
    "explanation": "", "source": "llm", "model": "llama3.1:8b", "runbook": None, "fallback_reason": None,
    "attempt": 1, "latency_ms": 12.0, "created_at": "2026-10-06T10:00:20Z",
}


def make(**changes):
    return ResponsePlan.model_validate({**GOOD, **changes})


def test_good_plan():
    assert make().confidence == 0.84


@pytest.mark.parametrize("changes", [
    {"incident_type": "disk_full"},
    {"severity": "urgent"},
    {"root_cause_service": "postgres"},
    {"root_cause_service": "monitoring"},
    {"confidence": 1.5},
    {"confidence": -0.1},
    {"source": "gpt"},
    {"recommended_action": {"type": "shell", "target": "api-service"}},
    {"recommended_action": {"type": "restart_container", "target": "db"}},
    {"recommended_action": {"type": "reset_faults", "target": "redis"}},
    {"recommended_action": {"type": "restart_container", "target": None}},
    {"recommended_action": {"type": "restart_container", "target": "redis", "cmd": "rm -rf /"}},
    {"fallback_action": {"type": "reset_faults", "target": "redis"}},
    {"unexpected": 1},
    {"attempt": 0},
])
def test_bad_plans_rejected(changes):
    with pytest.raises(ValidationError):
        make(**changes)


def test_escalate_may_have_no_target():
    plan = make(root_cause_service=None, incident_type="unknown",
                recommended_action={"type": "escalate", "target": None}, fallback_action=None)
    assert plan.recommended_action.target is None


def test_action_reset_only_on_app_services():
    assert Action(type="reset_faults", target="frontend")
    assert Action(type="restart_container", target="redis")


def test_incident_event_tolerant():
    e = load_sample(7)
    e["new_gateway_field"] = {"anything": True}
    e["context"]["frontend"]["container"] = None
    e["context"]["frontend"]["trend"]["p95"] = [None] * 10
    e["alerts"][0]["threshold"] = None
    inc = IncidentEvent.model_validate(e)
    assert inc.ctx("frontend").up == 0
    assert inc.ctx("nonexistent").p95 is None


def test_incident_event_minimal():
    inc = IncidentEvent.model_validate({"incident_id": "inc-9"})
    assert inc.topology["api-service"] == ["redis"]
    assert inc.history.attempt == 1
