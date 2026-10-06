"""Runbook engine: §10 expected root cause and action for every sample,
plus the cause-vs-symptom and retry rules."""

import copy

import pytest

from conftest import load_sample
from runbooks import load_runbooks, run_runbooks
from schemas import IncidentEvent

# scenario -> (root cause, recommended action, incident type)   (SUGGESTED_PLAN.md §10)
EXPECTED = {
    1: ("frontend", "reset_faults", "cpu_saturation"),
    2: ("api-service", "reset_faults", "cpu_saturation"),
    3: ("api-service", "restart_container", "memory_pressure"),
    4: ("api-service", "reset_faults", "latency_degradation"),
    5: ("api-service", "reset_faults", "error_spike"),
    6: ("redis", "restart_container", "dependency_down"),
    7: ("frontend", "restart_container", "service_down"),
    8: ("api-service", "restart_container", "memory_pressure"),
    9: ("api-service", "reset_faults", "cpu_saturation"),
}


def plan_for(event, runbooks):
    return run_runbooks(IncidentEvent.model_validate(event), runbooks)


@pytest.mark.parametrize("n", sorted(EXPECTED))
def test_samples_match_section_10(n, runbooks):
    root, action, itype = EXPECTED[n]
    plan = plan_for(load_sample(n), runbooks)
    assert plan.root_cause_service == root
    assert plan.recommended_action.type == action
    assert plan.recommended_action.target == root
    assert plan.incident_type == itype
    assert plan.source == "runbook" and plan.model is None and plan.runbook
    assert plan.incident_id == f"inc-{n:04d}"


@pytest.mark.parametrize("n", [1, 2, 4, 5, 9])
def test_reset_scenarios_fall_back_to_restart(n, runbooks):
    plan = plan_for(load_sample(n), runbooks)
    assert plan.fallback_action.type == "restart_container"
    assert plan.fallback_action.target == plan.root_cause_service


def test_runbooks_load_sorted_and_cover_priorities(runbooks):
    names = [rb["name"] for rb in runbooks]
    assert names == ["monitoring-down", "dependency-down", "service-down", "high-memory",
                     "high-cpu", "high-error-rate", "high-latency", "ml-memory-anomaly"]


def test_redis_down_from_context_only(runbooks):
    """No RedisDown alert yet, but redis up == 0: still redis, not api-service."""
    e = load_sample(6)
    e["alerts"] = [a for a in e["alerts"] if a["name"] != "RedisDown"]
    plan = plan_for(e, runbooks)
    assert plan.root_cause_service == "redis"
    assert plan.recommended_action.type == "restart_container"


def test_api_service_down_beats_frontend_errors(runbooks):
    e = load_sample(5)
    e["alerts"] = [{"name": "ServiceDown", "service": "api-service", "status": "firing"},
                   {"name": "HighErrorRate", "service": "frontend", "status": "firing", "value": 1.0}]
    e["context"]["api-service"]["up"] = 0
    plan = plan_for(e, runbooks)
    assert (plan.root_cause_service, plan.recommended_action.type) == ("api-service", "restart_container")
    assert plan.incident_type == "service_down"


def test_memory_beats_cpu_and_latency(runbooks):
    e = load_sample(9)
    e["alerts"].append({"name": "HighMemory", "service": "api-service", "status": "firing", "value": 0.9})
    plan = plan_for(e, runbooks)
    assert plan.incident_type == "memory_pressure"
    assert plan.recommended_action.type == "restart_container"


def test_cpu_on_both_picks_deepest(runbooks):
    e = load_sample(2)
    e["alerts"].append({"name": "HighCPU", "service": "frontend", "status": "firing", "value": 0.9})
    assert plan_for(e, runbooks).root_cause_service == "api-service"


def test_latency_origin_in_frontend(runbooks):
    """frontend slow on its own (upstream fast) -> frontend, not api-service."""
    e = load_sample(4)
    e["alerts"] = [{"name": "HighLatency", "service": "frontend", "status": "firing", "value": 3.0}]
    e["context"]["frontend"].update(p95=3.0, upstream_p95=0.006)
    e["context"]["api-service"].update(p95=0.006, upstream_p95=0.002)
    assert plan_for(e, runbooks).root_cause_service == "frontend"


