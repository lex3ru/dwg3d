import json
import re
import uuid
from datetime import date
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import uploads
from app.core.auth import Admin, CurrentActor
from app.core.db import DB
from app.core.errors import AppError
from app.modules.files import api as files
from app.modules.inventory import api, cost, counts, documents, excel, places, printing, units
from app.modules.inventory.rules import doc_title
from app.modules.system import api as system

router = APIRouter(prefix="/api/inventory", tags=["inventory"])
qr = APIRouter(prefix="/api/q", tags=["inventory"])


def _xlsx(data: bytes, name: str) -> Response:
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )


def _pdf(data: bytes, name: str) -> Response:
    return Response(
        data,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(name)}"},
    )


# ---------------------------------------------------------------- места хранения


@router.get("/places")
def place_tree(actor: CurrentActor, session: DB) -> Response:
    """Места для выбора: здания → этажи (верхний первым) → помещения, склады с ячейками.
    Здания с помещениями — готовым JSON из базы, склады (их единицы) — как обычно; три запроса
    на любое число этажей и складов (8.1, R-036, ADR-0019)."""
    stores = places.warehouse_views(session, places.warehouses(session, actor))
    stores_json = json.dumps(jsonable_encoder(stores), ensure_ascii=False, separators=(",", ":"))
    body = f'{{"buildings":{places.buildings_json(session, actor)},"warehouses":{stores_json}}}'
    return Response(body, media_type="application/json")


@router.get("/place")
def place_contents(key: str, actor: CurrentActor, session: DB) -> dict[str, Any]:
    """Что числится в месте (6.5.5): единицы и остатки."""
    info = places.Places(session, actor).get(key)
    return {
        "place": info.view(),
        "units": units.registry(session, actor, place=key, limit=2000)["items"],
        "balances": documents.balances(session, actor, place=key),
    }


class WarehouseIn(BaseModel):
    version: int | None = None
    name: str | None = Field(default=None, max_length=150)
    building_id: uuid.UUID | None = None
    room_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=300)
    archived: bool | None = None


@router.post("/warehouses", status_code=201)
def create_warehouse(body: WarehouseIn, actor: Admin, session: DB) -> dict[str, Any]:
    wh = places.create_warehouse(session, actor, body.model_dump(exclude_unset=True))
    return places.warehouse_view(session, wh)


@router.patch("/warehouses/{wh_id}")
def update_warehouse(
    wh_id: uuid.UUID, body: WarehouseIn, actor: Admin, session: DB
) -> dict[str, Any]:
    wh = places.update_warehouse(session, actor, wh_id, body.model_dump(exclude_unset=True))
    return places.warehouse_view(session, wh)


class CellIn(BaseModel):
    name: str = Field(max_length=100)


@router.post("/warehouses/{wh_id}/cells", status_code=201)
def add_cell(wh_id: uuid.UUID, body: CellIn, actor: Admin, session: DB) -> dict[str, Any]:
    places.add_cell(session, actor, wh_id, body.name)
    return places.warehouse_view(session, places.get_warehouse(session, actor, wh_id))


@router.delete("/cells/{cell_id}", status_code=204)
def remove_cell(cell_id: uuid.UUID, actor: Admin, session: DB) -> None:
    places.remove_cell(session, actor, cell_id)


# ---------------------------------------------------------------- инвентарные единицы


def _filters(
    building_id: uuid.UUID | None = None,
    floor_id: uuid.UUID | None = None,
    place: str | None = None,
    layer_id: uuid.UUID | None = None,
    type_id: uuid.UUID | None = None,
    state: str | None = None,
    responsible: str | None = None,
    department: str | None = None,
    since: date | None = None,
    until: date | None = None,
    q: str | None = None,
    written_off: bool = False,
) -> dict[str, Any]:
    return {
        "building_id": building_id,
        "floor_id": floor_id,
        "place": place,
        "layer_id": layer_id,
        "type_id": type_id,
        "state": state,
        "responsible": responsible,
        "department": department,
        "since": since,
        "until": until,
        "text": q,
        "written_off": written_off,
    }


