"""Socket message routing and per-incident coalescing."""

import asyncio
import json

from analyzer import Coalescer, events_ws_url, handle_message


def msg(iid="inc-0001", status="open", **extra):
    return json.dumps({"type": "incident", "incident_id": iid, "status": status, **extra})


def test_routing():
    c = Coalescer()
    assert handle_message("not json", c).startswith("ignored")
    assert handle_message(json.dumps({"type": "alert", "alertname": "HighCPU"}), c).startswith("ignored")
    assert handle_message(msg(replay=True), c) == "ignored: replay"
    assert handle_message(msg(status="weird"), c).startswith("ignored")
    assert handle_message(json.dumps({"type": "incident"}), c).startswith("ignored")
    assert c.pending() == 0
    assert handle_message(msg(), c) == "queued"
    assert handle_message(msg(status="updated"), c) == "queued"
    assert c.pending() == 1


def test_coalescing_keeps_latest_and_order():
    async def scenario():
        c = Coalescer()
        handle_message(msg("inc-1", version=1), c)
        handle_message(msg("inc-2", version=1), c)
        handle_message(msg("inc-1", "updated", version=2), c)
        handle_message(msg("inc-1", "updated", version=3), c)
        first = await c.get()
        second = await c.get()
        assert c.pending() == 0
        # Updated again after being taken: analyzed again
        handle_message(msg("inc-1", "updated", version=4), c)
        third = await c.get()
        return first, second, third

    first, second, third = asyncio.run(scenario())
    assert (first["incident_id"], first["version"]) == ("inc-1", 3)
    assert (second["incident_id"], second["version"]) == ("inc-2", 1)
    assert (third["incident_id"], third["version"]) == ("inc-1", 4)


def test_resolved_while_queued_is_dropped():
    async def scenario():
        c = Coalescer()
        handle_message(msg("inc-1"), c)
        handle_message(msg("inc-2"), c)
        assert handle_message(msg("inc-1", "resolved"), c) == "dropped: resolved"
        got = await c.get()
        try:
            await asyncio.wait_for(c.get(), 0.05)
            return got, "unexpected"
        except asyncio.TimeoutError:
            return got, "empty"

    got, rest = asyncio.run(scenario())
    assert got["incident_id"] == "inc-2"
    assert rest == "empty"


def test_ws_url():
    assert events_ws_url("http://gateway:8000") == "ws://gateway:8000/ws/events"
    assert events_ws_url("https://example.org") == "wss://example.org/ws/events"
