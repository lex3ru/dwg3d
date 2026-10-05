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


def visible(me: Identity, event: dict) -> bool:
    """Whether the viewer may see the event.

    Until the access service exists (stage 2) there are no scopes to check:
    system administrators see everything, others only what they did themselves."""
    return me.is_admin or event.get("actor", {}).get("id") == me.sub


class Hub:
    def __init__(self):
        self._viewers: dict[asyncio.Queue, Identity] = {}

    def __len__(self) -> int:
        return len(self._viewers)

    def dispatch(self, event: dict) -> None:
        for queue, me in list(self._viewers.items()):
            if not visible(me, event):
                continue
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:           # a stuck browser: drop it, it will reconnect and reload
                self._viewers.pop(queue, None)

    async def events(self, me: Identity, heartbeat: float = HEARTBEAT) -> AsyncIterator[bytes]:
        """The body of the stream for one viewer."""
        queue: asyncio.Queue = asyncio.Queue(QUEUE)
        self._viewers[queue] = me
        try:
            yield b"retry: 3000\n\n"
            while queue in self._viewers:
                try:
                    event = await asyncio.wait_for(queue.get(), heartbeat)
                except TimeoutError:
                    yield b": keep-alive\n\n"
                    continue
                data = json.dumps(event, ensure_ascii=False)
                yield f"id: {event['id']}\ndata: {data}\n\n".encode()
        finally:
            self._viewers.pop(queue, None)