@router.get("/units")
def registry(
    actor: CurrentActor,
    session: DB,
    sort: str = "number",
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=0, le=1000),
    building_id: uuid.UUID | None = None,
    floor_id: uuid.UUID | None = None,
    place: str | None = None,
    layer_id: uuid.UUID | None = None,
    type_id: uuid.UUID | None = None,
    state: str | None = None,
    responsible: str | None = None,
    department: str | None = None,
    since: date | None = None,
    until: date | None = None,
    q: str | None = None,
    written_off: bool = False,
) -> dict[str, Any]:
    f = _filters(
        building_id,
        floor_id,
        place,
        layer_id,
        type_id,
        state,
        responsible,
        department,
        since,
        until,
        q,
        written_off,
    )
    return units.registry(session, actor, sort=sort, offset=offset, limit=limit, **f)


@router.get("/units/export.xlsx")
def registry_export(
    actor: CurrentActor,
    session: DB,
    sort: str = "number",
    ids: str | None = None,
    building_id: uuid.UUID | None = None,
    floor_id: uuid.UUID | None = None,
    place: str | None = None,
    layer_id: uuid.UUID | None = None,
    type_id: uuid.UUID | None = None,
    state: str | None = None,
    responsible: str | None = None,
    department: str | None = None,
    since: date | None = None,
    until: date | None = None,
    q: str | None = None,
    written_off: bool = False,
) -> Response:
    f = _filters(
        building_id,
        floor_id,
        place,
        layer_id,
        type_id,
        state,
        responsible,
        department,
        since,
        until,
        q,
        written_off,
    )
    if ids:
        f["ids"] = [uuid.UUID(i) for i in ids.split(",")]
    items = units.registry(session, actor, sort=sort, limit=100_000, **f)["items"]
    return _xlsx(excel.registry_export(items, actor), "реестр-имущества.xlsx")


@router.get("/units/{unit_id}")
def get_unit(unit_id: uuid.UUID, actor: CurrentActor, session: DB) -> dict[str, Any]:
    return units.unit_view(session, actor, units.get_unit(session, actor, unit_id))


class UnitPatch(BaseModel):
    version: int
    values: dict[str, Any]


@router.patch("/units/{unit_id}")
def update_unit(unit_id: uuid.UUID, body: UnitPatch, actor: Admin, session: DB) -> dict[str, Any]:
    unit = units.update_unit(session, actor, unit_id, body.values, body.version)
    return units.unit_view(session, actor, unit)


@router.post("/changes/{change_id}/rollback")
def roll_back(change_id: uuid.UUID, actor: Admin, session: DB) -> dict[str, Any]:
    return units.unit_view(session, actor, units.roll_back(session, actor, change_id))


def _unit_file_limit(session: Session, request: Request) -> tuple[str, int]:
    photo = request.query_params.get("kind") == "photo"
    return system.upload_limit(session, "photo" if photo else "document")


UnitFileUpload = Annotated[uploads.Upload, uploads.receive(_unit_file_limit)]
DocumentUpload = Annotated[uploads.Upload, uploads.receive(
    lambda session, _: system.upload_limit(session, "document"))]
ExcelUpload = Annotated[uploads.Upload, uploads.receive(
    lambda session, _: system.upload_limit(session, "excel"))]


@router.post("/units/{unit_id}/files", status_code=201, openapi_extra=uploads.form())
def add_file(
    unit_id: uuid.UUID, actor: Admin, file: UnitFileUpload, session: DB, kind: str = "doc"
) -> dict[str, Any]:
    units.add_file(
        session,
        actor,
        unit_id,
        file.file,
        file.name or "файл",
        "photo" if kind == "photo" else "doc",
    )
    return units.unit_view(session, actor, units.get_unit(session, actor, unit_id))


@router.delete("/files/{link_id}")
def remove_file(link_id: uuid.UUID, actor: Admin, session: DB) -> dict[str, Any]:
    return units.unit_view(session, actor, units.remove_file(session, actor, link_id))


class LabelsIn(BaseModel):
    unit_ids: list[uuid.UUID] = Field(default_factory=list, max_length=5000)
    codes: list[str] = Field(default_factory=list, max_length=500)  # склады и ячейки
    room_ids: list[uuid.UUID] = Field(default_factory=list, max_length=2000)  # на двери
    mode: str = "sheet"


