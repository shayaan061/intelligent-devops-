"""Evaluation runner: run order, resume, void and per-system scoring selection
(no Docker; the stack-control functions aren't exercised here).

Run:  pytest -q experiments/tests
"""

import csv
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import run_eval  # noqa: E402


@pytest.fixture
def evaldir(tmp_path, monkeypatch):
    monkeypatch.setattr(run_eval, "EVAL_DIR", str(tmp_path))
    monkeypatch.setattr(run_eval, "RUNS_CSV", str(tmp_path / "runs.csv"))
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
    run_eval.cmd_void(type("A", (), {"run_id": "abc12345", "reason": "VM stalled"})())
    manifest = run_eval.load_manifest()
    assert len(run_eval.todo(manifest, 1, ["B2"])) == before + 1
    assert [r["status"] for r in manifest] == ["void"]
    assert manifest[0]["note"] == "VM stalled"
    assert run_eval.scored_runs(manifest, "B2", 1) == set()


def test_void_unknown_run_exits(evaldir):
    with pytest.raises(SystemExit):
        run_eval.cmd_void(type("A", (), {"run_id": "nope", "reason": "x"})())


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


def test_find_row_picks_the_new_run(evaldir):
    path = evaldir / "gt_B1.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["run_id", "start", "end_reason"])
        w.writeheader()
        w.writerow({"run_id": "old", "start": "2026-10-12T09:00:00.000Z", "end_reason": "expired"})
        w.writerow({"run_id": "new", "start": "2026-10-12T10:00:01.500Z", "end_reason": "remediated"})
    started = run_eval.datetime.fromisoformat("2026-10-12T10:00:00+00:00").timestamp()
    assert run_eval.find_row("B1", started)["run_id"] == "new"
    assert run_eval.find_row("B1", started + 3600) is None
    assert run_eval.find_row("B2", started) is None


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
                          "no_restore": False, "dry_run": False})()
    run_eval.cmd_run(args)
    assert calls == ["gap", "switch B1", "gap", "run B1", "gap", "switch S", "gap", "run S", "gap", "restore"]
