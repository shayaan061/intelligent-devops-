"""LLM Analysis Engine service (SUGGESTED_PLAN.md §6.4).

Listens for IncidentEvents on the gateway's /ws/events WebSocket, decides a
root cause and ONE recommended action per incident, and POSTs the
ResponsePlan to the gateway's /responses (which rebroadcasts it on
/ws/responses). It only recommends: no Docker calls, no /reset calls. The
policy validator and executor (§6.5) decide what actually runs.

Decision (analyze()):
  ANALYZER_MODE=llm      Ollama first; YAML runbooks when the LLM is
                         unreachable, times out, returns invalid JSON, breaks
                         the schema/allowlist or reports confidence < 0.7.
                         fallback_reason says which.
  ANALYZER_MODE=runbook  runbooks only: the "no LLM" baseline B1
                         (fallback_reason "mode=runbook").

Socket handling: only messages with type == "incident" count; replayed ones
(replay: true, sent on connect) and status "resolved" are skipped, and a
resolved incident still waiting in the queue is dropped. Inference is slow
on CPU, so the reader never waits for it: one worker analyzes, and an
incident updated while queued is analyzed once, in its latest version.

Env:
  GATEWAY_URL    default http://gateway:8000 (ws URL derived from it)
  ANALYZER_MODE  llm | runbook, default llm
  RUNBOOK_DIR    default ../runbooks next to this file; /runbooks in Docker
  OLLAMA_URL, OLLAMA_MODEL, LLM_TIMEOUT    see llm.py

Usage:
  python analyzer.py serve
  python analyzer.py analyze samples/scenario4.json [--mode runbook|llm]
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time

import httpx
from pydantic import ValidationError

import llm
from runbooks import load_runbooks, run_runbooks
from schemas import IncidentEvent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("analyzer")
# httpx logs every request at INFO; keep one line per plan
logging.getLogger("httpx").setLevel(logging.WARNING)

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://gateway:8000").rstrip("/")
ANALYZER_MODE = os.environ.get("ANALYZER_MODE", "llm")
MODES = ("llm", "runbook")


def events_ws_url(gateway_url):
    if gateway_url.startswith("https://"):
        return "wss://" + gateway_url[len("https://"):] + "/ws/events"
    return "ws://" + gateway_url.removeprefix("http://") + "/ws/events"


# -----------------------------
# Decision
# -----------------------------

def analyze(incident, mode="llm", runbooks=None, client=None):
    """IncidentEvent (or dict) -> ResponsePlan. Never raises for LLM problems:
    those fall back to the runbooks with fallback_reason set."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    if not isinstance(incident, IncidentEvent):
        incident = IncidentEvent.model_validate(incident)
    if runbooks is None:
        runbooks = load_runbooks()

    t0 = time.perf_counter()
    if mode == "runbook":
        plan, reason = None, "mode=runbook"
    else:
        try:
            plan, reason = llm.llm_plan(incident, client), None
        except llm.LLMError as e:
            plan, reason = None, str(e)
        except Exception as e:  # a bug in the LLM path must not lose the incident
            log.exception("LLM path failed")
            plan, reason = None, f"error: {type(e).__name__}"

    if plan is None:
        plan = run_runbooks(incident, runbooks, fallback_reason=reason)

    latency = round((time.perf_counter() - t0) * 1000, 1)
    return plan.model_copy(update={"latency_ms": latency})


def plan_line(plan):
    a = plan.recommended_action
    return (f"plan {plan.incident_id} attempt={plan.attempt} source={plan.source}"
            f"{'/' + plan.runbook if plan.runbook else ''} root={plan.root_cause_service}"
            f" type={plan.incident_type} action={a.type}:{a.target} conf={plan.confidence:.2f}"
            f" fallback_reason={plan.fallback_reason} {plan.latency_ms:.0f}ms")


# -----------------------------
# Queue with per-incident coalescing
# -----------------------------

