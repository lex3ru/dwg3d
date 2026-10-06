"""Reports assembled from what the services tell the user — never more than they may see
(docs/TZ.md, 4.10): the list of objects in Excel, the sheet of a room in PDF, the drawing with objects.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from io import BytesIO
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from twin_chassis import Problem

from .services import ask, every, required
from .sessions import Signed, not_guest

router = APIRouter()
STATES = {"in_use": "в работе", "faulty": "неисправен", "in_repair": "в ремонте", "in_storage": "на складе",
          "retired": "списан"}
FILTERS = ("building_id", "floor_id", "room_id", "type_id", "category_id", "state", "responsible_id", "container_id",
           "needs_placement", "needs_fill", "q")


def _file(data: bytes, filename: str, media: str) -> Response:
    return Response(data, media_type=media,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


async def _names(request: Request, who: Signed, ids: set[str]) -> tuple[dict[str, str], bool]:
    """Full names of people by id; the second value says whether the people service answered."""
    if not ids:
        return {}, True
    r = await ask(request, who, "people", "/people/batch-get", method="POST", json={"ids": sorted(ids)})
    if not r.ok:
        return {}, False
    return {p["id"]: p["full_name"] for p in r.body.get("items") or []}, True


async def _types(request: Request, who: Signed, ids: set[str]) -> dict[str, dict]:
    if not ids:
        return {}
    r = await ask(request, who, "catalog", "/types/batch-get", method="POST", json={"ids": sorted(ids)})
    return {t["id"]: t for t in r.body.get("items") or []} if r.ok else {}


def _places(tree: dict | None) -> tuple[dict[str, dict], dict[str, dict]]:
    floors, rooms = {}, {}
    for f in (tree or {}).get("floors") or []:
        floors[f["id"]] = f
        for r in f.get("rooms") or []:
            rooms[r["id"]] = {**r, "floor": f}
    return floors, rooms


def _show(v) -> str:
    return "" if v is None else "да" if v is True else "нет" if v is False else str(v)


# ------------------------------------------------------------------- Excel ---
def _workbook(items: list[dict], types: dict, floors: dict, rooms: dict, names: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    columns: list[tuple[str, str]] = []            # (type id or "", key) -> one column per distinct title
    titles: dict[str, tuple[str, str, str]] = {}   # title -> (kind, source, key)
    for t in types.values():
        for p in t.get("schema") or []:
            title = p["title"] + (f", {p['unit']}" if p.get("unit") else "")
            if title not in titles:
                titles[title] = (p.get("kind", "text"), p.get("stored", "asset"), p["key"])
                columns.append((title, p["key"]))
    head = ["Тип", "Инвентарный номер", "Серийный номер", "Состояние", "Этаж", "Помещение", "Ответственный",
            "Требует", "Примечание", "QR-код", *[title for title, _ in columns]]
    wb = Workbook()
    ws = wb.active
    ws.title = "Объекты"
    ws.append(head)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for a in items:
        room, floor = rooms.get(a["room_id"]), floors.get(a["floor_id"])
        flags = (("размещения", a.get("needs_placement")), ("заполнения", a.get("needs_fill")))
        needs = ", ".join(x for x, on in flags if on)
        t = types.get(a["type_id"]) or {}
        row = [a["type_name"], a["inventory_no"], a.get("serial_no") or "", STATES.get(a["state"], a["state"]),
               (floor or {}).get("name") or "", (room or {}).get("name") or "",
               names.get(a.get("responsible_id") or "", ""), needs, a.get("note") or "", a.get("qr_code") or ""]
        schema = {p["key"]: p for p in t.get("schema") or []}
        for _, key in columns:
            p = schema.get(key)
            if p is None:
                row.append("")
                continue
            value = (t.get("values") or {}).get(key) if p.get("stored") == "type" else (a.get("props") or {}).get(key)
            if p.get("kind") == "choice":
                value = next((o["title"] for o in p.get("options") or [] if o["value"] == value), value)
            elif p.get("kind") == "person":
                value = names.get(value or "", value)
            row.append(value if isinstance(value, int | float) and not isinstance(value, bool) else _show(value))
        ws.append(row)
    for n, title in enumerate(head, start=1):
        ws.column_dimensions[get_column_letter(n)].width = max(12, min(40, len(title) + 4))
    ws.freeze_panes = "A2"
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


@router.get("/api/reports/assets.xlsx", tags=["reports"], response_class=Response,
            responses={200: {"content": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}}}},
            summary="Список объектов в Excel по тем же фильтрам, что у списка; свойства — отдельными столбцами")
async def assets_xlsx(request: Request, building_id: UUID, who: Signed = Depends(not_guest)) -> Response:
    params = {k: v for k, v in request.query_params.items() if k in FILTERS or k.startswith("prop.")}
    items = await every(request, who, "assets", "/assets", params)
    tree = await ask(request, who, "buildings", f"/buildings/{building_id}/tree")
    floors, rooms = _places(tree.body if tree.ok else None)
    types, (names, _) = await asyncio.gather(
        _types(request, who, {a["type_id"] for a in items}),
        _names(request, who, {a["responsible_id"] for a in items if a.get("responsible_id")}))
    data = await asyncio.to_thread(_workbook, items, types, floors, rooms, names)
    return _file(data, f"объекты-{datetime.now():%Y-%m-%d}.xlsx",
                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ------------------------------------------------------------- room sheet ---
def _sheet(building: dict, floor: dict, room: dict, items: list[dict], names: dict, partial: bool) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from twin_chassis import pdf

    pdf.register_fonts()
    out = BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm,
                            bottomMargin=15 * mm, title=f"Ведомость: {room.get('name') or 'помещение'}")
    h1 = ParagraphStyle("h1", fontName=pdf.BOLD, fontSize=14, leading=18, alignment=TA_LEFT)
    body = ParagraphStyle("body", fontName=pdf.FONT, fontSize=9, leading=12)
    small = ParagraphStyle("small", fontName=pdf.FONT, fontSize=8, leading=10, textColor=colors.grey)
    parts = (building.get("name"), floor.get("name"), room.get("name") or "помещение без названия")
    where = " · ".join(x for x in parts if x)
    story = [Paragraph("Ведомость объектов помещения", h1), Paragraph(where, body),
             Paragraph(f"Составлена {datetime.now():%d.%m.%Y %H:%M} · объектов: {len(items)}", small),
             Spacer(1, 6 * mm)]
    rows = [["№", "Тип", "Инвентарный №", "Серийный №", "Состояние", "Ответственный", "Отметка"]]
    for n, a in enumerate(items, start=1):
        rows.append([str(n), Paragraph(a["type_name"], body), a["inventory_no"], a.get("serial_no") or "",
                     STATES.get(a["state"], a["state"]),
                     Paragraph(names.get(a.get("responsible_id") or "", "—"), body), ""])
    table = Table(rows, colWidths=[9 * mm, 45 * mm, 30 * mm, 28 * mm, 22 * mm, 36 * mm, 10 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), pdf.BOLD), ("FONTNAME", (0, 1), (-1, -1), pdf.FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
        ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(table)
    if partial:
        story += [Spacer(1, 3 * mm), Paragraph("Имена ответственных недоступны: сервис людей не ответил.", small)]
    story += [Spacer(1, 12 * mm),
              Paragraph("Ответственный за помещение ______________________ / ______________________", body),
              Spacer(1, 6 * mm),
              Paragraph("Проверил ______________________ / ______________________ · дата ______________", body)]
    doc.build(story)
    return out.getvalue()


@router.get("/api/reports/rooms/{room_id}/sheet.pdf", tags=["reports"], response_class=Response,
            responses={200: {"content": {"application/pdf": {}}}},
            summary="Ведомость помещения в PDF: объекты, номера, состояние, ответственные, место для подписи")
async def room_sheet(room_id: UUID, request: Request, who: Signed = Depends(not_guest)) -> Response:
    room = required(await ask(request, who, "buildings", f"/rooms/{room_id}"), "buildings")
    building, tree, items = await asyncio.gather(
        ask(request, who, "buildings", f"/buildings/{room['building_id']}"),
        ask(request, who, "buildings", f"/buildings/{room['building_id']}/tree"),
        every(request, who, "assets", "/assets", {"room_id": str(room_id)}))
    floors, _ = _places(tree.body if tree.ok else None)
    names, people_ok = await _names(request, who, {a["responsible_id"] for a in items if a.get("responsible_id")})
    data = await asyncio.to_thread(_sheet, building.body if building.ok else {}, floors.get(room["floor_id"]) or {},
                                   room, items, names, not people_ok)
    return _file(data, f"ведомость-{room.get('name') or room_id}.pdf", "application/pdf")


# ---------------------------------------------------------------- drawing ---
class DrawingReport(BaseModel):
    drawing_id: UUID
    format: str = Field(default="dxf", pattern="^(dxf|dwg)$")


@router.post("/api/reports/buildings/{building_id}/drawing", tags=["reports"], response_class=Response,
             summary="Чертёж с объектами (DXF или DWG): объекты — блоками с атрибутами на своих местах")
async def drawing_with_objects(building_id: UUID, body: DrawingReport, request: Request,
                               who: Signed = Depends(not_guest)) -> Response:
    tree = required(await ask(request, who, "buildings", f"/buildings/{building_id}/tree"), "buildings")
    floors, rooms = _places(tree)
    mine = {fid: f for fid, f in floors.items() if f.get("drawing_id") == str(body.drawing_id)}
    if not mine:
        raise Problem(404, "not_found", "Чертёж не найден в этом здании")
    items = [a for a in await every(request, who, "assets", "/assets", {"building_id": str(building_id)})
             if a["floor_id"] in mine and a.get("x") is not None]
    types, (names, _) = await asyncio.gather(
        _types(request, who, {a["type_id"] for a in items}),
        _names(request, who, {a["responsible_id"] for a in items if a.get("responsible_id")}))
    objects = [{"floor": mine[a["floor_id"]].get("candidate"), "at": [a["x"], a["y"]], "angle": a.get("angle") or 0,
                "type": a["type_id"], "name": a["type_name"], "inventory_no": a["inventory_no"],
                "state": STATES.get(a["state"], a["state"]),
                "responsible": names.get(a.get("responsible_id") or "", ""),
                "room": (rooms.get(a["room_id"]) or {}).get("name") or "", "note": a.get("note") or ""} for a in items]
    sizes = {tid: {"id": tid, "w": (t.get("size") or [0.5, 0.5])[0], "d": (t.get("size") or [0.5, 0.5])[1]}
             for tid, t in types.items()}
    for a in items:                                      # a type the catalog did not name: a half-metre square
        sizes.setdefault(a["type_id"], {"id": a["type_id"], "w": 0.5, "d": 0.5})
    base = request.app.state.config.services.get("import")
    if base is None:
        raise Problem(503, "service_unavailable", "Сервис «import» недоступен", extra={"service": "import"})
    try:
        r = await request.app.state.http.post(f"{base}/api/import/v1/drawings/{body.drawing_id}/export", timeout=600,
                                              json={"format": body.format, "objects": objects, "types": sizes},
                                              headers={"Authorization": f"Bearer {who.token}"})
    except Exception as ex:
        raise Problem(503, "service_unavailable", "Сервис «import» недоступен", extra={"service": "import"}) from ex
    if r.status_code != 200:
        problem = r.json() if r.headers.get("content-type", "").startswith("application/problem+json") else {}
        raise Problem(r.status_code if r.status_code < 500 else 503, problem.get("code", "error"),
                      problem.get("detail", "Сервис «import» не смог записать чертёж"))
    name = r.headers.get("content-disposition", "")
    filename = name.partition("filename*=UTF-8''")[2] or f"drawing.{body.format}"
    from urllib.parse import unquote
    return Response(r.content, media_type=r.headers.get("content-type", "application/octet-stream"),
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(unquote(filename))}",
                             "X-Objects-Drawn": r.headers.get("x-objects-drawn", ""),
                             "X-Objects-Skipped": r.headers.get("x-objects-skipped", "")})
