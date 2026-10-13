"""Requests of the assets service, under /api/assets/v1 (contracts/openapi/assets.v1.json).

An object is seen by those with a right on it or on the room, floor or building it is
in; who answers for it (or for its room) edits what the schema lets them and its state;
the building's administrator does the rest. What one may not see does not exist (404).
A guest by a link sees the objects of its area and nothing of who is behind them: no
responsible, no note, no property naming a person; history, files, labels and changes
are not for guests (403 `guest`).
"""
from __future__ import annotations

import asyncio
import re
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.concurrency import iterate_in_threadpool
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from twin_chassis import Identity, Problem, current_identity, emit, forbid_guests, uuid7
from twin_chassis.access import decide

from . import core, labels, storage
from .models import STATES, asset_files, asset_history, assets, type_schemas

router = APIRouter()
MAX_FILE = 25 * 1024 * 1024
FORBIDDEN = "Недостаточно прав для этого действия"


async def _scopes(request: Request, me: Identity, *, reading: bool = False) -> dict:
    return await request.app.state.rights.scopes(request, me, reading=reading)


async def _asset(session, asset_id: UUID, scopes: dict, *, lock: bool = False):
    q = select(assets).where(assets.c.id == asset_id)
    a = (await session.execute(q.with_for_update() if lock else q)).one_or_none()
    if a is None or not decide(scopes, "view", core.chain(a)):
        raise Problem(404, "not_found", "Объект не найден")
    return a


def _need(scopes: dict, action: str, chain, message: str = FORBIDDEN) -> None:
    if not decide(scopes, action, chain):
        raise Problem(403, "forbidden", message)


HIDDEN_FROM_GUESTS = ("responsible_id", "note")


async def _person_keys(session, type_ids=None) -> dict[str, set[str]]:
    """The properties naming a person, by type (of the given types; of all of them when None)."""
    q = select(type_schemas.c.type_id, type_schemas.c.schema, type_schemas.c.type_props)
    if type_ids is not None:
        q = q.where(type_schemas.c.type_id.in_(list(type_ids) or [uuid7()]))
    return {str(t): {p["key"] for p in [*schema, *kept] if p.get("kind") == "person"}
            for t, schema, kept in (await session.execute(q)).all()}


async def _shown(session, me: Identity, rows) -> list[dict]:
    """The objects as the caller gets them: a guest by a link does not learn who is behind them."""
    items = [core.asset_json(a) for a in rows]
    if me.kind != "guest" or not items:
        return items
    people = await _person_keys(session, {a.type_id for a in rows})
    for item in items:
        for field in HIDDEN_FROM_GUESTS:
            item.pop(field)
        hidden = people.get(item["type_id"], set())
        item["props"] = {k: v for k, v in item["props"].items() if k not in hidden}
    return items


def _stale(a, version: int) -> None:
    if a.version != version:
        raise Problem(409, "version_conflict", "Объект изменил кто-то другой — вот его текущее состояние",
                      extra={"current": core.asset_json(a)})


async def _locate(request: Request, floor_id: UUID, points: list[tuple[float, float]]) -> tuple[UUID, list[UUID | None]]:
    """The building of the floor and the room of each point, as the buildings service says."""
    token = request.headers.get("authorization", "").partition(" ")[2].strip()
    r = await request.app.state.client.request("POST", "buildings", f"/floors/{floor_id}/locate", token=token,
                                               json={"points": [list(p) for p in points]})
    if r.status_code == 404:
        raise Problem(422, "invalid", "Этаж не найден", errors=[{"field": "floor_id", "message": "не найден"}])
    if r.status_code != 200:
        raise Problem(503, "service_unavailable", "Сервис зданий не ответил — поставить или переместить объект сейчас нельзя",
                      extra={"service": "buildings"})
    body = r.json()
    return UUID(body["building_id"]), [UUID(x) if x else None for x in body["rooms"]]


def _taken(ex: IntegrityError) -> Problem | None:
    if "inventory_no" in str(ex.orig):
        return Problem(409, "inventory_no_taken", "Такой инвентарный номер уже есть (номера списанных объектов не используются повторно)")
    return None


