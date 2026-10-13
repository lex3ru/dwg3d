# ruff: noqa: E501
"""Checks the code does and the model explains: the audit of the records."""
from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel, Field

from . import Ctx, ToolError, tool
from .reading import _building, _people_names, _room_label, _room_names

MAX_SCAN = 5000
DATE_KEYS = ("warranty", "гарант", "service", "то_", "maintenance", "verification", "поверк", "calib", "expires", "until")


class Audit(BaseModel):
    building_id: str | None = Field(None, description="id здания; по умолчанию — открытое")
    floor_id: str | None = None
    room_id: str | None = None
    days: int = Field(30, ge=0, le=3650, description="за сколько дней вперёд считать срок (гарантия, ТО) истекающим")
    limit: int = Field(20, ge=1, le=100, description="сколько объектов перечислять в каждом списке")


@tool("audit_assets", """Аудит учёта (считает код): объекты без ответственного, требующие размещения (помещение снято), с незаполненными
обязательными свойствами, неисправные и в ремонте, с истёкшими или истекающими сроками (гарантия, ТО — свойства-даты),
давно не менявшиеся. Отдаёт счётчики и списки с id — по ним можно предлагать исправления.""")
async def audit_assets(ctx: Ctx, args: Audit) -> dict:
    b = _building(ctx, args.building_id)
    items: list[dict] = []
    cursor = 0
    while True:
        got = await ctx.get("assets", "/assets", building_id=b, floor_id=args.floor_id, room_id=args.room_id, limit=500, cursor=cursor)
        items.extend(got.get("items", []))
        if got.get("next") is None or len(items) >= MAX_SCAN:
            break
        cursor = got["next"]
    if not items:
        raise ToolError("Объектов не найдено (или они не видны пользователю)")
    today = date.today()
    horizon = today + timedelta(days=args.days)
    buckets: dict[str, list[dict]] = {"no_responsible": [], "needs_placement": [], "needs_fill": [], "faulty": [], "repair": [],
                                      "expired": [], "expiring": [], "stale": []}
    for a in items:
        if not a.get("responsible_id") and a.get("state") != "retired":
            buckets["no_responsible"].append(a)
        if a.get("needs_placement"):
            buckets["needs_placement"].append(a)
        if a.get("needs_fill"):
            buckets["needs_fill"].append(a)
        if a.get("state") == "faulty":
            buckets["faulty"].append(a)
        if a.get("state") == "repair":
            buckets["repair"].append(a)
        for key, value in (a.get("props") or {}).items():
            if not isinstance(value, str) or not any(k in key.lower() for k in DATE_KEYS):
                continue
            try:
                d = date.fromisoformat(value[:10])
            except ValueError:
                continue
            if d < today:
                buckets["expired"].append({**a, "_prop": key, "_date": value[:10]})
            elif d <= horizon:
                buckets["expiring"].append({**a, "_prop": key, "_date": value[:10]})
        upd = (a.get("updated_at") or "")[:10]
        try:
            if upd and (today - date.fromisoformat(upd)).days > 365:
                buckets["stale"].append(a)
        except ValueError:
            pass
    shown = {a["id"] for lst in buckets.values() for a in lst[: args.limit]}
    rooms = await _room_names(ctx, {a["room_id"] for a in items if a["id"] in shown and a.get("room_id")})
    people = await _people_names(ctx, {a["responsible_id"] for a in items if a["id"] in shown and a.get("responsible_id")})

    def brief(a: dict) -> dict:
        out = {"id": a["id"], "inventory_no": a.get("inventory_no"), "type": a.get("type_name"), "state": a.get("state"),
               "room_id": a.get("room_id"), "room": _room_label(rooms.get(a.get("room_id")))}
        if a.get("responsible_id"):
            out["responsible"] = people.get(a["responsible_id"], "")
        if a.get("_prop"):
            out["prop"], out["date"] = a["_prop"], a["_date"]
        return out

    return {"scanned": len(items), "truncated": len(items) >= MAX_SCAN, "horizon_days": args.days,
            "counts": {k: len(v) for k, v in buckets.items()},
            "lists": {k: [brief(a) for a in v[: args.limit]] for k, v in buckets.items() if v},
            "legend": {"no_responsible": "без ответственного", "needs_placement": "требуют размещения", "needs_fill": "не заполнены обязательные свойства",
                       "faulty": "неисправны", "repair": "в ремонте", "expired": "срок истёк", "expiring": "срок истекает", "stale": "не менялись больше года"}}
