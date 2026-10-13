# ruff: noqa: E501
"""Facts for the texts the model writes: the passport of a building, a digest of the journal, what a revision changed."""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field

from . import Ctx, ToolError, tool
from .reading import BuildingArg, _building, _people_names

MAX_SCAN = 5000


@tool("building_passport", """Паспорт здания в фактах (для связного описания): этажи и помещения по видам с площадями, объекты
по разделам каталога и типам, состояния, оценка стоимости по ценам каталога, люди, ответственные. Текст пиши сам по этим данным.""")
async def building_passport(ctx: Ctx, args: BuildingArg) -> dict:
    b = _building(ctx, args.building_id)
    tree = await ctx.get("buildings", f"/buildings/{b}/tree")
    bld = tree.get("building") or {}
    floors, by_type = [], Counter()
    area_by_type: Counter = Counter()
    for f in sorted(tree.get("floors", []), key=lambda x: x.get("level") or 0):
        rooms = [r for r in f.get("rooms", []) if r.get("status", "active") == "active"]
        for r in rooms:
            by_type[r.get("type") or "other"] += 1
            area_by_type[r.get("type") or "other"] += float(r.get("area") or 0)
        floors.append({"id": f["id"], "name": f.get("name"), "level": f.get("level"), "rooms": len(rooms),
                       "area": round(sum(float(r.get("area") or 0) for r in rooms), 1)})
    items, cursor = [], 0
    while True:
        got = await ctx.get("assets", "/assets", building_id=b, limit=500, cursor=cursor)
        items.extend(got.get("items", []))
        if got.get("next") is None or len(items) >= MAX_SCAN:
            break
        cursor = got["next"]
    types = {}
    try:
        for active in ("true", "false"):
            got = await ctx.get("catalog", "/types", active=active)
            types.update({t["id"]: t for t in got.get("items", [])})
        cats = {c["id"]: c.get("name") for c in (await ctx.get("catalog", "/categories")).get("items", [])}
    except ToolError:
        cats = {}
    by_cat, by_kind, by_state = Counter(), Counter(), Counter()
    value = 0.0
    priced = 0
    for a in items:
        t = types.get(a.get("type_id")) or {}
        by_cat[cats.get(t.get("category_id") or a.get("category_id"), "прочее")] += 1
        by_kind[a.get("type_name") or "?"] += 1
        by_state[a.get("state") or "?"] += 1
        if t.get("price") is not None:
            value += float(t["price"])
            priced += 1
    out = {"building": {k: bld.get(k) for k in ("id", "name", "address")},
           "floors": floors, "rooms_total": sum(f["rooms"] for f in floors), "area_total": round(sum(f["area"] for f in floors), 1),
           "rooms_by_type": dict(by_type.most_common()), "area_by_type": {k: round(v, 1) for k, v in area_by_type.most_common()},
           "assets_total": len(items), "assets_truncated": len(items) >= MAX_SCAN,
           "assets_by_category": dict(by_cat.most_common()), "assets_by_type": dict(by_kind.most_common(30)),
           "assets_by_state": dict(by_state.most_common()),
           "estimated_value": {"sum": round(value), "priced_assets": priced, "currency": "RUB", "note": "по ценам-оценкам типов каталога"},
           "without_responsible": sum(1 for a in items if not a.get("responsible_id") and a.get("state") != "retired")}
    try:
        people = await ctx.get("people", "/people", building_id=b, limit=500)
        out["people_assigned"] = len(people.get("items", []))
    except ToolError as ex:
        out["people_assigned"] = str(ex)
    responsible = Counter(a["responsible_id"] for a in items if a.get("responsible_id"))
    names = await _people_names(ctx, set(dict(responsible.most_common(10))))
    out["top_responsible"] = [{"person": names.get(pid, pid), "assets": n} for pid, n in responsible.most_common(10)]
    return out


class DigestArg(BaseModel):
    building_id: str | None = Field(None, description="id здания; по умолчанию — открытое")
    days: int = Field(7, ge=1, le=366, description="за сколько последних дней")
    limit: int = Field(30, ge=1, le=200, description="сколько примечательных событий перечислить")