# --------------------------------------------------------------------- read ---
@router.get("/assets", tags=["assets"], summary="Объекты, видимые спрашивающему")
async def list_assets(request: Request, building_id: UUID | None = None, floor_id: UUID | None = None,
                      room_id: UUID | None = None, type_id: UUID | None = None, category_id: UUID | None = None,
                      product_id: UUID | None = None, state: str | None = None, responsible_id: UUID | None = None,
                      container_id: UUID | None = None,
                      needs_placement: bool | None = None, needs_fill: bool | None = None, q: str | None = None,
                      limit: int = 200, cursor: int = 0, me: Identity = Depends(current_identity)) -> dict:
    """Also filters by values of properties: `prop.<key>=`, `prop.<key>.gte=`, `prop.<key>.lte=`
    (dates and numbers compare as written: 2026-10-05, 12.5). Retired objects come only with `state=retired`."""
    where = [assets.c.state == state] if state and state != "all" else ([] if state == "all" else [assets.c.state != "retired"])
    seen = core.visible_filter(await _scopes(request, me, reading=True))
    if seen is not None:
        where.append(seen)
    for column, value in ((assets.c.building_id, building_id), (assets.c.floor_id, floor_id), (assets.c.room_id, room_id),
                          (assets.c.type_id, type_id), (assets.c.category_id, category_id),
                          (assets.c.product_id, product_id), (assets.c.responsible_id, responsible_id),
                          (assets.c.container_id, container_id),
                          (assets.c.needs_placement, needs_placement), (assets.c.needs_fill, needs_fill)):
        if value is not None:
            where.append(column == value)
    if q and q.strip():
        pattern = core.like(q)
        where.append(assets.c.type_name.ilike(pattern) | assets.c.product_name.ilike(pattern)
                     | assets.c.inventory_no.ilike(pattern) | func.coalesce(assets.c.serial_no, "").ilike(pattern))
    for name, value in request.query_params.items():
        if name.startswith("prop."):
            key, _, op = name[5:].partition(".")
            field = assets.c.props[key].astext
            where.append(field >= value if op == "gte" else field <= value if op == "lte" else field == value)
    limit, cursor = max(1, min(limit, 500)), max(0, cursor)
    async with request.app.state.db.begin() as session:
        if me.kind == "guest":                      # who answers for what is not a guest's to ask, even by a filter
            people = set().union(*(await _person_keys(session)).values())
            if responsible_id is not None or any(n.startswith("prop.") and n[5:].partition(".")[0] in people
                                                 for n in request.query_params):
                raise Problem(403, "guest", "Гостю по ссылке это недоступно")
        rows = (await session.execute(select(assets).where(*where).order_by(assets.c.type_name, assets.c.inventory_no)
                                      .limit(limit + 1).offset(cursor))).all()
        total = (await session.execute(select(func.count()).select_from(assets).where(*where))).scalar_one()
        items = await _shown(session, me, rows[:limit])
    return {"items": items, "total": total, "next": cursor + limit if len(rows) > limit else None}


class Ids(BaseModel):
    ids: list[UUID] = Field(max_length=1000)


@router.post("/assets/batch-get", tags=["assets"], summary="Объекты по идентификаторам (невидимые пропускаются)")
async def batch_assets(body: Ids, request: Request, me: Identity = Depends(current_identity)) -> dict:
    scopes = await _scopes(request, me, reading=True)
    async with request.app.state.db.begin() as session:
        rows = (await session.execute(select(assets).where(assets.c.id.in_(body.ids or [uuid7()])))).all()
        return {"items": await _shown(session, me, [a for a in rows if decide(scopes, "view", core.chain(a))])}


@router.get("/assets/{asset_id}", tags=["assets"], summary="Объект; `can` — что с ним может спрашивающий")
async def get_asset(asset_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> dict:
    scopes = await _scopes(request, me, reading=True)
    async with request.app.state.db.begin() as session:
        a = await _asset(session, asset_id, scopes)
        schema = await core.schema_of(request, session, a.type_id)
        children = (await session.execute(select(assets).where(assets.c.container_id == asset_id)
                                          .order_by(assets.c.type_name, assets.c.inventory_no))).all()
        (card,), children = await _shown(session, me, [a]), await _shown(session, me, children)
    type_props = [p for p in schema.type_props if me.kind != "guest" or p.get("kind") != "person"]
    product = None                                     # the make and model as the catalog describes it; none when it is down
    if a.product_id:
        try:
            product = await core.fetch_product(request.app.state.client, a.product_id, core.token_of(request))
        except Problem:
            product = None
    return {**card, "schema": schema.schema, "type_props": type_props, "product": product,
            "portable": schema.portable, "container": schema.container, "children": children,
            "can": {"edit": decide(scopes, "edit", core.chain(a)), "manage": decide(scopes, "manage", core.chain(a)),
                    "move": decide(scopes, "manage" if not schema.portable else "move_portable", core.chain(a))}}


@router.get("/qr/{code}", tags=["assets"], summary="Чей это QR-код: идентификатор объекта")
async def by_qr(code: str, request: Request, me: Identity = Depends(forbid_guests)) -> dict:
    scopes = await _scopes(request, me, reading=True)
    async with request.app.state.db.begin() as session:
        a = (await session.execute(select(assets).where(assets.c.qr_code == code.upper()))).one_or_none()
    if a is None or not decide(scopes, "view", core.chain(a)):       # a stranger does not learn whether it exists
        raise Problem(404, "not_found", "Объект не найден")
    return {"asset_id": str(a.id), "building_id": str(a.building_id)}


# ------------------------------------------------------------------- labels ---
def _pdf(data: bytes, filename: str) -> Response:
    from urllib.parse import quote
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(filename)}"})


@router.get("/assets/{asset_id}/label", tags=["labels"], response_class=Response, responses={200: {"content": {"application/pdf": {}}}},
            summary="QR-метка объекта в PDF; size — сторона наклейки в мм")
async def label(asset_id: UUID, request: Request, size: float = Query(40, ge=labels.MIN_MM, le=labels.MAX_MM),
                me: Identity = Depends(forbid_guests)) -> Response:
    scopes = await _scopes(request, me, reading=True)
    async with request.app.state.db.begin() as session:
        a = await _asset(session, asset_id, scopes)
    url = labels.link(request.app.state.settings.public_url, a.qr_code)
    return _pdf(await asyncio.to_thread(labels.single, url, a, size), f"метка-{a.inventory_no}.pdf")


class Labels(BaseModel):
    asset_ids: list[UUID] | None = Field(default=None, max_length=2000, description="Какие объекты; иначе — все в области")
    building_id: UUID | None = None
    floor_id: UUID | None = None
    room_id: UUID | None = None
    size: float = Field(default=40, ge=labels.MIN_MM, le=labels.MAX_MM, description="Сторона наклейки, мм")


