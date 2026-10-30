"""Evaluation runner: run order, resume, void, per-system scoring selection,
suites, the SF switch and the soak report (no Docker: stack control is faked).

Run:  pytest -q experiments/tests
"""

import csv
import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import run_eval  # noqa: E402


@pytest.fixture
def evaldir(tmp_path, monkeypatch):
    monkeypatch.setattr(run_eval, "EVAL_DIR", str(tmp_path))
    monkeypatch.setattr(run_eval, "SUITE", "core")
    monkeypatch.setattr(run_eval, "LOG_PATH", str(tmp_path / "run_eval.log"))
    return tmp_path


def done(system, rnd, sid, run_id=None, ended="2026-10-12T10:00:00Z"):
    run_eval.append_manifest({"system": system, "round": rnd, "slot": 1, "scenario": sid,
                              "run_id": run_id or f"{system}{rnd}{sid}", "status": "done",
                              "started": "2026-10-12T09:58:00Z", "ended": ended})


def test_order_is_a_fixed_shuffle():
    o = run_eval.order("B1", 1)
    assert sorted(o) == list(range(1, 10))
    assert o == run_eval.order("B1", 1)
    assert o != run_eval.order("B1", 2) or o != run_eval.order("B2", 1)


def test_fresh_stage_interleaves_systems(evaldir):
    plan = run_eval.todo([], 1, ["B1", "B2", "S"])
    assert len(plan) == 81
    assert [p[:2] for p in plan[::9]] == [("B1", 1), ("B2", 1), ("S", 1), ("B1", 2), ("B2", 2),
                                          ("S", 2), ("B1", 3), ("B2", 3), ("S", 3)]
    assert [p[3] for p in plan[:9]] == run_eval.order("B1", 1)


def test_resume_skips_finished_runs(evaldir):
    first = run_eval.order("B1", 1)
    for sid in first[:4]:
        done("B1", 1, sid)
    plan = run_eval.todo(run_eval.load_manifest(), 1, ["B1"])
    assert len(plan) == 27 - 4
    assert [p[3] for p in plan[:5]] == first[4:]
    assert plan[0][2] == 5   # slot numbers keep the round's order


def test_rounds_limit_counts_unfinished_rounds(evaldir):
    for sid in range(1, 10):
        done("B1", 1, sid)
    plan = run_eval.todo(run_eval.load_manifest(), 1, ["B1", "B2"], rounds=1)
    assert {(p[0], p[1]) for p in plan} == {("B1", 2), ("B2", 1)}


def test_later_stage_adds_rounds(evaldir):
    for rnd in range(1, 4):
        for sid in range(1, 10):
            done("S", rnd, sid)
    assert run_eval.todo(run_eval.load_manifest(), 1, ["S"]) == []
    plan = run_eval.todo(run_eval.load_manifest(), 2, ["S"])
    assert len(plan) == 63 and plan[0][1] == 4


def test_void_makes_a_run_due_again(evaldir):
    done("B2", 1, 4, run_id="abc12345")
    before = len(run_eval.todo(run_eval.load_manifest(), 1, ["B2"]))
    run_eval.cmd_void(type("A", (), {"run_id": "abc12345", "reason": "VM stalled", "suite": "core"})())
    manifest = run_eval.load_manifest()
    assert len(run_eval.todo(manifest, 1, ["B2"])) == before + 1
    assert [r["status"] for r in manifest] == ["void"]
    assert manifest[0]["note"] == "VM stalled"
    assert run_eval.scored_runs(manifest, "B2", 1) == set()


def test_void_unknown_run_exits(evaldir):
    with pytest.raises(SystemExit):
        run_eval.cmd_void(type("A", (), {"run_id": "nope", "reason": "x", "suite": "core"})())


def test_scored_runs_respects_stage_and_system(evaldir):
    done("B1", 1, 1, run_id="a")
    done("B1", 4, 1, run_id="b")
    done("S", 1, 1, run_id="c")
    m = run_eval.load_manifest()
    assert run_eval.scored_runs(m, "B1", 1) == {"a"}
    assert run_eval.scored_runs(m, "B1", 2) == {"a", "b"}


def test_last_end(evaldir):
    assert run_eval.last_end([]) is None
    done("B1", 1, 1, ended="2026-10-12T10:00:00Z")
    done("B2", 1, 1, ended="2026-10-12T11:00:00Z")
    assert run_eval.iso(run_eval.last_end(run_eval.load_manifest())) == "2026-10-12T11:00:00Z"


def test_new_row_is_the_appended_row(evaldir):
    path = evaldir / "gt_B1.csv"
    def write(ids):
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["run_id", "start", "end_reason"])
            w.writeheader()
            # start times deliberately out of step with the host clock (Docker drift)
            w.writerows({"run_id": i, "start": "2020-01-01T00:00:00.000Z", "end_reason": "expired"} for i in ids)
    assert run_eval.new_row("B1", 0) is None            # no file yet
    write(["old"])
    assert run_eval.new_row("B1", 1) is None            # nothing appended
    write(["old", "new"])
    assert run_eval.new_row("B1", 1)["run_id"] == "new"
    write(["old", "a", "b"])
    assert run_eval.new_row("B1", 1) is None            # ambiguous


