"""Scorer tests on synthetic ground truth + incident store.

Run:  pip install pyyaml pytest && pytest -q experiments/tests
"""

import csv
import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import score  # noqa: E402

POLICIES = os.path.join(os.path.dirname(__file__), "..", "..", "responder", "policies.yaml")

SCHEMA = """CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, channel TEXT NOT NULL,
            type TEXT, incident_id TEXT, status TEXT, body TEXT NOT NULL)"""


def t(sec):
    """Seconds after 10:00:00 -> ISO."""
    m, s = divmod(sec, 60)
    return f"2026-10-06T10:{m:02d}:{s:02d}Z"


def gt_row(run_id, scenario, root, action, start, end, reason="remediated"):
    return {"run_id": run_id, "scenario": str(scenario), "name": f"s{scenario}", "fault": "x",
            "target_service": root, "expected_root_cause": root, "expected_action": action,
            "start": t(start), "planned_end": t(start + 180), "end": t(end), "end_reason": reason, "params": ""}


def incident(iid, opened, alert_at, status="open", resolved=None):
    return ("incident", iid, {"type": "incident", "incident_id": iid, "status": status, "opened_at": t(opened),
                              "resolved_at": t(resolved) if resolved else None,
                              "alerts": [{"name": "HighLatency", "service": "api-service", "startsAt": t(alert_at)}],
                              "ml_anomalies": []})


def plan(iid, root, a_type, target, attempt=1, source="runbook", latency=5.0):
    return ("response_plan", iid, {"type": "response_plan", "incident_id": iid, "root_cause_service": root,
                                   "recommended_action": {"type": a_type, "target": target}, "attempt": attempt,
                                   "source": source, "latency_ms": latency})


def action(iid, status, a_type, target):
    return ("action", iid, {"type": "action", "incident_id": iid, "status": status,
                            "action": {"type": a_type, "target": target}})


@pytest.fixture
def world(tmp_path):
    def build(runs, messages):
        gt = tmp_path / "gt.csv"
        with open(gt, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(runs[0]))
            w.writeheader()
            w.writerows(runs)
        db = tmp_path / "inc.db"
        con = sqlite3.connect(db)
        con.execute(SCHEMA)
        for type_, iid, body in messages:
            con.execute("INSERT INTO messages (at, channel, type, incident_id, status, body) VALUES (?,?,?,?,?,?)",
                        ("x", "c", type_, iid, body.get("status"), json.dumps(body)))
        con.commit()
        con.close()
        return score.score(str(gt), str(db), POLICIES)
    return build


def test_good_run_scores_everything(world):
    rows, s = world([gt_row("r1", 4, "api-service", "reset_faults", 0, 50)],
                    [incident("i1", 45, 40), plan("i1", "api-service", "reset_faults", "api-service"),
                     action("i1", "executed", "reset_faults", "api-service"),
                     action("i1", "verified", "reset_faults", "api-service")])
    r = rows[0]
    assert r["detected"] and r["mttd_s"] == 40 and r["mttr_s"] == 50
    assert r["root_cause_ok"] and r["plan_action_ok"] and r["executed_action_ok"] and r["verified"]
    assert s["recall_pct"] == 100 and s["unsafe_actions_executed"] == 0 and s["auto_resolved_pct"] == 100


def test_symptom_as_root_cause_is_wrong(world):
    rows, s = world([gt_row("r1", 4, "api-service", "reset_faults", 0, 180, "expired")],
                    [incident("i1", 45, 40), plan("i1", "frontend", "reset_faults", "frontend"),
                     action("i1", "executed", "reset_faults", "frontend")])
    r = rows[0]
    assert not r["root_cause_ok"] and not r["executed_action_ok"]
    assert r["collateral_executed"] == 1 and r["mttr_s"] is None and not r["auto_resolved"]
    assert s["root_cause_accuracy_pct"] == 0 and s["auto_resolved_pct"] == 0


def test_scenario_1_accepts_reset_or_restart(world):
    rows, _ = world([gt_row("r1", 1, "frontend", "reset_faults", 0, 60)],
                    [incident("i1", 45, 40), plan("i1", "frontend", "restart_container", "frontend")])
    assert rows[0]["plan_action_ok"]


def test_undetected_run_and_false_positive(world):
    runs = [gt_row("r1", 4, "api-service", "reset_faults", 0, 180, "expired"),
            gt_row("r2", 5, "api-service", "reset_faults", 300, 350)]
    # i1 opens between runs (no fault behind it); i2 belongs to r2
    rows, s = world(runs, [incident("i1", 250, 245), incident("i2", 340, 335)])
    assert [r["detected"] for r in rows] == [False, True]
    assert rows[1]["incident_id"] == "i2"
    assert s["recall_pct"] == 50 and s["false_positive_incidents"] == 1 and s["precision_pct"] == 50


def test_incident_from_before_the_run_is_not_matched(world):
    rows, _ = world([gt_row("r1", 4, "api-service", "reset_faults", 100, 150)], [incident("old", 90, 85)])
    assert rows[0]["detected"] is False


def test_unsafe_action_is_counted(world):
    _, s = world([gt_row("r1", 6, "redis", "restart_container", 0, 50)],
                 [incident("i1", 45, 40), action("i1", "executed", "reset_faults", "redis")])
    assert s["unsafe_actions_executed"] == 1


def test_attempts_sources_and_escalation(world):
    rows, s = world([gt_row("r1", 4, "api-service", "reset_faults", 0, 180, "expired")],
                    [incident("i1", 45, 40),
                     plan("i1", "api-service", "reset_faults", "api-service", 1, "llm", 900.0),
                     plan("i1", "api-service", "restart_container", "api-service", 2, "runbook", 5.0),
                     action("i1", "executed", "reset_faults", "api-service"),
                     action("i1", "escalated", "escalate", "api-service")])
    r = rows[0]
    assert r["attempts"] == 2 and r["escalated"] and r["plan_source"] == "llm"
    assert s["llm_plans_pct"] == 100 and s["plan_latency_ms"]["mean"] == 900.0


def test_plans_without_incident_message_are_ignored(world):
    rows, s = world([gt_row("r1", 4, "api-service", "reset_faults", 0, 50)],
                    [plan("demo", "redis", "flush_cache", "redis")])
    assert not rows[0]["detected"] and s["false_positive_incidents"] == 0


def test_since_filter(world, tmp_path):
    world([gt_row("r1", 4, "api-service", "reset_faults", 0, 50),
           gt_row("r2", 5, "api-service", "reset_faults", 300, 350)], [])
    rows, _ = score.score(str(tmp_path / "gt.csv"), str(tmp_path / "inc.db"), POLICIES, since=score.ts(t(200)))
    assert [r["run_id"] for r in rows] == ["r2"]