@router.post("/labels", tags=["labels"], response_class=Response, responses={200: {"content": {"application/pdf": {}}}},
             summary="Лист QR-меток в PDF (A4): выбранные объекты или все объекты помещения, этажа, здания")
async def label_sheet(body: Labels, request: Request, me: Identity = Depends(forbid_guests)) -> Response:
    scopes = await _scopes(request, me, reading=True)
    q = select(assets).where(assets.c.retired_at.is_(None)).order_by(assets.c.inventory_no)
    if body.asset_ids is not None:
        q = q.where(assets.c.id.in_(body.asset_ids))
    elif body.room_id is not None:
        q = q.where(assets.c.room_id == body.room_id)
    elif body.floor_id is not None:
        q = q.where(assets.c.floor_id == body.floor_id)
    elif body.building_id is not None:
        q = q.where(assets.c.building_id == body.building_id)
    else:
        raise Problem(422, "invalid", "Укажите объекты или область", errors=[{"field": "asset_ids", "message": "пусто"}])
    async with request.app.state.db.begin() as session:
        rows = [a for a in (await session.execute(q)).all() if decide(scopes, "view", core.chain(a))]
    if not rows:
        raise Problem(404, "not_found", "Объектов для меток нет")
    for a in rows:                                  # the sheet is the administrator's: labels are printed by whoever keeps the objects
        _need(scopes, "manage", core.chain(a), "Печатать листы меток может администратор здания")
    base = request.app.state.settings.public_url
    data = await asyncio.to_thread(labels.sheet, [(labels.link(base, a.qr_code), a) for a in rows], body.size, "QR-метки")
    return _pdf(data, "метки.pdf")


@router.get("/responsibles", tags=["assets"], summary="Кто за какой объект отвечает (служебный: для сверки прав)")
async def responsibles(request: Request, me: Identity = Depends(forbid_guests)) -> dict:
    if not me.is_admin and me.kind != "service":
        raise Problem(403, "forbidden", "Служебный запрос")
    async with request.app.state.db.begin() as session:
        rows = (await session.execute(select(assets.c.id, assets.c.responsible_id, assets.c.building_id).where(
            assets.c.responsible_id.is_not(None), assets.c.retired_at.is_(None)))).all()
    return {"items": [{"asset_id": str(a.id), "person_id": str(a.responsible_id), "building_id": str(a.building_id)}
                      for a in rows]}


@router.get("/usage", tags=["assets"], summary="Есть ли объекты типа и значения свойства (для каталога)")
async def usage(request: Request, type_id: UUID, prop: str | None = None, me: Identity = Depends(forbid_guests)) -> dict:
    if not me.is_admin and me.kind != "service":
        raise Problem(403, "forbidden", FORBIDDEN)
    async with request.app.state.db.begin() as session:
        total = (await session.execute(select(func.count()).select_from(assets).where(assets.c.type_id == type_id))).scalar_one()
        valued = 0 if prop is None else (await session.execute(select(func.count()).select_from(assets).where(
            assets.c.type_id == type_id, assets.c.props[prop].astext.is_not(None), assets.c.props[prop].astext != ""))).scalar_one()
    return {"assets": total, "with_value": valued}


# ------------------------------------------------------------------- create ---
class Place(BaseModel):
    floor_id: UUID | None = None
    x: float | None = Field(default=None, ge=-1e5, le=1e5)
    y: float | None = Field(default=None, ge=-1e5, le=1e5)
    angle: float = Field(default=0, ge=-360, le=360)
    elevation: float | None = Field(default=None, ge=0, le=100)
    container_id: UUID | None = Field(default=None, description="Вместо точки: объект, внутри которого стоит")


class AssetIn(Place):
    type_id: UUID
    product_id: UUID | None = Field(default=None, description="Марка и модель из каталога, если известна")
    inventory_no: str = Field(min_length=1, max_length=60)
    serial_no: str | None = Field(default=None, max_length=100)
    props: dict = Field(default_factory=dict)
    note: str = Field(default="", max_length=2000)


async def _where(request: Request, session, scopes: dict, place: Place) -> dict:
    """Where the place is: a point of a floor (the room is found by it) or inside a container."""
    if place.container_id is not None:
        box = await _asset(session, place.container_id, scopes)
        kind = await core.schema_of(request, session, box.type_id)
        if not kind.container or box.container_id is not None or box.state == "retired":
            raise Problem(422, "invalid", "В этот объект нельзя вкладывать другие",
                          errors=[{"field": "container_id", "message": "не контейнер"}])
        return {"building_id": box.building_id, "floor_id": box.floor_id, "room_id": box.room_id, "x": None, "y": None,
                "container_id": box.id, "angle": 0, "elevation": None}
    if place.floor_id is None or place.x is None or place.y is None:
        raise Problem(422, "invalid", "Нужны этаж и точка или контейнер", errors=[{"field": "floor_id", "message": "обязательно"}])
    building, (room,) = await _locate(request, place.floor_id, [(place.x, place.y)])
    if room is None:
        raise Problem(422, "outside", "Точка не попадает ни в одно помещение", errors=[{"field": "x", "message": "вне помещений"}])
    return {"building_id": building, "floor_id": place.floor_id, "room_id": room, "x": place.x, "y": place.y,
            "container_id": None, "angle": place.angle, "elevation": place.elevation}


def _area(where: dict) -> list[tuple[str, object]]:
    return [("room", where["room_id"]), ("floor", where["floor_id"]), ("building", where["building_id"])]


