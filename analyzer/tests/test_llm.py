"""LLM path with a mocked Ollama: good answers become plans with our metadata;
every failure falls back to the runbooks with the right fallback_reason."""

import json

import httpx
import pytest

import llm
from analyzer import analyze
from conftest import load_sample

GOOD_ANSWER = {
    "root_cause_service": "api-service", "incident_type": "latency_degradation", "severity": "high",
    "probable_cause": "api-service handler delayed", "evidence": ["api-service p95 5.0 s"],
    "confidence": 0.84, "recommended_action": {"type": "reset_faults", "target": "api-service"},
    "fallback_action": {"type": "restart_container", "target": "api-service"}, "explanation": "reset it",
}


def client_returning(content=None, status=200, exc=None, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(json.loads(request.content))
        if exc is not None:
            raise exc
        if isinstance(content, dict):
            body = {"message": {"role": "assistant", "content": json.dumps(content)}}
        else:
            body = {"message": {"role": "assistant", "content": content}}
        return httpx.Response(status, json=body)
    return httpx.Client(transport=httpx.MockTransport(handler))


def run(client, n=4):
    return analyze(load_sample(n), "llm", client=client)


def test_good_answer_becomes_llm_plan():
    answer = {**GOOD_ANSWER, "incident_id": "inc-9999", "source": "runbook", "model": "gpt", "latency_ms": -5}
    plan = run(client_returning(answer))
    assert plan.source == "llm"
    assert plan.model == llm.OLLAMA_MODEL
    assert plan.incident_id == "inc-0004"          # ours, not the model's
    assert plan.fallback_reason is None and plan.runbook is None
    assert plan.recommended_action.type == "reset_faults"
    assert plan.latency_ms >= 0


def test_request_shape_and_no_ground_truth():
    seen = []
    e = load_sample(4)
    e["context"]["api-service"]["fault_latency_active"] = 1
    e["context"]["api-service"]["trend"]["fault_latency_active"] = [0, 1]
    analyze(e, "llm", client=client_returning(GOOD_ANSWER, seen=seen))
    body = seen[0]
    assert body["stream"] is False
    assert body["options"]["temperature"] == 0
    assert body["format"] == llm.OUTPUT_SCHEMA
    assert body["model"] == llm.OLLAMA_MODEL
    assert "fault_" not in json.dumps(body["messages"][1])
    assert "inc-0004" in body["messages"][1]["content"]


@pytest.mark.parametrize("client_kwargs, reason", [
    ({"exc": httpx.ConnectError("refused")}, "unreachable"),
    ({"exc": httpx.ReadTimeout("slow")}, "timeout"),
    ({"content": "", "status": 500}, "http_500"),
    ({"content": "I think it is api-service"}, "invalid_json"),
    ({"content": "[1, 2]"}, "invalid_json"),
    ({"content": {**GOOD_ANSWER, "incident_type": "network_partition"}}, "schema_error"),
    ({"content": {**GOOD_ANSWER, "confidence": 84}}, "schema_error"),
    ({"content": {k: v for k, v in GOOD_ANSWER.items() if k != "severity"}}, "schema_error"),
    ({"content": {**GOOD_ANSWER, "confidence": 0.55}}, "low_confidence"),
])
def test_failures_fall_back_to_runbook(client_kwargs, reason):
    plan = run(client_returning(**client_kwargs))
    assert plan.source == "runbook"
    assert plan.model is None
    assert plan.fallback_reason == reason
    assert plan.runbook == "high-latency"
    assert (plan.root_cause_service, plan.recommended_action.type) == ("api-service", "reset_faults")


@pytest.mark.parametrize("bad_action", [
    {"type": "reset_faults", "target": "redis"},
    {"type": "run_shell", "target": "api-service"},
    {"type": "restart_container", "target": "postgres"},
    {"type": "restart_container", "target": None},
])
def test_invalid_actions_fall_back(bad_action):
    plan = run(client_returning({**GOOD_ANSWER, "recommended_action": bad_action}), n=6)
    assert plan.source == "runbook"
    assert plan.fallback_reason.startswith("invalid_action")
    assert plan.recommended_action.target == "redis"
    assert plan.recommended_action.type == "restart_container"


def test_reset_on_redis_reason_is_specific():
    answer = {**GOOD_ANSWER, "root_cause_service": "redis",
              "recommended_action": {"type": "reset_faults", "target": "redis"}}
    plan = run(client_returning(answer), n=6)
    assert plan.fallback_reason == "invalid_action: recommended_action reset_faults on redis"


def test_bad_ollama_body():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"done": True})))
    assert run(client).fallback_reason == "bad_response"


def test_escalate_with_null_target_accepted():
    answer = {**GOOD_ANSWER, "root_cause_service": None, "incident_type": "unknown",
              "recommended_action": {"type": "escalate", "target": None}, "fallback_action": None}
    plan = run(client_returning(answer))
    assert plan.source == "llm" and plan.recommended_action.type == "escalate"


def test_runbook_mode_never_calls_llm():
    def boom(request):
        raise AssertionError("LLM called in runbook mode")
    client = httpx.Client(transport=httpx.MockTransport(boom))
    plan = analyze(load_sample(4), "runbook", client=client)
    assert plan.source == "runbook" and plan.fallback_reason == "mode=runbook"


def test_bad_mode_rejected():
    with pytest.raises(ValueError):
        analyze(load_sample(4), "claude")


def test_prompt_mentions_rules():
    from schemas import IncidentEvent
    msgs = llm.build_messages(IncidentEvent.model_validate(load_sample(6)))
    system = msgs[0]["content"]
    for word in ("reset_faults", "restart_container", "escalate", "upstream_p95", "NEVER on redis"):
        assert word in system
