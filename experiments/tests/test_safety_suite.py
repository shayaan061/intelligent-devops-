"""The adversarial safety suite must pass in full (objective O4: 0 unsafe actions)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import safety_suite  # noqa: E402


def test_every_adversarial_case_is_contained():
    results = safety_suite.run_suite()
    failed = [(r["id"], r["case"], r["outcome"], r["crashed"]) for r in results if not r["pass"]]
    assert failed == []
    assert sum(r["unsafe_executed"] for r in results) == 0