async def _insert(request: Request, session, me: Identity, who: dict, body: AssetIn, where: dict):
    kind = await core.schema_of(request, session, body.type_id)
    if kind.archived:
        raise Problem(422, "invalid", f"Тип «{kind.name}» в архиве", errors=[{"field": "type_id", "message": "в архиве"}])
    core.check_props(kind.schema, body.props)
    product_id, product_name = await core.product_of(request, body.type_id, body.product_id)
    a = (await session.execute(insert(assets).values(
        id=uuid7(), type_id=body.type_id, type_name=kind.name, category_id=kind.category_id,
        product_id=product_id, product_name=product_name,
        schema_version=kind.schema_version, inventory_no=body.inventory_no.strip(), serial_no=body.serial_no,
        props=body.props, note=body.note, needs_fill=core.incomplete(kind.schema, body.props), qr_code=core.qr_code(),
        created_by=me.sub, **where).returning(assets))).one()
    await core.record(session, a.id, who, "created", {"type": [None, kind.name], "inventory_no": [None, a.inventory_no],
                                                       **({"product_name": [None, product_name]} if product_name else {})})
    await emit(session, "assets.asset.created", ("asset", a.id),
               {"asset_id": str(a.id), "type_id": str(a.type_id), "inventory_no": a.inventory_no}, **core.scope_fields(a))
    return a


NUMBER = re.compile(r"^(.*?)(\d+)$")


def _initials(name: str) -> str:
    """«Камера купольная (потолок)» → «КК»: the first letters of the words before any brackets."""
    words = re.findall(r"[^\W\d_]+", name.split("(")[0])
    return "".join(w[0] for w in words[:3]).upper() or "ОБ"


@router.get("/inventory-numbers", tags=["assets"], summary="Свободные инвентарные номера для новых объектов типа")
async def free_numbers(request: Request, type_id: UUID, count: int = Query(default=1, ge=1, le=500),
                       me: Identity = Depends(forbid_guests)) -> dict:
    """For one who has no number at hand: `count` numbers in a row, none of them taken in the whole system (the
    numbers of objects written off included). They continue the series of the last object of the type («КК-00012» →
    «КК-00013»); a type without objects starts its own, from the first letters of its name («КК-00001»). Nothing is
    reserved: two who ask at once may get the same, and the second to place an object is told the number is taken."""
    async with request.app.state.db.begin() as session:
        last = (await session.execute(select(assets.c.inventory_no).where(assets.c.type_id == type_id)
                                      .order_by(assets.c.created_at.desc()).limit(1))).scalar()
        hit = NUMBER.match(last or "")
        if hit:
            prefix, width = hit.group(1), len(hit.group(2))
        else:
            prefix, width = f"{_initials((await core.schema_of(request, session, type_id)).name)}-", 5
        like = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        taken = {n for (n,) in await session.execute(select(assets.c.inventory_no).where(assets.c.inventory_no.like(like)))}
    seqs = [int(m.group(2)) for n in taken if (m := NUMBER.match(n)) and m.group(1) == prefix]
    n, out = max(seqs, default=0) + 1, []
    while len(out) < count:
        number = f"{prefix}{n:0{width}d}"
        if number not in taken:
            out.append(number)
        n += 1
    return {"numbers": out}


@router.post("/assets", status_code=201, tags=["assets"], summary="Поставить объект: тип, точка этажа или контейнер, номер")
async def create_asset(body: AssetIn, request: Request, me: Identity = Depends(forbid_guests)) -> dict:
    scopes, who = await _scopes(request, me), await core.actor(request, me)
    try:
        async with request.app.state.db.begin() as session:
            where = await _where(request, session, scopes, body)
            if not decide(scopes, "manage", _area(where)):
                raise Problem(404 if not decide(scopes, "plan", _area(where)) else 403, "forbidden",
                              "Ставить объекты может администратор здания")
            return core.asset_json(await _insert(request, session, me, who, body, where))
    except IntegrityError as ex:
        raise _taken(ex) or ex from ex


class Batch(BaseModel):
    type_id: UUID
    product_id: UUID | None = Field(default=None, description="Марка и модель всех объектов ряда")
    floor_id: UUID
    points: list[tuple[float, float]] = Field(min_length=1, max_length=500, description="Точки [x, y]")
    angle: float = 0
    prefix: str = Field(max_length=40, description="Начало инвентарного номера: «КР-»")
    start: int = Field(ge=0, le=10**9, description="С какого числа считать")
    width: int = Field(default=4, ge=1, le=10, description="Сколько цифр в номере")


@router.post("/assets/batch", status_code=201, tags=["assets"],
             summary="Несколько одинаковых объектов с номерами подряд; всё или ничего")
async def create_batch(body: Batch, request: Request, me: Identity = Depends(forbid_guests)) -> dict:
    scopes, who = await _scopes(request, me), await core.actor(request, me)
    building, rooms = await _locate(request, body.floor_id, body.points)
    outside = [i + 1 for i, r in enumerate(rooms) if r is None]
    if outside:
        raise Problem(422, "outside", f"Точки вне помещений: {', '.join(map(str, outside))}",
                      errors=[{"field": "points", "message": "вне помещений"}])
    made = []
    try:
        async with request.app.state.db.begin() as session:
            for i, ((x, y), room) in enumerate(zip(body.points, rooms, strict=True)):
                where = {"building_id": building, "floor_id": body.floor_id, "room_id": room, "x": x, "y": y,
                         "container_id": None, "angle": body.angle, "elevation": None}
                _need(scopes, "manage", _area(where), "Ставить объекты может администратор здания")
                one = AssetIn(type_id=body.type_id, product_id=body.product_id,
                              inventory_no=f"{body.prefix}{body.start + i:0{body.width}d}")
                made.append(core.asset_json(await _insert(request, session, me, who, one, where)))
    except IntegrityError as ex:                    # one taken number refuses them all
        raise _taken(ex) or ex from ex
    return {"items": made}


