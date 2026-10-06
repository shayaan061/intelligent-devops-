"""Make the analyzer modules importable (they are plain scripts, not a package)
and point the runbook engine at the repo's runbooks/."""

import json
import sys
from pathlib import Path

import pytest

ANALYZER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ANALYZER))

SAMPLES = ANALYZER / "samples"
RUNBOOKS = ANALYZER.parent / "runbooks"


def load_sample(n):
    return json.loads((SAMPLES / f"scenario{n}.json").read_text())


@pytest.fixture(scope="session")
def runbooks():
    from runbooks import load_runbooks
    return load_runbooks(RUNBOOKS)