def test_slept(monkeypatch):
    monkeypatch.setattr(run_eval.time, "time", lambda: 1000.0 + 600)
    monkeypatch.setattr(run_eval.time, "monotonic", lambda: 50.0 + 120)
    assert run_eval.slept(1000.0, 50.0)                 # 600 s wall, 120 s awake
    monkeypatch.setattr(run_eval.time, "monotonic", lambda: 50.0 + 595)
    assert not run_eval.slept(1000.0, 50.0)


def test_gap_is_waited_before_switching_and_restoring(evaldir, monkeypatch):
    calls = []
    monkeypatch.setattr(run_eval, "wait_gap", lambda gap: calls.append("gap"))
    monkeypatch.setattr(run_eval, "switch_system", lambda s: calls.append(f"switch {s}") or False)
    monkeypatch.setattr(run_eval, "restore_default", lambda: calls.append("restore"))
    monkeypatch.setattr(run_eval, "wait_until_ready", lambda s: None)
    monkeypatch.setattr(run_eval, "run_one", lambda s, r, slot, sid: calls.append(f"run {s}"))
    monkeypatch.setattr(run_eval, "check_sleep", lambda: None)
    monkeypatch.setattr(run_eval, "keep_awake", lambda: None)
    monkeypatch.setattr(run_eval.signal, "signal", lambda *a: None)
    plan = [("B1", 1, 9, 6), ("S", 1, 9, 4)]
    monkeypatch.setattr(run_eval, "todo", lambda *a: plan)
    args = type("A", (), {"systems": "B1,S", "stage": 1, "rounds": None, "hours": None, "gap": 300,
                          "no_restore": False, "dry_run": False, "suite": "core"})()
    run_eval.cmd_run(args)
    assert calls == ["gap", "switch B1", "gap", "run B1", "gap", "switch S", "gap", "run S", "gap", "restore"]


def test_core_order_unchanged_by_the_extra_suite(evaldir):
    # Stage 1 ran in this order; resuming stage 2 depends on it staying the same
    assert run_eval.order("B1", 1) == [5, 2, 7, 8, 1, 6, 9, 4, 3]
    assert run_eval.order("B2", 1)[:5] == [3, 8, 4, 6, 1]
    assert run_eval.gt_container_path("B1") == "/experiments/eval/gt_B1.csv"


def test_extra_suite_plan_and_paths(evaldir):
    run_eval.use_suite("extra")
    plan = run_eval.todo([], 1, list(run_eval.cells()))
    assert len(plan) == (5 * 3 + 4) * 3
    assert {p[3] for p in plan if p[0] == "SF"} == {3, 4, 6, 8}
    assert {p[3] for p in plan if p[0] == "B1"} == {10, 11, 12, 13, 14}
    assert sorted(run_eval.order("B1", 1)) == [10, 11, 12, 13, 14]
    assert run_eval.runs_csv() == str(evaldir / "extra" / "runs.csv")
    assert run_eval.gt_container_path("SF") == "/experiments/eval/extra/gt_SF.csv"
    # Each suite has its own manifest
    done("B1", 1, 10)
    run_eval.use_suite("core")
    assert run_eval.load_manifest() == []


def test_novel_suite_plan_and_paths(evaldir):
    run_eval.use_suite("novel")
    plan = run_eval.todo([], 1, list(run_eval.cells()))
    assert len(plan) == 4 * 4 * 3
    assert {p[3] for p in plan if p[0] == "SF"} == {15, 16, 18, 19}
    assert run_eval.runs_csv() == str(evaldir / "novel" / "runs.csv")
    run_eval.use_suite("core")
    assert run_eval.order("B1", 1) == [5, 2, 7, 8, 1, 6, 9, 4, 3]   # core order untouched


def test_system_not_in_suite_is_refused(evaldir):
    with pytest.raises(SystemExit):
        run_eval.parse_systems("SF")          # SF only exists in the extra suite
    assert run_eval.parse_systems(None) == ["B1", "B2", "S"]


def test_gap_counts_every_suite_and_the_soak(evaldir):
    done("B1", 1, 1, ended="2026-10-12T10:00:00Z")
    run_eval.use_suite("extra")
    done("S", 1, 10, ended="2026-10-12T11:00:00Z")
    run_eval.use_suite("core")
    assert run_eval.iso(run_eval.last_end_any()) == "2026-10-12T11:00:00Z"
    run_eval.append_csv(os.path.join(run_eval.soak_dir(), "windows.csv"), run_eval.WINDOW_FIELDS,
                        {"system": "S", "start": "2026-10-12T11:10:00Z", "end": "2026-10-12T12:00:00Z"})
    assert run_eval.iso(run_eval.last_end_any()) == "2026-10-12T12:00:00Z"


