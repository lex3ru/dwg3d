"""Events to the browser: GET /api/stream (Server-Sent Events).

The gateway hears every event on the bus and passes on those the viewer may
see. Nothing is replayed: a browser that was away reloads what it shows.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from twin_chassis import Identity

HEARTBEAT = 15.0
QUEUE = 500


def visible(me: Identity, buildings: set[str], event: dict) -> bool:
    """Whether the viewer may see the event: what happens in a building — those who may see
    its plan; what belongs to no building — whoever did it. The system administrator sees all."""
    if me.is_admin:
        return True
    if event.get("building_id"):
        return event["building_id"] in buildings
    return event.get("actor", {}).get("id") == me.sub


class Hub:
    def __init__(self):
        self._viewers: dict[asyncio.Queue, tuple[Identity, set[str]]] = {}

    def __len__(self) -> int:
        return len(self._viewers)

    def dispatch(self, event: dict) -> None:
        for queue, (me, buildings) in list(self._viewers.items()):
            if not visible(me, buildings, event):
                continue
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:           # a stuck browser: drop it, it will reconnect and reload
                self._viewers.pop(queue, None)

    async def events(self, me: Identity, buildings=None, heartbeat: float = HEARTBEAT) -> AsyncIterator[bytes]:
        """The body of the stream for one viewer. `buildings`: an async callable giving the
        buildings the viewer may see now; asked again with every heartbeat, so a right given
        or taken away shows within one."""
        queue: asyncio.Queue = asyncio.Queue(QUEUE)

        async def refresh() -> None:
            if buildings is not None and queue in self._viewers:
                try:
                    self._viewers[queue] = (me, set(await buildings()))
                except Exception:
                    pass                        # the access service is away: go on by what was known

        self._viewers[queue] = (me, set())
        await refresh()
        try:
            yield b"retry: 3000\n\n"
            while queue in self._viewers:
                try:
                    event = await asyncio.wait_for(queue.get(), heartbeat)
                except TimeoutError:
                    await refresh()
                    yield b": keep-alive\n\n"
                    continue
                data = json.dumps(event, ensure_ascii=False)
                yield f"id: {event['id']}\ndata: {data}\n\n".encode()
        finally:
            self._viewers.pop(queue, None)