NOTABLE = {"assets.asset.state_changed": "смена состояния", "assets.asset.retired": "списание", "assets.asset.moved": "перемещение",
           "assets.asset.created": "новый объект", "assets.asset.responsible_changed": "смена ответственного",
           "access.grant.created": "выдано право", "access.grant.revoked": "отозвано право", "people.person.left": "выбыл человек",
           "buildings.revision.published": "новая ревизия чертежа", "buildings.room.retired": "снято помещение",
           "planning.variant.applied": "применён вариант", "copilot.proposal.applied": "применено предложение копилота"}


@tool("journal_digest", """Сводка журнала здания за период (считает код): сколько событий и каких, кто был активен, по дням,
примечательное — неисправности и списания, перемещения, новые объекты, права, ревизии. Рассказ по ней пиши сам.""")
async def journal_digest(ctx: Ctx, args: DigestArg) -> dict:
    b = _building(ctx, args.building_id)
    since = (datetime.now(UTC) - timedelta(days=args.days)).isoformat()
    events, cursor = [], None
    while True:
        got = await ctx.get("journal", "/events", building_id=b, limit=500, cursor=cursor, **{"from": since})
        events.extend(got.get("items", []))
        cursor = got.get("next")
        if not cursor or len(events) >= MAX_SCAN:
            break
    by_type, by_day, by_actor = Counter(), Counter(), Counter()
    notable = []
    for e in events:
        by_type[e.get("type")] += 1
        by_day[(e.get("time") or "")[:10]] += 1
        actor = e.get("actor") or {}
        by_actor[actor.get("person_id") or actor.get("id") or "?"] += 1
        if e.get("type") in NOTABLE:
            d = e.get("data") or {}
            notable.append({"time": e.get("time"), "what": NOTABLE[e["type"]], "type": e["type"], "actor": actor.get("person_id") or actor.get("id"),
                            "asset_id": e.get("asset_id"), "room_id": e.get("room_id"), "person_id": e.get("person_id"),
                            "data": {k: d.get(k) for k in ("from", "to", "fields", "inventory_no", "role", "from_room_id", "to_room_id") if k in d}})
    names = await _people_names(ctx, {k for k in by_actor if k and k != "?"})
    faulty = sum(1 for e in events if e.get("type") == "assets.asset.state_changed" and (e.get("data") or {}).get("to") == "faulty")
    return {"days": args.days, "since": since[:10], "events": len(events), "truncated": len(events) >= MAX_SCAN,
            "by_type": dict(by_type.most_common(30)), "by_day": dict(sorted(by_day.items())),
            "active": [{"actor": names.get(k, k), "events": n} for k, n in by_actor.most_common(10)],
            "became_faulty": faulty, "retired": by_type.get("assets.asset.retired", 0), "moved": by_type.get("assets.asset.moved", 0),
            "created": by_type.get("assets.asset.created", 0), "notable": notable[: args.limit]}


@tool("revisions", "Ревизии чертежей здания: загрузки новых версий чертежа — черновики на проверке и опубликованные.")
async def revisions(ctx: Ctx, args: BuildingArg) -> dict:
    b = _building(ctx, args.building_id)
    got = await ctx.get("buildings", f"/buildings/{b}/revisions")
    return {"revisions": [{k: r.get(k) for k in ("id", "drawing_id", "n", "status", "summary", "created_at", "published_at", "decided_by")}
                          for r in got.get("items", [])]}


class RevisionArg(BaseModel):
    revision_id: str


@tool("revision", """Ревизия подробно: как новая сборка чертежа сопоставлена с прежними помещениями (новые, те же, переименованные,
изменившие контур, снятые) и предупреждения сборки. Объясни пользователю, что изменится при публикации и что проверить.""")
async def revision(ctx: Ctx, args: RevisionArg) -> dict:
    r = await ctx.get("buildings", f"/revisions/{args.revision_id}")
    out = {k: r.get(k) for k in ("id", "drawing_id", "n", "status", "summary", "created_at", "published_at")}
    diffs = r.get("differences")
    if isinstance(diffs, dict):
        out["differences"] = {k: (v[:100] if isinstance(v, list) else v) for k, v in diffs.items()}
    elif isinstance(diffs, list):
        kinds = Counter(d.get("kind") or d.get("change") or "?" for d in diffs)
        out["differences"] = {"counts": dict(kinds), "items": diffs[:100]}
    out["warnings"] = (r.get("warnings") or [])[:50]
    return out