@router.get("/labels/address")
def label_address(request: Request, _: Admin, session: DB) -> dict[str, str]:
    """Куда ведут QR-метки и откуда этот адрес: settings, install, request (R-016)."""
    url, source = api.label_base(session, str(request.base_url))
    return {"url": url, "source": source}


@router.post("/labels.pdf")
def labels(body: LabelsIn, request: Request, actor: Admin, session: DB) -> Response:
    """QR-метки (5.4.7): листом А4 с наклейками или на принтер этикеток. Адрес меток — в
    заголовке X-Label-Url: интерфейс предупреждает, если система открыта по другому (R-016)."""
    from app.modules.catalog import api as catalog

    rows = [units.get_unit(session, actor, i) for i in body.unit_ids]
    types = catalog.types_by_id(session, [u.type_id for u in rows])
    items = [
        {"code": u.label_code, "number": u.number, "title": types[u.type_id].name} for u in rows
    ]
    for wh in places.warehouses(session, actor):
        view = places.warehouse_view(session, wh)
        if wh.label_code in body.codes:
            items.append({"code": wh.label_code, "number": "", "title": f"Склад «{wh.name}»"})
        for c in view["cells"]:
            if c["label_code"] in body.codes:
                items.append(
                    {"code": c["label_code"], "number": "", "title": f"{wh.name} › {c['name']}"}
                )
    known = places.Places(session, actor)
    for room_id in body.room_ids:
        room = known.get(places.room_key(room_id))
        items.append({"code": api.room_label(session, room_id), "number": "", "title": room.title})
    if not items:
        raise AppError("Не выбрано, что печатать.")
    base, _ = api.label_base(session, str(request.base_url))
    data = printing.labels_pdf(
        items, api.label_settings(session), base, "printer" if body.mode == "printer" else "sheet"
    )
    response = _pdf(data, "метки.pdf")
    response.headers["X-Label-Url"] = base
    return response


# ---------------------------------------------------------------- документы


@router.get("/documents")
def list_documents(
    actor: Admin,
    session: DB,
    kind: str | None = None,
    status: str | None = None,
    since: date | None = None,
    until: date | None = None,
    place: str | None = None,
    unit_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    return {
        "items": documents.documents(
            session,
            actor,
            kind=kind,
            status=status,
            since=since,
            until=until,
            place=place,
            unit_id=unit_id,
        )
    }


class DocIn(BaseModel):
    kind: str | None = None
    version: int | None = None
    header: dict[str, Any] = Field(default_factory=dict)
    lines: list[dict[str, Any]] | None = Field(default=None, max_length=5000)


@router.post("/documents", status_code=201)
def create_document(body: DocIn, actor: Admin, session: DB) -> dict[str, Any]:
    doc = documents.create_document(session, actor, body.kind or "", body.header, body.lines)
    return documents.doc_view(session, actor, doc)


@router.get("/documents/{doc_id}")
def get_document(doc_id: uuid.UUID, actor: Admin, session: DB) -> dict[str, Any]:
    return documents.doc_view(session, actor, documents.get_document(session, actor, doc_id))


@router.put("/documents/{doc_id}")
def update_document(doc_id: uuid.UUID, body: DocIn, actor: Admin, session: DB) -> dict[str, Any]:
    doc = documents.update_document(
        session, actor, doc_id, body.version or 0, body.header, body.lines
    )
    return documents.doc_view(session, actor, doc)


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: uuid.UUID, actor: Admin, session: DB) -> None:
    documents.delete_draft(session, actor, doc_id)


class VersionIn(BaseModel):
    version: int


@router.post("/documents/{doc_id}/post")
def post_document(doc_id: uuid.UUID, body: VersionIn, actor: Admin, session: DB) -> dict[str, Any]:
    return documents.doc_view(session, actor, documents.post(session, actor, doc_id, body.version))


@router.post("/documents/{doc_id}/cancel")
def cancel_document(doc_id: uuid.UUID, actor: Admin, session: DB) -> dict[str, Any]:
    back = documents.cancel(session, actor, doc_id)
    return documents.doc_view(session, actor, back)


