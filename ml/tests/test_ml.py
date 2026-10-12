"""ML detector: model, persistence, and the fault_* guard. Synthetic data only."""

import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from model import FEATURES, ServiceModel, fit_all  # noqa: E402
from detector import Detector  # noqa: E402
import detector  # noqa: E402


def normal_row(rng, svc):
    if svc == "redis":
        return {"service": svc, "mem": 0.04 + rng.gauss(0, 0.002), "mem_bytes": 1.2e6 + rng.gauss(0, 5e4),
                "clients": 2 + rng.choice([0, 1]), "ops": 5 + rng.gauss(0, 0.3)}
    return {"service": svc, "cpu": abs(rng.gauss(0.02, 0.005)), "mem": 0.06 + rng.gauss(0, 0.002),
            "p95": 0.005 + abs(rng.gauss(0, 0.001)), "err": 0.0, "rps": 5 + rng.gauss(0, 0.2),
            "upstream_p95": 0.004 + abs(rng.gauss(0, 0.001)) if svc == "frontend" else 0.002}


def rows(n=600, seed=1):
    rng = random.Random(seed)
    return [normal_row(rng, svc) for _ in range(n) for svc in FEATURES]


def test_normal_samples_are_rarely_flagged():
    models = fit_all(rows())
    rng = random.Random(99)
    for svc, m in models.items():
        flagged = sum(m.score(normal_row(rng, svc))["anomalous"] for _ in range(400))
        assert flagged <= 4, (svc, flagged)


def test_memory_rise_is_flagged_with_mem_first():
    m = fit_all(rows())["api-service"]
    sample = {**normal_row(random.Random(5), "api-service"), "mem": 0.30}  # far below the 80% rule
    res = m.score(sample)
    assert res["anomalous"] and res["top_features"][0] == "mem"


def test_lower_than_usual_is_not_an_incident():
    m = fit_all(rows())["api-service"]
    sample = {**normal_row(random.Random(5), "api-service"), "mem": 0.01, "cpu": 0.0, "rps": 5.0}
    assert not m.score(sample)["anomalous"]  # e.g. just after a restart


def test_missing_values_count_as_typical():
    m = fit_all(rows())["frontend"]
    assert not m.score({f: None for f in FEATURES["frontend"]})["anomalous"]
    assert not m.score({"p95": float("nan")})["anomalous"]


def test_latency_and_errors_are_flagged():
    m = fit_all(rows())["frontend"]
    base = normal_row(random.Random(6), "frontend")
    assert "p95" in m.score({**base, "p95": 2.0})["top_features"]
    assert m.score({**base, "err": 0.5})["top_features"] == ["err"]


def test_needs_enough_training_data():
    try:
        ServiceModel("redis").fit([normal_row(random.Random(1), "redis")] * 5)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_detector_requires_sustained_anomaly_and_clears_at_once():
    models = fit_all(rows())
    det = Detector(models, sustain=2)
    bad = {**normal_row(random.Random(7), "api-service"), "mem": 0.4}
    good = normal_row(random.Random(8), "api-service")
    assert det.step("api-service", bad) is None
    out = det.step("api-service", bad)
    assert out["service"] == "api-service" and out["top_features"][0] == "mem"
    assert det.step("api-service", bad) is not None   # re-posted while it lasts
    assert det.step("api-service", good) is None      # stops at once when normal
    assert det.step("api-service", bad) is None       # streak restarts


def test_no_fault_queries_reach_the_detector():
    for svc, feats in FEATURES.items():
        for f in feats:
            assert "fault_" not in detector.SERVICE_QUERIES[svc][f]
        assert not any(f.startswith("fault_") for f in feats)


def test_forest_catches_moderate_deviations_together_but_not_alone():
    m = fit_all(rows())["frontend"]
    base = normal_row(random.Random(6), "frontend")
    together = m.score({**base, "p95": 0.155, "err": 0.06, "upstream_p95": 0.15})  # each z ~3 (< 4)
    assert together["anomalous"] and together["by"] == ["forest"]
    assert not m.score({**base, "p95": 0.155})["anomalous"]


def test_replay_scores_runs_and_false_positives():
    from replay import evaluate
    rng = random.Random(3)
    models = fit_all(rows())
    data = []
    for i in range(200):  # 50 min at 15 s
        stamp = f"2026-10-09T12:{i * 15 // 60:02d}:{i * 15 % 60:02d}Z"
        for svc in FEATURES:
            r = {**normal_row(rng, svc), "timestamp": stamp}
            if svc == "api-service" and 40 <= i < 60:   # injected run 10:00-15:00
                r["mem"] = 0.5
            if svc == "frontend" and 150 <= i < 154:     # an unexplained blip at 37:30
                r["err"] = 0.4
            data.append(r)
    runs = [{"run_id": "r1", "scenario": "8", "name": "gradual-memory-api", "target_service": "api-service",
             "end_reason": "remediated", "start": "2026-10-09T12:10:00Z", "end": "2026-10-09T12:15:00Z",
             "planned_end": "2026-10-09T12:15:00Z"}]
    res = evaluate(data, models, runs)
    run_ = res["per_run"][0]
    assert run_["detected"] and run_["delay_s"] == 15 and run_["target_flagged"]
    assert run_["first_features"][0] == "mem"
    assert [e["service"] for e in res["false_positive_episodes"]] == ["frontend"]