def test_latency_uses_context_when_only_frontend_alerted(runbooks):
    """Only frontend has fired yet, but api-service p95 explains it."""
    e = load_sample(4)
    e["alerts"] = [a for a in e["alerts"] if a["service"] == "frontend"]
    assert plan_for(e, runbooks).root_cause_service == "api-service"


def test_errors_with_frontend_only_own_errors(runbooks):
    e = load_sample(5)
    e["alerts"] = [{"name": "HighErrorRate", "service": "frontend", "status": "firing", "value": 0.5}]
    e["context"]["frontend"]["err"] = 0.5
    e["context"]["api-service"]["err"] = 0.0
    assert plan_for(e, runbooks).root_cause_service == "frontend"


def test_resolved_alerts_are_ignored(runbooks):
    e = load_sample(9)
    for a in e["alerts"]:
        if a["name"] == "HighCPU":
            a["status"] = "resolved"
    e["status"] = "updated"
    plan = plan_for(e, runbooks)
    assert plan.incident_type == "latency_degradation"
    assert plan.root_cause_service == "api-service"


def test_exporter_down_only_escalates_without_target(runbooks):
    e = load_sample(4)
    e["alerts"] = [{"name": "ExporterDown", "service": "monitoring", "status": "firing"}]
    plan = plan_for(e, runbooks)
    assert plan.recommended_action.type == "escalate"
    assert plan.recommended_action.target is None
    assert plan.root_cause_service is None
    assert plan.fallback_action is None
    assert plan.runbook == "monitoring-down"


def test_exporter_down_does_not_hide_app_alerts(runbooks):
    e = load_sample(3)
    e["alerts"].append({"name": "ExporterDown", "service": "monitoring", "status": "firing"})
    assert plan_for(e, runbooks).recommended_action.type == "restart_container"


def test_no_match_escalates_unknown(runbooks):
    e = load_sample(1)
    e["alerts"] = [{"name": "SomethingNew", "service": "api-service", "status": "firing"}]
    plan = plan_for(e, runbooks)
    assert plan.incident_type == "unknown"
    assert plan.recommended_action.type == "escalate"
    assert plan.recommended_action.target == "api-service"
    assert plan.runbook == "no-match"


def test_retry_skips_tried_actions(runbooks):
    e = load_sample(4)
    e["history"] = {"attempt": 2, "previous_actions": [{"type": "reset_faults", "target": "api-service"}]}
    plan = plan_for(e, runbooks)
    assert plan.attempt == 2
    assert plan.recommended_action.type == "restart_container"
    assert plan.fallback_action.type == "escalate"

    e["history"]["previous_actions"].append({"action": {"type": "restart_container", "target": "api-service"}})
    plan = plan_for(e, runbooks)
    assert plan.recommended_action.type == "escalate"
    assert plan.recommended_action.target == "api-service"


def test_null_values_everywhere(runbooks):
    e = load_sample(7)
    e["context"]["api-service"] = None
    e["context"]["redis"]["container"] = None
    plan = plan_for(e, runbooks)
    assert plan.root_cause_service == "frontend"


def test_ground_truth_is_stripped():
    e = load_sample(4)
    e["context"]["api-service"]["fault_latency_active"] = 1
    e["context"]["api-service"]["trend"]["fault_cpu_active"] = [1, 1]
    e["fault_summary"] = {"x": 1}
    inc = IncidentEvent.model_validate(e)
    dumped = inc.model_dump_json()
    assert "fault_" not in dumped


def test_bad_runbook_file_rejected(tmp_path):
    (tmp_path / "bad.yaml").write_text(
        "- name: x\n  priority: 1\n  match: {alert: HighCPU}\n  root_cause: matched_service\n"
        "  incident_type: cpu_saturation\n  severity: high\n  action: rm_rf\n  confidence: 0.8\n")
    with pytest.raises(ValueError, match="allowlist"):
        load_runbooks(tmp_path)