@router.get("/documents/{doc_id}/print.pdf")
def print_document(doc_id: uuid.UUID, actor: Admin, session: DB) -> Response:
    from app.modules.system import api as system

    doc = documents.get_document(session, actor, doc_id)
    view = documents.doc_view(session, actor, doc)
    data = printing.document_pdf(view, str(system.get(session, "organization_name")))
    return _pdf(data, f"{doc_title(doc.kind, doc.number)}.pdf")


@router.post("/documents/{doc_id}/files", status_code=201, openapi_extra=uploads.form())
def document_file(
    doc_id: uuid.UUID, actor: Admin, file: DocumentUpload, session: DB
) -> dict[str, Any]:
    record = files.store(
        session,
        actor,
        file.file,
        file.name or "скан",
        {"pdf", "jpeg", "png", "webp", "heic"},
        file.limit,
    )
    documents.attach_file(session, actor, doc_id, record.id, record.name)
    return documents.doc_view(session, actor, documents.get_document(session, actor, doc_id))


# ---------------------------------------------------------------- остатки и стоимость


@router.get("/balances")
def balances(
    actor: CurrentActor,
    session: DB,
    place: str | None = None,
    at: date | None = None,
    building_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    return {
        "items": documents.balances(session, actor, place=place, at=at, building_id=building_id)
    }


@router.get("/balances/history")
def stock_history(
    place: str, type_id: uuid.UUID, actor: Admin, session: DB, model_id: uuid.UUID | None = None
) -> dict[str, Any]:
    return {"items": documents.stock_history(session, actor, place, type_id, model_id)}


@router.post("/cost", status_code=202)
def cost_statement(
    actor: Admin,
    session: DB,
    at: date | None = None,
    group_by: str = "building,floor,layer",
    building_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Ведомость стоимости на дату (5.4.5 п. 4, С19) — фоновой задачей (8.2: «идёт в фоне»,
    R-036, ADR-0021): ход и итог — /api/system/tasks/{job_id}, Excel — /cost/{job_id}.xlsx."""
    groups = [g for g in group_by.split(",") if g]
    return {"job_id": cost.start(session, actor, at or date.today(), groups, building_id)}


@router.get("/cost/{job_id}.xlsx")
def cost_export(job_id: uuid.UUID, actor: Admin, session: DB) -> Response:
    st = cost.result(session, actor, job_id)
    return _xlsx(excel.statement_export(st), f"стоимость-на-{st['at']:%d.%m.%Y}.xlsx")


# ---------------------------------------------------------------- загрузка из Excel (5.4.9)


@router.get("/import/template.xlsx")
def import_template(_: Admin) -> Response:
    return _xlsx(excel.template(), "имущество-шаблон.xlsx")


@router.post(
    "/import",
    openapi_extra=uploads.form(building_id="string", mapping="string", apply="boolean"),
)
def import_property(actor: Admin, file: ExcelUpload, session: DB) -> dict[str, Any]:
    # поля формы: здание, сопоставление типов и помещений (JSON), загружать ли
    try:
        building_id = uuid.UUID(file.fields.get("building_id", ""))
    except ValueError:
        raise AppError("Выберите здание.", field="building_id") from None
    try:
        m = json.loads(file.fields.get("mapping") or "{}")
    except ValueError:
        raise AppError("Неверное сопоставление.") from None
    apply = file.fields.get("apply", "").lower() in ("true", "1", "on", "yes")
    return excel.load(
        session, actor, file.file, building_id, m.get("types", {}), m.get("rooms", {}), apply
    )


# ---------------------------------------------------------------- QR-метки


@qr.get("/{code}")
def resolve(code: str, actor: CurrentActor, session: DB) -> dict[str, Any]:
    return api.resolve_label(session, actor, code)


# ---------------------------------------------------------------- инвентаризация (5.4.6)


class CountIn(BaseModel):
    places: list[str] = Field(default_factory=list, max_length=2000)
    floor_id: uuid.UUID | None = None
    warehouse_id: uuid.UUID | None = None


@router.get("/counts")
def list_counts(actor: Admin, session: DB, status: str | None = None) -> dict[str, Any]:
    return {"items": documents.documents(session, actor, kind="inventory", status=status)}


@router.post("/counts", status_code=201)
def create_count(body: CountIn, actor: Admin, session: DB) -> dict[str, Any]:
    doc = counts.create_count(session, actor, body.places, body.floor_id, body.warehouse_id)
    return counts.count_view(session, actor, doc.id)


@router.get("/counts/{doc_id}")
def get_count(
    doc_id: uuid.UUID, actor: Admin, session: DB, place: str | None = None
) -> dict[str, Any]:
    return counts.count_view(session, actor, doc_id, place)


def _sent(
    device: Annotated[str | None, Header(alias="X-Count-Device")] = None,
    seq: Annotated[str | None, Header(alias="X-Count-Seq")] = None,
) -> counts.Sent | None:
    """Устройство и номер отметки с телефона (ADR-0006): оба заголовка или ни одного."""
    if device is None and seq is None:
        return None
    try:
        phone = uuid.UUID(device or "")
    except ValueError:
        phone = None
    if phone is None or seq is None or not re.fullmatch(r"[1-9][0-9]{0,17}", seq):
        raise AppError("Неверное устройство или номер отметки обхода.")
    return phone, int(seq)


Sent = Annotated[counts.Sent | None, Depends(_sent)]


class ScanIn(BaseModel):
    code: str = Field(max_length=200)
    place: str | None = None


@router.post("/counts/{doc_id}/scan")
def scan(
    doc_id: uuid.UUID, body: ScanIn, sent: Sent, actor: Admin, session: DB
) -> dict[str, Any]:
    return counts.scan(session, actor, doc_id, body.code, body.place, sent)


class MarkIn(BaseModel):
    unit_id: uuid.UUID
    place: str


@router.post("/counts/{doc_id}/marks")
def mark(
    doc_id: uuid.UUID, body: MarkIn, sent: Sent, actor: Admin, session: DB
) -> dict[str, Any]:
    return counts.mark(session, actor, doc_id, body.unit_id, body.place, manual=True, sent=sent)


@router.delete("/counts/{doc_id}/marks/{unit_id}", status_code=204)
def unmark(
    doc_id: uuid.UUID, unit_id: uuid.UUID, sent: Sent, actor: Admin, session: DB
) -> Response:
    counts.unmark(session, actor, doc_id, unit_id, sent)
    return Response(status_code=204)


@router.post("/counts/{doc_id}/extras", status_code=201)
def add_extra(doc_id: uuid.UUID, body: dict[str, Any], actor: Admin, session: DB) -> dict[str, Any]:
    e = counts.add_extra(session, actor, doc_id, body)
    return {"id": e.id}


@router.delete("/counts/{doc_id}/extras/{extra_id}", status_code=204)
def remove_extra(doc_id: uuid.UUID, extra_id: uuid.UUID, actor: Admin, session: DB) -> Response:
    counts.remove_extra(session, actor, doc_id, extra_id)
    return Response(status_code=204)


class StockIn(BaseModel):
    place: str
    type_id: uuid.UUID
    model_id: uuid.UUID | None = None  # позиция — с моделью, если она у остатка есть (ADR-0005)
    counted: float | None = None


@router.put("/counts/{doc_id}/stock", status_code=204)
def set_stock(
    doc_id: uuid.UUID, body: StockIn, sent: Sent, actor: Admin, session: DB
) -> Response:
    counts.set_stock(
        session, actor, doc_id, body.place, body.type_id, body.model_id, body.counted, sent
    )
    return Response(status_code=204)


class PostIn(BaseModel):
    version: int


@router.post("/counts/{doc_id}/post")
def post_count(doc_id: uuid.UUID, body: PostIn, actor: Admin, session: DB) -> dict[str, Any]:
    doc = counts.post_count(session, actor, doc_id, body.version)
    return documents.doc_view(session, actor, doc)


@router.get("/counts/{doc_id}/statement.pdf")
def statement(doc_id: uuid.UUID, actor: Admin, session: DB) -> Response:
    data, name = counts.statement_pdf(session, actor, doc_id, system_name(session))
    return _pdf(data, name)


@router.get("/counts/{doc_id}/act.pdf")
def act(doc_id: uuid.UUID, actor: Admin, session: DB) -> Response:
    data, name = counts.act_pdf(session, actor, doc_id, system_name(session))
    return _pdf(data, name)


def system_name(session: DB) -> str:
    from app.modules.system import api as system

    return str(system.get(session, "organization_name") or "")