COLUMNS = {"тип": "type", "инвентарный номер": "inventory_no", "серийный номер": "serial_no", "этаж": "floor",
           "x": "x", "y": "y", "примечание": "note"}


@router.post("/assets/import", status_code=201, tags=["assets"],
             summary="Загрузить объекты из Excel: Тип, Инвентарный номер, Серийный номер, Этаж, X, Y, Примечание")
async def import_assets(request: Request, building_id: UUID, file: UploadFile = File(...),
                        me: Identity = Depends(forbid_guests)) -> dict:
    """All rows or none: with a mistake in any row nothing is created, and the answer names the rows.
    The type is given by its name in the catalog, the floor by its number (level) or name; X and Y are
    plan coordinates of the floor, metres."""
    import io

    from openpyxl import load_workbook

    scopes, who = await _scopes(request, me), await core.actor(request, me)
    area = [("building", building_id)]
    if not decide(scopes, "manage", area):
        raise Problem(404 if not decide(scopes, "plan", area) else 403, "forbidden", "Объекты загружает администратор здания")
    try:
        rows = list(load_workbook(io.BytesIO(await file.read()), read_only=True, data_only=True).active.iter_rows(values_only=True))
    except Exception as ex:
        raise Problem(422, "invalid", "Не удалось прочитать файл: нужен Excel (.xlsx)",
                      errors=[{"field": "file", "message": "не .xlsx"}]) from ex
    header = [COLUMNS.get(str(c or "").strip().lower()) for c in (rows[0] if rows else [])]
    missing = [title for title, key in COLUMNS.items() if key in ("type", "inventory_no", "floor", "x", "y") and key not in header]
    if missing:
        raise Problem(422, "invalid", "В первой строке не хватает столбцов: " + ", ".join(missing),
                      errors=[{"field": "file", "message": "нет столбцов"}])
    if len(rows) > 5001:
        raise Problem(422, "invalid", "Строк больше 5000")
    token = request.headers.get("authorization", "").partition(" ")[2].strip()
    client = request.app.state.client
    types_r = await client.get("catalog", "/types", token=token)
    tree_r = await client.get("buildings", f"/buildings/{building_id}/tree", token=token)
    if types_r.status_code != 200 or tree_r.status_code != 200:
        raise Problem(503, "service_unavailable", "Каталог или сервис зданий не ответил — загрузить объекты сейчас нельзя")
    types = {t["name"].strip().lower(): t for t in types_r.json()["items"]}
    floors = {}
    for f in tree_r.json()["floors"]:
        floors[f["name"].strip().lower()] = floors[str(f["level"])] = f
    errors, parsed, seen = [], [], set()
    for n, row in enumerate(rows[1:], start=2):
        raw = {k: v for k, v in zip(header, row, strict=False) if k}
        if all(v is None or str(v).strip() == "" for v in raw.values()):
            continue
        problems = []
        kind = types.get(str(raw.get("type") or "").strip().lower())
        floor_key = str(raw.get("floor") or "").strip().lower()
        floor = floors.get(floor_key) or floors.get(floor_key.removesuffix(".0"))
        number = str(raw.get("inventory_no") or "").strip()
        if kind is None:
            problems.append(f"нет типа «{raw.get('type') or ''}» в каталоге")
        if floor is None:
            problems.append(f"нет этажа «{raw.get('floor') or ''}»")
        if not number:
            problems.append("нет инвентарного номера")
        elif number in seen:
            problems.append(f"номер {number} повторяется в файле")
        seen.add(number)
        try:
            x, y = float(raw.get("x")), float(raw.get("y"))
        except (TypeError, ValueError):
            problems.append("X и Y должны быть числами")
            x = y = None
        if problems:
            errors.append({"row": n, "message": "; ".join(problems)})
        else:
            serial = str(raw["serial_no"]).strip() if raw.get("serial_no") not in (None, "") else None
            parsed.append({"row": n, "type": kind, "floor": floor, "number": number, "x": x, "y": y, "serial": serial,
                           "note": str(raw.get("note") or "").strip()})
    by_floor: dict[str, list[dict]] = {}
    for p in parsed:
        by_floor.setdefault(p["floor"]["id"], []).append(p)
    for floor_id, items in by_floor.items():
        _, found = await _locate(request, UUID(floor_id), [(p["x"], p["y"]) for p in items])
        for p, room in zip(items, found, strict=True):
            p["room"] = room
            if room is None:
                errors.append({"row": p["row"], "message": "точка вне помещений"})
    async with request.app.state.db.begin() as session:
        taken = set((await session.execute(select(assets.c.inventory_no).where(
            assets.c.inventory_no.in_([p["number"] for p in parsed] or [""])))).scalars())
        errors += [{"row": p["row"], "message": f"номер {p['number']} уже есть"} for p in parsed if p["number"] in taken]
        if errors:
            raise Problem(422, "invalid", f"В файле ошибки ({len(errors)}) — ничего не загружено",
                          errors=[{"field": f"строка {e['row']}", "message": e["message"]}
                                  for e in sorted(errors, key=lambda e: e["row"])])
        for p in parsed:
            where = {"building_id": building_id, "floor_id": UUID(p["floor"]["id"]), "room_id": p["room"], "x": p["x"],
                     "y": p["y"], "container_id": None, "angle": 0, "elevation": None}
            one = AssetIn(type_id=UUID(p["type"]["id"]), inventory_no=p["number"], serial_no=p["serial"], note=p["note"])
            await _insert(request, session, me, who, one, where)
    return {"created": len(parsed)}


