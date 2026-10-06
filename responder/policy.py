"""Policy validator (§6.5): decides what happens to a ResponsePlan.

Pure functions over the plan, the policies and the responder's state, so
every rule is unit-tested. The checks, in order, for the recommended action
and then the fallback action:

  1. the action type is on the allowlist
  2. the target is allowed for that type
  3. the incident has had fewer than max_actions_per_incident actions
  4. the same type+target hasn't run within cooldown_seconds
  5. confidence is a number in [0, 1] and >= min_confidence, otherwise a
     human approves
  6. risky types (requires_approval) always need a human

An action that fails 1, 2 or 4 is skipped and the fallback is tried. If
neither passes, the incident is escalated. `escalate` itself always passes
and executes nothing.
"""

import os
from dataclasses import dataclass, field

import yaml

EXECUTE, APPROVAL, ESCALATE = "execute", "approval", "escalate"


def load_policies(path):
    with open(path) as f:
        p = yaml.safe_load(f)
    for key in ("actions", "min_confidence", "cooldown_seconds", "max_actions_per_incident",
                "verify_delay_seconds", "max_attempts"):
        if key not in p:
            raise ValueError(f"{path}: missing {key}")
    if "COOLDOWN_SECONDS" in os.environ:
        p["cooldown_seconds"] = float(os.environ["COOLDOWN_SECONDS"])
    return p


@dataclass
class Decision:
    kind: str                 # execute | approval | escalate
    action: dict              # {"type", "target"}
    reasons: list = field(default_factory=list)


def valid_confidence(c):
    """A real number in [0, 1]. Rejects bool (an int in Python), NaN (every
    comparison with NaN is False, so `nan < 0.7` would let it through), inf
    and strings. Plans can reach the responder without the analyzer's schema."""
    return isinstance(c, (int, float)) and not isinstance(c, bool) and 0 <= c <= 1


def action_key(action):
    return (action.get("type"), action.get("target"))


def decide(plan, policies, executed_count, last_run, now):
    """plan: ResponsePlan dict. executed_count: actions already run for this
    incident. last_run: {(type, target): timestamp} across incidents."""
    reasons = []
    candidates = [("recommended", plan.get("recommended_action")),
                  ("fallback", plan.get("fallback_action"))]

    for which, action in candidates:
        if not isinstance(action, dict):
            continue
        a_type, target = action.get("type"), action.get("target")
        # JSON can carry lists/objects here; they'd crash the dict lookups below
        if not isinstance(a_type, str) or not (target is None or isinstance(target, str)):
            reasons.append(f"{which}: malformed action")
            continue

        if a_type == "escalate":
            return Decision(ESCALATE, {"type": "escalate", "target": target}, reasons + [f"{which}: escalate"])

        rule = policies["actions"].get(a_type)
        if rule is None:
            reasons.append(f"{which}: {a_type} not on the allowlist")
            continue
        if target not in rule["targets"]:
            reasons.append(f"{which}: {a_type} not allowed on {target}")
            continue
        if executed_count >= policies["max_actions_per_incident"]:
            reasons.append(f"max {policies['max_actions_per_incident']} actions per incident reached")
            return Decision(ESCALATE, {"type": "escalate", "target": target}, reasons)
        since = now - last_run.get((a_type, target), float("-inf"))
        if since < policies["cooldown_seconds"]:
            reasons.append(f"{which}: {a_type} on {target} in cooldown ({since:.0f}s < {policies['cooldown_seconds']:.0f}s)")
            continue

        chosen = {"type": a_type, "target": target}
        confidence = plan.get("confidence")
        if not valid_confidence(confidence) or confidence < policies["min_confidence"]:
            return Decision(APPROVAL, chosen, reasons + [f"confidence {confidence} < {policies['min_confidence']}"])
        if rule["requires_approval"]:
            return Decision(APPROVAL, chosen, reasons + [f"{a_type} requires approval"])
        return Decision(EXECUTE, chosen, reasons + [f"{which} action passed all checks"])

    target = plan.get("root_cause_service")
    return Decision(ESCALATE, {"type": "escalate", "target": target}, reasons + ["no action passed validation"])
