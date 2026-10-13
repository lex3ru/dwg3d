# ruff: noqa: E501  (descriptions for the model are prose; they are not wrapped)
"""Proposing tools (building administrators only): nothing here changes data. Changes of objects become a
variant in planning; everything else — a proposal with a list of actions the user applies with a click."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .. import geometry, proposals
from ..tools.reading import _building, _room_label, _room_names
from . import Ctx, ToolError, tool


async def _propose(ctx: Ctx, summary: str, actions: list[dict]) -> dict:
    if not ctx.chat_id:
        raise ToolError("Предложение можно сделать только в беседе")
    try:
        async with ctx.db.begin() as session:
            p = await proposals.create(session, chat_id=ctx.chat_id, me=ctx.me, building_id=ctx.building_id,
                                       summary=summary, actions=actions)
    except ValueError as ex:
        raise ToolError(str(ex)) from ex
    return {"proposal": p, "next": "Предложение показано пользователю; применит он сам. Не говори, что изменения внесены."}


async def _asset(ctx: Ctx, asset_id: str) -> dict:
    return await ctx.get("assets", f"/assets/{asset_id}")


# ------------------------------------------------------------------ variants ---
class Place(BaseModel):
    type_id: str = Field(description="тип каталога")
    floor_id: str
    x: float
    y: float
    angle: float | None = None
    inventory_no: str | None = Field(None, description="инвентарный номер; пусто — назначат при применении")
    product_id: str | None = None


class Move(BaseModel):
    asset_id: str
    floor_id: str | None = Field(None, description="по умолчанию — тот же этаж")
    x: float
    y: float
    angle: float | None = None


class ProposeVariant(BaseModel):
    name: str = Field(description="название варианта, например «Переезд бухгалтерии»", max_length=200)
    summary: str = Field(description="что и зачем предлагается, одной-двумя фразами", max_length=2000)
    places: list[Place] = Field(default_factory=list, description="новые объекты и где их поставить (координаты плана этажа, м)")
    moves: list[Move] = Field(default_factory=list, description="перестановки существующих объектов")
    removes: list[str] = Field(default_factory=list, description="id объектов, которые убрать (списать)")
    based_on: str | None = Field(None, description="id варианта, копией которого начать; пусто — от факта")


@tool("propose_variant", """Предложить изменения объектов вариантом расстановки (проектирование): поставить новые, переставить,
убрать. Координаты — метры плана этажа; не выдумывай их: возьми из карточки объекта, из помещения (move_to_room) или спроси.
Пользователь увидит вариант на плане, сравнит с фактом и применит сам.""", kind="propose")
async def propose_variant(ctx: Ctx, args: ProposeVariant) -> dict:
    b = _building(ctx, None)
    if not (args.places or args.moves or args.removes):
        raise ToolError("Вариант пуст: укажите places, moves или removes")
    edits: list[dict] = []
    for m in args.moves:
        a = await _asset(ctx, m.asset_id)
        edits.append({"kind": "move", "asset_id": m.asset_id, "version": a["version"], "floor_id": m.floor_id or a["floor_id"],
                      "x": m.x, "y": m.y, **({"angle": m.angle} if m.angle is not None else {})})
    for r in args.removes:
        a = await _asset(ctx, r)
        edits.append({"kind": "remove", "asset_id": r, "version": a["version"]})
    for p in args.places:
        edits.append({"kind": "place", **{k: v for k, v in p.model_dump().items() if v is not None}})
    v = await ctx.call("POST", "planning", "/variants", json={"building_id": b, "name": args.name[:200], "based_on": args.based_on})
    res = await ctx.call("POST", "planning", f"/variants/{v['id']}/edits", json={"edits": edits})
    v = await ctx.get("planning", f"/variants/{v['id']}")
    prop = {"kind": "variant", "variant_id": v["id"], "name": v["name"], "summary": args.summary, "counts": v.get("counts"),
            "building_id": b}
    ctx.events.append({"type": "proposal", "proposal": prop})
    return {"proposal": prop, "edits": res, "next": "Вариант создан как черновик; пользователь посмотрит его в разделе «Варианты» и применит сам."}


class MoveToRoom(BaseModel):
    asset_ids: list[str] = Field(min_length=1, max_length=200, description="какие объекты")
    room_id: str = Field(description="куда")
    name: str | None = Field(None, description="название варианта; по умолчанию «Перенос в <помещение>»")
    summary: str | None = None


@tool("move_to_room", """Перенести объекты в другое помещение вариантом расстановки: места внутри помещения подбираются сами
(сеткой от центра), точную расстановку пользователь поправит в редакторе. Для «перенеси всё из 305 в 310» сначала найди
объекты помещения (room), затем вызови это.""", kind="propose")
async def move_to_room(ctx: Ctx, args: MoveToRoom) -> dict:
    room = await ctx.get("buildings", f"/rooms/{args.room_id}")
    poly = [(float(x), float(y)) for x, y in (room.get("polygon") or [])]
    if len(poly) < 3:
        raise ToolError("У помещения нет контура: перенести автоматически нельзя, укажите координаты в propose_variant")
    points = geometry.spread(poly, len(args.asset_ids))
    label = _room_label(room)
    moves = [Move(asset_id=a, floor_id=room["floor_id"], x=x, y=y) for a, (x, y) in zip(args.asset_ids, points, strict=True)]
    return await propose_variant(ctx, ProposeVariant(
        name=args.name or f"Перенос в {label}", summary=args.summary or f"Перенести {len(moves)} объектов в {label}", moves=moves))


# --------------------------------------------------------------------- rooms ---
class RoomChange(BaseModel):
    room_id: str
    name: str | None = Field(None, max_length=200)
    number: str | None = Field(None, max_length=40)
    type: str | None = Field(None, max_length=40, description="вид: office, corridor, wc, stair, lift, technical, meeting, storage, other…")


class ProposeRooms(BaseModel):
    summary: str = Field(max_length=2000)
    changes: list[RoomChange] = Field(min_length=1, max_length=200)


@tool("propose_rooms", "Предложить переименовать, перенумеровать помещения или сменить их вид. Применяется пользователем.", kind="propose")
async def propose_rooms(ctx: Ctx, args: ProposeRooms) -> dict:
    actions = []
    for c in args.changes:
        r = await ctx.get("buildings", f"/rooms/{c.room_id}")
        body = {k: v for k, v in (("name", c.name), ("number", c.number), ("type", c.type)) if v is not None}
        if not body:
            continue
        what = ", ".join(f"{k}: «{r.get(k) or ''}» → «{v}»" for k, v in body.items())
        actions.append(proposals.action(f"Помещение {_room_label(r)}: {what}", "buildings", "PATCH", f"/rooms/{c.room_id}",
                                        {**body, "version": r["version"]}))
    return await _propose(ctx, args.summary, actions)


# -------------------------------------------------------------------- assets ---
class StateChange(BaseModel):
    asset_id: str
    state: Literal["in_use", "faulty", "repair", "stock", "retired"]


class ProposeState(BaseModel):
    summary: str = Field(max_length=2000)
    changes: list[StateChange] = Field(min_length=1, max_length=200)


@tool("propose_state", "Предложить сменить состояние объектов: в работе, неисправен, в ремонте, на складе, списан (списание — только администратору).", kind="propose")
async def propose_state(ctx: Ctx, args: ProposeState) -> dict:
    actions = []
    for c in args.changes:
        a = await _asset(ctx, c.asset_id)
        actions.append(proposals.action(f"{a.get('type_name')} {a.get('inventory_no')}: {a.get('state')} → {c.state}", "assets",
                                        "POST", f"/assets/{c.asset_id}/state", {"state": c.state, "version": a["version"]}))
    return await _propose(ctx, args.summary, actions)


class ResponsibleChange(BaseModel):
    asset_id: str
    person_id: str | None = Field(description="кто отвечает; null — снять ответственного")


class ProposeResponsible(BaseModel):
    summary: str = Field(max_length=2000)
    changes: list[ResponsibleChange] = Field(min_length=1, max_length=200)


@tool("propose_responsible", "Предложить назначить или снять ответственного за объекты (человек — из справочника, people).", kind="propose")
async def propose_responsible(ctx: Ctx, args: ProposeResponsible) -> dict:
    names = {}
    ids = {c.person_id for c in args.changes if c.person_id}
    if ids:
        got = await ctx.call("POST", "people", "/people/batch-get", json={"ids": sorted(ids)})
        names = {p["id"]: p.get("full_name") for p in got.get("items", [])}
        missing = ids - set(names)
        if missing:
            raise ToolError(f"В справочнике нет людей с id: {', '.join(sorted(missing))}")
    actions = []
    for c in args.changes:
        a = await _asset(ctx, c.asset_id)
        who = names.get(c.person_id, "") if c.person_id else "никто"
        actions.append(proposals.action(f"{a.get('type_name')} {a.get('inventory_no')}: ответственный — {who}", "assets", "POST",
                                        f"/assets/{c.asset_id}/responsible", {"person_id": c.person_id, "version": a["version"]}))
    return await _propose(ctx, args.summary, actions)


class NoteChange(BaseModel):
    asset_id: str
    note: str = Field(max_length=2000)


class ProposeNotes(BaseModel):
    summary: str = Field(max_length=2000)
    changes: list[NoteChange] = Field(min_length=1, max_length=200)


@tool("propose_notes", "Предложить примечания к объектам (заменяют прежнее примечание).", kind="propose")
async def propose_notes(ctx: Ctx, args: ProposeNotes) -> dict:
    actions = []
    for c in args.changes:
        a = await _asset(ctx, c.asset_id)
        actions.append(proposals.action(f"{a.get('type_name')} {a.get('inventory_no')}: примечание «{c.note[:60]}»", "assets", "PATCH",
                                        f"/assets/{c.asset_id}", {"note": c.note, "version": a["version"]}))
    return await _propose(ctx, args.summary, actions)


# -------------------------------------------------------------------- people ---
class Assign(BaseModel):
    person_id: str
    room_id: str
    workplace_asset_id: str | None = Field(None, description="рабочее место (объект) в этом помещении")


class Unassign(BaseModel):
    person_id: str
    room_id: str


class ProposeAssignments(BaseModel):
    summary: str = Field(max_length=2000)
    assign: list[Assign] = Field(default_factory=list, max_length=200)
    unassign: list[Unassign] = Field(default_factory=list, max_length=200)


@tool("propose_assignments", "Предложить привязать людей к помещениям (и рабочим местам) или отвязать. Привязанный сам получает право видеть помещение.", kind="propose")
async def propose_assignments(ctx: Ctx, args: ProposeAssignments) -> dict:
    if not (args.assign or args.unassign):
        raise ToolError("Нечего предлагать")
    ids = {x.person_id for x in [*args.assign, *args.unassign]}
    got = await ctx.call("POST", "people", "/people/batch-get", json={"ids": sorted(ids)})
    names = {p["id"]: p.get("full_name") for p in got.get("items", [])}
    rooms = await _room_names(ctx, {x.room_id for x in [*args.assign, *args.unassign]})
    actions = []
    for a in args.assign:
        actions.append(proposals.action(f"{names.get(a.person_id, a.person_id)} → {_room_label(rooms.get(a.room_id))}", "people", "PUT",
                                        f"/people/{a.person_id}/assignments/{a.room_id}",
                                        {"workplace_asset_id": a.workplace_asset_id} if a.workplace_asset_id else {}))
    for u in args.unassign:
        actions.append(proposals.action(f"{names.get(u.person_id, u.person_id)}: отвязать от {_room_label(rooms.get(u.room_id))}", "people",
                                        "DELETE", f"/people/{u.person_id}/assignments/{u.room_id}"))
    return await _propose(ctx, args.summary, actions)


# -------------------------------------------------------------------- rights ---
class GrantNew(BaseModel):
    person_id: str
    role: Literal["viewer", "responsible", "admin"]
    scope_kind: Literal["building", "floor", "room", "asset"]
    scope_id: str


class ProposeGrants(BaseModel):
    summary: str = Field(max_length=2000)
    grant: list[GrantNew] = Field(default_factory=list, max_length=200)
    revoke: list[str] = Field(default_factory=list, max_length=200, description="id назначений (grants), которые отозвать")


@tool("propose_grants", "Предложить выдать права (роль на здание, этаж, помещение или объект) или отозвать назначения (их id — из grants).", kind="propose")
async def propose_grants(ctx: Ctx, args: ProposeGrants) -> dict:
    if not (args.grant or args.revoke):
        raise ToolError("Нечего предлагать")
    b = _building(ctx, None)
    names = {}
    if args.grant:
        got = await ctx.call("POST", "people", "/people/batch-get", json={"ids": sorted({g.person_id for g in args.grant})})
        names = {p["id"]: p.get("full_name") for p in got.get("items", [])}
    actions = []
    for g in args.grant:
        actions.append(proposals.action(f"{names.get(g.person_id, g.person_id)}: {g.role} на {g.scope_kind} {g.scope_id[:8]}…", "access", "POST", "/grants",
                                        {"person_id": g.person_id, "role": g.role, "scope": {"kind": g.scope_kind, "id": g.scope_id}, "building_id": b}))
    for gid in args.revoke:
        actions.append(proposals.action(f"Отозвать назначение {gid[:8]}…", "access", "DELETE", f"/grants/{gid}"))
    return await _propose(ctx, args.summary, actions)


# ------------------------------------------------------------------ comments ---
class ProposeComment(BaseModel):
    target_kind: Literal["room", "asset"]
    target_id: str
    body: str = Field(min_length=1, max_length=4000, description="текст замечания")


@tool("propose_comment", "Предложить оставить комментарий к помещению или объекту (замечание, вопрос); увидят все, кому видно это место.", kind="propose")
async def propose_comment(ctx: Ctx, args: ProposeComment) -> dict:
    if args.target_kind == "room":
        r = await ctx.get("buildings", f"/rooms/{args.target_id}")
        b, label = r["building_id"], _room_label(r)
    else:
        a = await _asset(ctx, args.target_id)
        b, label = a["building_id"], f"{a.get('type_name')} {a.get('inventory_no')}"
    act = proposals.action(f"Комментарий к {label}: «{args.body[:60]}»", "buildings", "POST", "/comments",
                           {"building_id": b, "target_kind": args.target_kind, "target_id": args.target_id, "body": args.body})
    return await _propose(ctx, f"Комментарий к {label}", [act])
