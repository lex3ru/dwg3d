"""A variant is stale when the fact changed under it: an object it moves, changes or removes was changed since,
or a new revision of the drawing reshaped the floors it places objects on."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from twin_chassis.bus import Bus

from .models import variant_ops, variants

WHAT = {"assets.asset.moved": "перемещён", "assets.asset.changed": "изменён", "assets.asset.state_changed": "сменил состояние",
        "assets.asset.retired": "списан", "assets.asset.responsible_changed": "сменил ответственного"}


async def _mark(session: AsyncSession, ids: set, reason: dict) -> None:
    for vid in ids:
        v = (await session.execute(select(variants).where(variants.c.id == vid).with_for_update())).one()
        if v.status != "draft":
            continue
        await session.execute(update(variants).where(variants.c.id == vid).values(
            stale=True, stale_reasons=[*v.stale_reasons, reason][-50:]))


def register(bus: Bus) -> None:
    @bus.consumer("assets.asset.*", name="asset-changed")
    async def asset_changed(session: AsyncSession, event: dict) -> None:
        if event["type"] not in WHAT or event["type"] == "assets.asset.responsible_changed":
            return
        asset = UUID(event["data"]["asset_id"])
        ids = {vid for (vid,) in await session.execute(select(variant_ops.c.variant_id).where(variant_ops.c.asset_id == asset))}
        await _mark(session, ids, {"asset_id": str(asset), "what": WHAT[event["type"]], "at": event["time"]})

    @bus.consumer("buildings.revision.published", name="revision-published")
    async def revision_published(session: AsyncSession, event: dict) -> None:
        d = event["data"]
        if not (d["rooms"]["created"] or d["rooms"]["retired"] or d.get("moves")):
            return
        floors = {*d["floors"]["active"], *d["floors"]["retired"]}
        rows = (await session.execute(select(variant_ops.c.variant_id, variant_ops.c.data).join(
            variants, variants.c.id == variant_ops.c.variant_id).where(
            variants.c.building_id == UUID(event["building_id"]), variant_ops.c.op.in_(("add", "move"))))).all()
        ids = {vid for vid, data in rows if (data or {}).get("floor_id") in floors}
        await _mark(session, ids, {"what": "новая версия чертежа", "at": event["time"]})