class Coalescer:
    """FIFO of incident ids; each id holds only its latest event, so an
    incident updated three times while Ollama is busy is analyzed once."""

    def __init__(self):
        self.latest = {}
        self.queue = asyncio.Queue()

    def put(self, event):
        iid = event["incident_id"]
        if iid not in self.latest:
            self.queue.put_nowait(iid)
        self.latest[iid] = event

    def drop(self, incident_id):
        # The id stays in the queue; get() skips it
        self.latest.pop(incident_id, None)

    def pending(self):
        return len(self.latest)

    async def get(self):
        while True:
            iid = await self.queue.get()
            event = self.latest.pop(iid, None)
            if event is not None:
                return event


def handle_message(text, coalescer):
    """Route one /ws/events message. Returns what was done, for logs/tests."""
    try:
        msg = json.loads(text)
    except ValueError:
        return "ignored: not json"
    if not isinstance(msg, dict) or msg.get("type") != "incident":
        return "ignored: not an incident"
    if msg.get("replay"):
        return "ignored: replay"
    if not msg.get("incident_id"):
        return "ignored: no incident_id"

    status = msg.get("status", "open")
    if status == "resolved":
        coalescer.drop(msg["incident_id"])
        return "dropped: resolved"
    # reanalyze: the verifier found the fix didn't work (history.attempt > 1)
    if status not in ("open", "updated", "reanalyze"):
        return f"ignored: status {status}"

    coalescer.put(msg)
    return "queued"


# -----------------------------
# Service
# -----------------------------

async def post_plan(client, plan):
    body = plan.model_dump(mode="json")
    for attempt in range(3):
        try:
            r = await client.post(f"{GATEWAY_URL}/responses", json=body, timeout=10)
            if r.status_code < 300:
                return True
            log.warning("POST /responses -> %s %s", r.status_code, r.text[:200])
        except httpx.HTTPError as e:
            log.warning("POST /responses failed: %s", e)
        await asyncio.sleep(2 ** attempt)
    log.error("plan for %s not delivered", plan.incident_id)
    return False


async def worker(coalescer, runbooks, mode):
    async with httpx.AsyncClient() as client:
        while True:
            event = await coalescer.get()
            try:
                incident = IncidentEvent.model_validate(event)
            except ValidationError as e:
                log.warning("bad incident %s: %s", event.get("incident_id"), e.errors()[:3])
                continue
            try:
                # Blocking Ollama call off the event loop, so the reader keeps up
                plan = await asyncio.to_thread(analyze, incident, mode, runbooks)
            except Exception:
                log.exception("analysis of %s failed", incident.incident_id)
                continue
            log.info(plan_line(plan))
            await post_plan(client, plan)


async def reader(url, coalescer):
    from websockets.asyncio.client import connect

    backoff = 1
    while True:
        try:
            async with connect(url, max_size=None) as ws:
                log.info("connected to %s", url)
                backoff = 1
                async for text in ws:
                    result = handle_message(text, coalescer)
                    if result != "ignored: not an incident":
                        log.debug("%s", result)
        except Exception as e:
            log.warning("events socket %s: %s; retrying in %ss", url, e or type(e).__name__, backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30)


async def serve(mode):
    runbooks = load_runbooks()
    log.info("mode=%s model=%s ollama=%s runbooks=%d gateway=%s",
             mode, llm.OLLAMA_MODEL, llm.OLLAMA_URL, len(runbooks), GATEWAY_URL)
    coalescer = Coalescer()
    await asyncio.gather(reader(events_ws_url(GATEWAY_URL), coalescer),
                         worker(coalescer, runbooks, mode))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("serve", help="listen on the gateway WebSocket and post plans")

    p_an = sub.add_parser("analyze", help="analyze one IncidentEvent JSON file and print the plan")
    p_an.add_argument("file")
    p_an.add_argument("--mode", choices=MODES, default=ANALYZER_MODE)

    args = parser.parse_args()

    if args.cmd == "serve":
        if ANALYZER_MODE not in MODES:
            sys.exit(f"ANALYZER_MODE must be one of {MODES}, got {ANALYZER_MODE!r}")
        asyncio.run(serve(ANALYZER_MODE))
    else:
        with open(args.file) as f:
            event = json.load(f)
        plan = analyze(event, args.mode)
        print(json.dumps(plan.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