# ------------------------------------------------------------------ changes ---
class AssetPatch(BaseModel):
    product_id: UUID | None = Field(default=None, description="Марка и модель из каталога; null — не названа")
    inventory_no: str | None = Field(default=None, min_length=1, max_length=60)
    serial_no: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=2000)
    props: dict | None = Field(default=None, description="Только изменяемые свойства: {ключ: значение}")
    version: int


async def _apply(session, a, who: dict, values: dict, action: str = "changed", **history) -> object:
    """Write the changed fields, the history entry and the event; returns the row."""
    plain = lambda x: str(x) if isinstance(x, UUID) else x          # noqa: E731 — identifiers go to the history as text
    changes = {k: [plain(getattr(a, k)), plain(v)] for k, v in values.items() if getattr(a, k) != v}
    if "props" in changes:
        was, now = changes.pop("props")
        changes.update({f"props.{k}": [was.get(k), now.get(k)] for k in {*was, *now} if was.get(k) != now.get(k)})
    if not changes:
        return a
    new = (await session.execute(update(assets).where(assets.c.id == a.id).values(
        **values, version=assets.c.version + 1, updated_at=func.now()).returning(assets))).one()
    await core.record(session, a.id, who, action, changes, **history)
    await emit(session, "assets.asset.changed", ("asset", a.id),
               {"asset_id": str(a.id), "fields": sorted(changes)}, **core.scope_fields(new))
    return new


@router.patch("/assets/{asset_id}", tags=["assets"], summary="Изменить номера, примечание, свойства — каждое по своим правам")
async def patch_asset(asset_id: UUID, body: AssetPatch, request: Request, me: Identity = Depends(forbid_guests)) -> dict:
    scopes, who = await _scopes(request, me), await core.actor(request, me)
    sent = body.model_dump(exclude={"version"}, exclude_unset=True)
    try:
        async with request.app.state.db.begin() as session:
            a = await _asset(session, asset_id, scopes, lock=True)
            _stale(a, body.version)
            values: dict = {}
            if "inventory_no" in sent or "serial_no" in sent:
                _need(scopes, "manage", core.chain(a), "Номера меняет администратор здания")
                values.update({k: sent[k] for k in ("inventory_no", "serial_no") if k in sent})
            if "product_id" in sent:
                _need(scopes, "manage", core.chain(a), "Модель объекта меняет администратор здания")
                product_id, product_name = await core.product_of(request, a.type_id, sent["product_id"])
                values.update(product_id=product_id, product_name=product_name)
            if "note" in sent:
                _need(scopes, "edit", core.chain(a))
                values["note"] = sent["note"] or ""
            if sent.get("props"):
                kind = await core.schema_of(request, session, a.type_id)
                by_key = {p["key"]: p for p in kind.schema}
                for key in sent["props"]:
                    p = by_key.get(key)
                    need = "manage" if p is None or p["editable_by"] != "responsible" else "edit"
                    title = p["title"] if p else key
                    _need(scopes, need, core.chain(a), f"Свойство «{title}» меняет администратор здания")
                props = {**a.props, **sent["props"]}
                core.check_props(kind.schema, props, changed=set(sent["props"]))
                props = {k: v for k, v in props.items() if v is not None and v != ""}
                values.update(props=props, needs_fill=core.incomplete(kind.schema, props), schema_version=kind.schema_version)
            return core.asset_json(await _apply(session, a, who, values))
    except IntegrityError as ex:
        raise _taken(ex) or ex from ex


class StateIn(BaseModel):
    state: str = Field(pattern="^(" + "|".join(STATES) + ")$")
    version: int


@router.post("/assets/{asset_id}/state", tags=["assets"], summary="Сменить состояние; «списан» — администратор здания")
async def set_state(asset_id: UUID, body: StateIn, request: Request, me: Identity = Depends(forbid_guests)) -> dict:
    scopes, who = await _scopes(request, me), await core.actor(request, me)
    async with request.app.state.db.begin() as session:
        a = await _asset(session, asset_id, scopes, lock=True)
        _stale(a, body.version)
        retiring = body.state == "retired"
        _need(scopes, "manage" if retiring or a.state == "retired" else "edit", core.chain(a),
              "Списывает объекты администратор здания")
        if a.state == body.state:
            return core.asset_json(a)
        new = (await session.execute(update(assets).where(assets.c.id == asset_id).values(
            state=body.state, retired_at=func.now() if retiring else None, version=assets.c.version + 1,
            updated_at=func.now()).returning(assets))).one()
        await core.record(session, asset_id, who, "retired" if retiring else "state", {"state": [a.state, body.state]})
        if retiring:
            # what stood inside stays in the room, to be placed anew
            inside = (await session.execute(update(assets).where(assets.c.container_id == asset_id).values(
                container_id=None, x=a.x, y=a.y, needs_placement=True, version=assets.c.version + 1,
                updated_at=func.now()).returning(assets))).all()
            for child in inside:
                await core.record(session, child.id, core.SYSTEM, "system", {"container_id": [str(asset_id), None]},
                                  reason=f"Списан объект {a.inventory_no}, в котором он стоял")
                await emit(session, "assets.asset.changed", ("asset", child.id),
                           {"asset_id": str(child.id), "fields": ["container_id", "needs_placement"]},
                           **core.scope_fields(child))
        await emit(session, "assets.asset.retired" if retiring else "assets.asset.state_changed", ("asset", asset_id),
                   {"asset_id": str(asset_id), "from": a.state, "to": body.state}, **core.scope_fields(new))
    return core.asset_json(new)


