"""Events to the browser."""
from __future__ import annotations

import asyncio
import json

from twin_chassis import Identity
from twin_chassis.events import envelope

from app.stream import Hub, visible


def event_by(sub: str) -> dict:
    return envelope("ping.note.created", ("note", "n1"), {"text": "x"}, actor={"kind": "user", "id": sub})


def test_who_sees_what():
    user, admin = Identity("user", "user-1"), Identity("user", "admin-1", roles=("twin.admin",))
    assert visible(user, set(), event_by("user-1")) and not visible(user, set(), event_by("user-2"))
    assert visible(admin, set(), event_by("user-2"))
    # what happens in a building is seen by those who may see its plan, whoever did it
    there = {**event_by("user-2"), "building_id": "b1"}
    assert visible(user, {"b1"}, there) and not visible(user, {"b2"}, there) and not visible(user, set(), there)
    assert not visible(user, set(), {**event_by("user-1"), "building_id": "b1"})


async def test_viewer_gets_only_visible_events():
    hub = Hub()
    stream = hub.events(Identity("user", "user-1"), heartbeat=0.05)
    assert await anext(stream) == b"retry: 3000\n\n"
    assert await anext(stream) == b": keep-alive\n\n"          # the heartbeat also registered the viewer

    mine, theirs = event_by("user-1"), event_by("user-2")
    hub.dispatch(theirs)
    hub.dispatch(mine)
    chunk = (await anext(stream)).decode()
    assert chunk.startswith(f"id: {mine['id']}\ndata: ")
    assert json.loads(chunk.split("data: ", 1)[1]) == mine

    await stream.aclose()
    assert len(hub) == 0


async def test_events_from_the_bus_reach_the_hub(app):
    """What a service publishes is heard by the gateway (through real NATS)."""
    bus = app.state.bus
    for _ in range(50):
        if bus.connected:
            break
        await asyncio.sleep(0.1)
    stream = app.state.hub.events(Identity("user", "admin-1", roles=("twin.admin",)), heartbeat=5)
    await anext(stream)
    pending = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0.05)                                  # the viewer is registered

    event = event_by("user-9")
    await bus.js.publish(bus.subject + event["type"], json.dumps(event).encode())
    chunk = (await asyncio.wait_for(pending, 2)).decode()      # criterion: within 2 seconds
    assert event["id"] in chunk
    await stream.aclose()


async def test_rights_given_meanwhile_show_with_the_next_heartbeat():
    hub, mine = Hub(), []

    async def buildings():
        return mine

    stream = hub.events(Identity("user", "user-1"), buildings, heartbeat=0.05)
    assert await anext(stream) == b"retry: 3000\n\n"
    there = {**event_by("user-2"), "building_id": "b1"}
    hub.dispatch(there)                                     # not seen: no right in b1 yet
    mine.append("b1")
    assert await anext(stream) == b": keep-alive\n\n"       # the heartbeat asks again
    hub.dispatch(there)
    assert there["id"] in (await anext(stream)).decode()
    await stream.aclose()
