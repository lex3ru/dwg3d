"""Events: the envelope, and writing one into the outbox.

    await emit(session, "ping.note.created", ("note", note.id), {"text": note.text})

The event is stored in the transaction of `session`; it reaches NATS only if
that transaction commits. Its `data` must match contracts/events/<type>.json —
a mismatch is an error here, not a surprise for the consumer.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from uuid import UUID

from jsonschema import Draft202012Validator
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from . import auth
from .db import outbox, uuid7

SCOPE = ("building_id", "floor_id", "room_id", "asset_id", "person_id")
_contracts: Path | None = None
_service = "?"


def configure(service: str, contracts: Path) -> None:
    global _contracts, _service
    _contracts, _service = contracts, service
    _validator.cache_clear()


class UnknownEvent(RuntimeError):
    pass


@cache
def _validator(name: str) -> Draft202012Validator:
    path = _contracts / "events" / f"{name}.json"
    if not path.is_file():
        raise UnknownEvent(f"Нет контракта события: contracts/events/{name}.json")
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def check(event: dict) -> None:
    """Raise unless the envelope and its data match the contracts."""
    for validator, value in ((_validator("envelope"), event), (_validator(event["type"]), event["data"])):
        if (error := next(iter(validator.iter_errors(value)), None)) is not None:
            where = "/".join(str(p) for p in error.absolute_path) or "(корень)"
            raise ValueError(f"Событие {event['type']} не соответствует контракту: {where}: {error.message}")


def envelope(type: str, subject: tuple[str, object], data: dict, *, actor: dict | None = None, **scope) -> dict:
    unknown = set(scope) - set(SCOPE)
    if unknown:
        raise TypeError(f"Неизвестная область события: {sorted(unknown)}")
    me = auth.current.get()
    event = {
        "id": str(uuid7()), "type": type,
        "time": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "actor": actor or (me.actor() if me else {"kind": "service", "id": _service}),
        "subject": {"kind": subject[0], "id": str(subject[1])},
        "data": data,
    }
    event.update({k: str(v) for k, v in scope.items() if v is not None})
    return event


async def emit(session: AsyncSession, type: str, subject: tuple[str, object], data: dict, **scope) -> dict:
    event = envelope(type, subject, data, **scope)
    check(event)
    await session.execute(insert(outbox).values(id=UUID(event["id"]), type=type, payload=event))
    return event