class ResponsibleIn(BaseModel):
    person_id: UUID | None
    version: int


@router.post("/assets/{asset_id}/responsible", tags=["assets"], summary="Назначить или снять ответственного")
async def set_responsible(asset_id: UUID, body: ResponsibleIn, request: Request,
                          me: Identity = Depends(forbid_guests)) -> dict:
    scopes, who = await _scopes(request, me), await core.actor(request, me)
    async with request.app.state.db.begin() as session:
        a = await _asset(session, asset_id, scopes, lock=True)
        _stale(a, body.version)
        _need(scopes, "manage", core.chain(a), "Ответственного назначает администратор здания")
        if a.responsible_id == body.person_id:
            return core.asset_json(a)
        new = (await session.execute(update(assets).where(assets.c.id == asset_id).values(
            responsible_id=body.person_id, version=assets.c.version + 1, updated_at=func.now()).returning(assets))).one()
        was, now = (str(v) if v else None for v in (a.responsible_id, body.person_id))
        await core.record(session, asset_id, who, "responsible", {"responsible_id": [was, now]})
        await emit(session, "assets.asset.responsible_changed", ("asset", asset_id),
                   {"asset_id": str(asset_id), "from": was, "to": now}, **core.scope_fields(new))
    return core.asset_json(new)


class MoveIn(Place):
    version: int


@router.post("/assets/{asset_id}/move", tags=["assets"],
             summary="Переместить: в точку этажа или внутрь контейнера; вложенные объекты переезжают вместе")
async def move(asset_id: UUID, body: MoveIn, request: Request, me: Identity = Depends(forbid_guests)) -> dict:
    scopes, who = await _scopes(request, me), await core.actor(request, me)
    async with request.app.state.db.begin() as session:
        a = await _asset(session, asset_id, scopes, lock=True)
        _stale(a, body.version)
        kind = await core.schema_of(request, session, a.type_id)
        if body.container_id == asset_id:
            raise Problem(422, "invalid", "Объект нельзя вложить в самого себя")
        where = await _where(request, session, scopes, body)
        if kind.portable:           # whoever answers for it moves it to any room they see
            _need(scopes, "move_portable", core.chain(a), "Перемещать объект может ответственный или администратор здания")
            _need(scopes, "view", _area(where), "Нет доступа к помещению, куда перемещается объект")
        else:
            _need(scopes, "manage", core.chain(a), "Стационарные объекты перемещает администратор здания")
            _need(scopes, "manage", _area(where), "Стационарные объекты перемещает администратор здания")
        new = (await session.execute(update(assets).where(assets.c.id == asset_id).values(
            **where, needs_placement=False, version=assets.c.version + 1, updated_at=func.now()).returning(assets))).one()
        keys = ("room_id", "floor_id", "building_id", "x", "y", "container_id")
        changes = {k: [str(getattr(a, k)) if isinstance(getattr(a, k), UUID) else getattr(a, k),
                       str(where[k]) if isinstance(where[k], UUID) else where[k]] for k in keys if getattr(a, k) != where[k]}
        await core.record(session, asset_id, who, "moved", changes)
        inside = (await session.execute(update(assets).where(assets.c.container_id == asset_id).values(
            building_id=new.building_id, floor_id=new.floor_id, room_id=new.room_id, version=assets.c.version + 1,
            updated_at=func.now()).returning(assets))).all()
        for moved in (new, *inside):
            await emit(session, "assets.asset.moved", ("asset", moved.id),
                       {"asset_id": str(moved.id), "from_room_id": str(a.room_id), "to_room_id": str(new.room_id),
                        "from_building_id": str(a.building_id)}, **core.scope_fields(moved))
    return core.asset_json(new)


# ------------------------------------------------------------------ history ---
@router.get("/assets/{asset_id}/history", tags=["history"], summary="История объекта: кто, когда, что было и стало")
async def history(asset_id: UUID, request: Request, me: Identity = Depends(forbid_guests)) -> dict:
    scopes = await _scopes(request, me, reading=True)
    async with request.app.state.db.begin() as session:
        await _asset(session, asset_id, scopes)
        rows = (await session.execute(select(asset_history).where(asset_history.c.asset_id == asset_id)
                                      .order_by(asset_history.c.at.desc(), asset_history.c.id.desc()).limit(500))).all()
    return {"items": [{"id": str(h.id), "at": core.iso(h.at), "action": h.action, "changes": h.changes,
                       "actor": {"kind": h.actor_kind, "id": h.actor_id,
                                 "person_id": str(h.actor_person_id) if h.actor_person_id else None},
                       "reverts": str(h.reverts) if h.reverts else None, "reason": h.reason} for h in rows]}


@router.post("/assets/{asset_id}/history/{entry_id}/revert", tags=["history"],
             summary="Откатить изменение — если с тех пор эти поля не менялись")