def test_switch_to_sf_points_the_analyzer_at_a_dead_llm(monkeypatch):
    env = {"ANALYZER_MODE": "llm", "OLLAMA_URL": run_eval.DEFAULT_OLLAMA_URL}
    calls = []
    monkeypatch.setattr(run_eval, "container_env", lambda name: env)
    monkeypatch.setattr(run_eval, "running_containers", lambda: {"ml-detector"})
    monkeypatch.setattr(run_eval, "log", lambda msg: None)
    monkeypatch.setattr(run_eval, "sh", lambda args, env=None, timeout=0: calls.append((args, env))
                        or type("R", (), {"returncode": 0, "stderr": ""})())
    assert run_eval.switch_system("S") is False and calls == []     # already S
    assert run_eval.switch_system("SF") is True
    args, sent = calls[0]
    assert args[-1] == "analyzer" and sent == {"ANALYZER_MODE": "llm", "OLLAMA_URL": run_eval.DEAD_OLLAMA_URL}


SCHEMA = """CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, channel TEXT NOT NULL,
            type TEXT, incident_id TEXT, status TEXT, body TEXT NOT NULL)"""


def make_db(path, messages):
    con = sqlite3.connect(path)
    con.execute(SCHEMA)
    for type_, iid, body in messages:
        con.execute("INSERT INTO messages (at, channel, type, incident_id, status, body) VALUES (?,?,?,?,?,?)",
                    ("x", "c", type_, iid, body.get("status"), json.dumps(body)))
    con.commit()
    con.close()


def test_soak_report_counts_and_attributes_false_alarms(tmp_path):
    db = tmp_path / "inc.db"
    make_db(db, [
        ("incident", "a", {"opened_at": "2026-10-12T10:20:00Z", "sources": ["ml"], "services": ["api-service"]}),
        ("response_plan", "a", {"source": "llm", "recommended_action": {"type": "reset_faults", "target": "api-service"}}),
        ("action", "a", {"status": "executed", "action": {"type": "reset_faults", "target": "api-service"}}),
        ("incident", "b", {"opened_at": "2026-10-12T11:30:00Z", "sources": ["rule"], "services": ["frontend"]}),
        ("incident", "c", {"opened_at": "2026-10-12T15:00:00Z", "sources": ["rule"], "services": ["frontend"]}),  # outside
    ])
    windows = [{"system": "S", "start": "2026-10-12T10:00:00Z", "end": "2026-10-12T12:00:00Z",
                "awake_hours": "2.0", "events": "1", "note": ""}]
    events = [{"window_start": "2026-10-12T10:00:00Z", "at": "2026-10-12T10:10:00Z", "event": "load",
               "detail": "load 5 -> 10 users", "until": "2026-10-12T10:20:00Z"}]
    w = run_eval.soak_report(windows, events, run_eval.load_incident_summaries(db))[0]
    assert w["false_alarms"] == 2 and w["per_hour"] == 1.0
    assert w["after_event"] == 1 and w["without_event"] == 1
    assert w["by_source"] == {"ml": 1, "rule": 1} and w["actions_executed"] == 1
    assert w["incidents"][0]["after_event"] == "load 5 -> 10 users"
    assert w["incidents"][0]["first_plan"] == "llm:reset_faults/api-service"


def test_by_scenario_counts():
    base = {"name": "corrupted-cache", "detected": True, "root_cause_ok": False, "plan_action_ok": False,
            "executed_action_ok": False, "approval_requested": False, "escalated": True, "auto_resolved": False,
            "fallback_reason": None, "mttd_s": 30.0, "mttr_s": None}
    rows = [{**base, "scenario": "10"}, {**base, "scenario": "10", "approval_requested": True, "plan_action_ok": True,
                                         "escalated": False, "mttd_s": 40.0},
            {**base, "scenario": "12", "name": "subtle-latency-api", "detected": False, "mttd_s": None}]
    out = run_eval.by_scenario("S", rows)
    assert [r["scenario"] for r in out] == ["10", "12"]
    assert out[0]["runs"] == 2 and out[0]["approval_requested"] == 1 and out[0]["escalated"] == 1
    assert out[0]["mttd_mean_s"] == 35.0 and out[0]["mttr_mean_s"] is None
    assert out[1]["detected"] == 0 and out[1]["mttd_mean_s"] is None


def test_unfinished_soak_window_is_kept(evaldir):
    run_eval.save_progress("S", 1760000000.0, run_eval.time.monotonic() - 3600, 2)
    w = run_eval.soak_windows()
    assert len(w) == 1 and w[0]["system"] == "S" and w[0]["events"] == "2"
    assert 0.99 < float(w[0]["awake_hours"]) < 1.01 and w[0]["note"].startswith("unfinished")