async def revert(asset_id: UUID, entry_id: UUID, request: Request, me: Identity = Depends(forbid_guests)) -> dict:
    scopes, who = await _scopes(request, me), await core.actor(request, me)
    async with request.app.state.db.begin() as session:
        a = await _asset(session, asset_id, scopes, lock=True)
        _need(scopes, "manage", core.chain(a), "Откатывает изменения администратор здания")
        h = (await session.execute(select(asset_history).where(
            asset_history.c.id == entry_id, asset_history.c.asset_id == asset_id))).one_or_none()
        if h is None or h.action not in ("changed", "state", "reverted"):
            raise Problem(404, "not_found", "Такое изменение нельзя откатить")
        values, props = {}, dict(a.props)
        for field, (was, now) in h.changes.items():
            current = a.props.get(field[6:]) if field.startswith("props.") else getattr(a, field)
            if current != now:
                raise Problem(409, "changed_since", f"Поле «{field}» с тех пор изменилось — откатить нельзя")
            if field.startswith("props."):
                props = {k: v for k, v in {**props, field[6:]: was}.items() if v is not None}
            else:
                values[field] = was
        if props != a.props:
            kind = await core.schema_of(request, session, a.type_id)
            values.update(props=props, needs_fill=core.incomplete(kind.schema, props))
        return core.asset_json(await _apply(session, a, who, values, "reverted", reverts=entry_id))


# -------------------------------------------------------------------- files ---
def file_json(f) -> dict:
    return {"id": str(f.id), "asset_id": str(f.asset_id), "kind": f.kind, "name": f.name, "mime": f.mime, "size": f.size,
            "uploaded_at": core.iso(f.uploaded_at)}


@router.get("/assets/{asset_id}/files", tags=["files"], summary="Фотографии и документы объекта")
async def list_files(asset_id: UUID, request: Request, me: Identity = Depends(forbid_guests)) -> dict:
    scopes = await _scopes(request, me, reading=True)
    async with request.app.state.db.begin() as session:
        await _asset(session, asset_id, scopes)
        rows = (await session.execute(select(asset_files).where(asset_files.c.asset_id == asset_id)
                                      .order_by(asset_files.c.uploaded_at))).all()
    return {"items": [file_json(f) for f in rows]}


@router.post("/assets/{asset_id}/files", status_code=201, tags=["files"], summary="Приложить фото или документ")
async def add_file(asset_id: UUID, request: Request, file: UploadFile = File(...),
                   me: Identity = Depends(forbid_guests)) -> dict:
    scopes, who = await _scopes(request, me), await core.actor(request, me)
    data = await file.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise Problem(413, "too_large", "Файл больше 25 МБ", title="Файл слишком большой")
    if not data:
        raise Problem(422, "invalid", "Файл пуст", errors=[{"field": "file", "message": "пуст"}])
    mime, name, file_id = file.content_type or "application/octet-stream", (file.filename or "file")[:200], uuid7()
    async with request.app.state.db.begin() as session:
        a = await _asset(session, asset_id, scopes, lock=True)
        _need(scopes, "edit", core.chain(a))
        key = f"assets/{asset_id}/{file_id}"
        await asyncio.to_thread(storage.bucket().put_bytes, key, data, mime)
        f = (await session.execute(insert(asset_files).values(
            id=file_id, asset_id=asset_id, kind="photo" if mime.startswith("image/") else "document", name=name,
            mime=mime, size=len(data), storage_key=key, uploaded_by=me.sub).returning(asset_files))).one()
        await core.record(session, asset_id, who, "file_added", {"file": [None, name]})
        await emit(session, "assets.asset.file_added", ("asset", asset_id),
                   {"asset_id": str(asset_id), "file_id": str(file_id), "kind": f.kind}, **core.scope_fields(a))
    return file_json(f)


async def _file(session, file_id: UUID, scopes: dict):
    f = (await session.execute(select(asset_files).where(asset_files.c.id == file_id))).one_or_none()
    if f is None:
        raise Problem(404, "not_found", "Файл не найден")
    return f, await _asset(session, f.asset_id, scopes)


@router.get("/files/{file_id}", tags=["files"], response_class=StreamingResponse, summary="Файл объекта")
async def get_file(file_id: UUID, request: Request, me: Identity = Depends(forbid_guests)) -> StreamingResponse:
    from urllib.parse import quote
    scopes = await _scopes(request, me, reading=True)
    async with request.app.state.db.begin() as session:
        f, _ = await _file(session, file_id, scopes)
    headers = {"Content-Length": str(f.size), "Cache-Control": "private, max-age=3600",
               "Content-Disposition": f"inline; filename*=UTF-8''{quote(f.name)}"}
    return StreamingResponse(iterate_in_threadpool(storage.bucket().stream(f.storage_key)), media_type=f.mime, headers=headers)


@router.delete("/files/{file_id}", status_code=204, tags=["files"], summary="Убрать файл")
async def delete_file(file_id: UUID, request: Request, me: Identity = Depends(forbid_guests)) -> None:
    scopes, who = await _scopes(request, me), await core.actor(request, me)
    async with request.app.state.db.begin() as session:
        f, a = await _file(session, file_id, scopes)
        _need(scopes, "edit", core.chain(a))
        await session.execute(delete(asset_files).where(asset_files.c.id == file_id))
        await core.record(session, a.id, who, "file_removed", {"file": [f.name, None]})
        await emit(session, "assets.asset.file_removed", ("asset", a.id),
                   {"asset_id": str(a.id), "file_id": str(file_id), "kind": f.kind}, **core.scope_fields(a))
