"""Excel (5.4.9, 7.3, 7.4): шаблон начального наполнения, проверка и загрузка списка
имущества документом «Ввод остатков»; выгрузка реестра и ведомости стоимости."""

import difflib
import io
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, BinaryIO

from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.actor import Actor
from app.core.errors import AppError
from app.core.report import text_row
from app.modules.building import api as building
from app.modules.catalog import api as catalog
from app.modules.inventory import documents
from app.modules.inventory.models import Unit
from app.modules.inventory.places import Places, admin, room_key
from app.modules.inventory.rules import STATE_BY_TITLE, STATES
from app.modules.inventory.units import number_template

COLUMNS = [
    (
        "Инвентарный номер",
        False,
        "Пусто — система выдаст следующий свободный номер. Для вещей, "
        "учитываемых количеством, не заполняется.",
    ),
    (
        "Наименование",
        True,
        "Как называется вещь. При загрузке сопоставляется с типом каталога; "
        "несопоставленное система покажет для ручного выбора.",
    ),
    ("Модель", False, "Производитель и модель, если известны."),
    ("Слой", False, "Группа по назначению — слой плана. Для расходных материалов не заполняется."),
    (
        "Вид учёта",
        True,
        "«поштучно» — у каждой вещи свой номер; «количеством» — учитывается остаток.",
    ),
    (
        "Количество",
        True,
        "Для поштучного учёта — 1 (одна строка — одна вещь); для количественного — сколько.",
    ),
    ("Ед. изм.", True, "шт., упак., м, пачка и т. п."),
    ("Серийный номер", False, "Заводской номер, если есть."),
    ("Этаж", True, "Номер этажа."),
    ("Помещение", True, "Номер помещения по плану. Склад — тоже помещение."),
    ("Название помещения", False, "Помогает сопоставить помещение, если номера на плане другие."),
    ("Ответственный", False, "Один человек: ФИО."),
    ("Подразделение", False, "Отделение или служба ответственного."),
    ("Состояние", True, "в работе, неисправна, в ремонте, на хранении."),
    ("Цена за ед., ₽", True, "Цена приобретения одной единицы, рублей."),
    (
        "Дата ввода",
        True,
        "Когда вещь начали использовать (для количественного учёта — дата поступления).",
    ),
    ("Срок службы, мес.", False, "Пусто — берётся из типа каталога."),
    ("Стоимость, ₽", False, "Считается сама: количество × цена. При загрузке не читается."),
    ("Примечание", False, "Что угодно."),
]
HEAD = [c[0] for c in COLUMNS]
DARK = PatternFill("solid", fgColor="1F3A5F")
LIGHT = PatternFill("solid", fgColor="BFD7EA")
GREY = PatternFill("solid", fgColor="D9D9D9")


def template() -> bytes:
    wb = Workbook()
    help_ws = wb.active
    help_ws.title = "Как заполнять"
    help_ws.append(["Шаблон начального наполнения учёта имущества"])
    help_ws.append(
        [
            "Одна строка — одна вещь при поштучном учёте или одна позиция с количеством "
            "при количественном. Заполняется лист «Имущество»."
        ]
    )
    help_ws.append([])
    help_ws.append(["Столбец", "Обязательный", "Что писать"])
    for name, required, hint in COLUMNS:
        help_ws.append([name, "да" if required else "нет", hint])
    help_ws["A1"].font = Font(bold=True, size=14)
    help_ws.column_dimensions["A"].width = 24
    help_ws.column_dimensions["C"].width = 100
    ws = wb.create_sheet("Имущество")
    ws.append(HEAD)
    for i, (name, required, hint) in enumerate(COLUMNS, 1):
        cell = ws.cell(row=1, column=i)
        cell.fill = GREY if name.startswith("Стоимость") else (DARK if required else LIGHT)
        cell.font = Font(bold=True, color="FFFFFF" if required else "000000")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        cell.comment = Comment(hint, "система")
        ws.column_dimensions[cell.column_letter].width = max(12, len(name) + 4)
    for col, values in (
        ("E", "поштучно,количеством"),
        ("N", "в работе,неисправна,в ремонте,на хранении"),
    ):
        dv = DataValidation(type="list", formula1=f'"{values}"', allow_blank=True)
        dv.add(f"{col}2:{col}5000")
        ws.add_data_validation(dv)
    for r in range(2, 501):
        ws.cell(row=r, column=18, value=f"=F{r}*O{r}")
        ws.cell(row=r, column=16).number_format = "DD.MM.YYYY"
    ws.freeze_panes = "A2"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ---------------------------------------------------------------- разбор файла


def _norm(text: str) -> str:
    text = text.lower().replace("ё", "е").replace("″", '"')
    return " ".join(re.findall(r"[\w\"]+", text))


def similarity(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if na == nb:
        return 1.0
    ratio = difflib.SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    shorter = min(len(ta), len(tb)) or 1
    contain = len(ta & tb) / shorter
    return max(ratio, contain * 0.9)


@dataclass
class Row:
    n: int
    number: str
    name: str
    model: str
    layer: str
    accounting: str
    qty: Decimal
    unit: str
    serial: str
    floor: str
    room: str
    room_name: str
    responsible: str
    department: str
    state: str
    price: Decimal
    commissioned: date
    life: int | None
    note: str


@dataclass
class Parsed:
    rows: list[Row] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def parse(stream: BinaryIO) -> Parsed:
    try:
        wb = load_workbook(stream, data_only=True)
    except Exception:  # noqa: BLE001
        raise AppError("Это не файл Excel (.xlsx) или он повреждён.", code="bad_file") from None
    if "Имущество" not in wb.sheetnames:
        raise AppError(
            "В файле нет листа «Имущество» — возьмите шаблон из системы.", code="bad_file"
        )
    ws = wb["Имущество"]
    head = [_cell(c.value) for c in ws[1]]
    idx = {}
    for name in HEAD:
        if name in head:
            idx[name] = head.index(name)
        elif any(c[0] == name and c[1] for c in COLUMNS):
            raise AppError(f"Нет столбца «{name}» — возьмите шаблон из системы.", code="bad_file")
    out = Parsed()
    today = date.today()
    for n, values in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):

        def get(name: str, values: tuple[Any, ...] = values) -> Any:
            return values[idx[name]] if name in idx and idx[name] < len(values) else None

        if not any(_cell(get(h)) for h in HEAD if h != "Стоимость, ₽"):
            continue
        errs = []
        name = _cell(get("Наименование"))
        if not name:
            errs.append("нет наименования")
        accounting = _cell(get("Вид учёта")).lower()
        if accounting not in ("поштучно", "количеством"):
            errs.append("вид учёта — «поштучно» или «количеством»")
        try:
            qty = Decimal(_cell(get("Количество")).replace(",", ".") or "1")
            if qty <= 0:
                raise InvalidOperation
        except InvalidOperation:
            errs.append("количество — число больше нуля")
            qty = Decimal(1)
        state_title = _cell(get("Состояние")).lower() or "в работе"
        if state_title not in STATE_BY_TITLE or state_title == "списана":
            errs.append("состояние — в работе, неисправна, в ремонте или на хранении")
        try:
            price = Decimal(_cell(get("Цена за ед., ₽")).replace(" ", "").replace(",", "."))
            if price < 0:
                raise InvalidOperation
        except InvalidOperation:
            errs.append("нет цены")
            price = Decimal(0)
        raw_date = get("Дата ввода")
        commissioned = today
        if isinstance(raw_date, datetime):
            commissioned = raw_date.date()
        elif isinstance(raw_date, date):
            commissioned = raw_date
        elif _cell(raw_date):
            try:
                commissioned = datetime.strptime(_cell(raw_date), "%d.%m.%Y").date()
            except ValueError:
                errs.append("дата ввода — ДД.ММ.ГГГГ")
        else:
            errs.append("нет даты ввода")
        if commissioned > today:
            errs.append("дата ввода — в будущем")
        life_raw = _cell(get("Срок службы, мес."))
        life = None
        if life_raw:
            try:
                life = int(float(life_raw))
            except ValueError:
                errs.append("срок службы — число месяцев")
        if not _cell(get("Этаж")) or not _cell(get("Помещение")):
            errs.append("нет этажа или помещения")
        for e in errs:
            out.errors.append({"row": n, "message": e})
        out.rows.append(
            Row(
                n=n,
                number=_cell(get("Инвентарный номер")),
                name=name,
                model=_cell(get("Модель")),
                layer=_cell(get("Слой")),
                accounting=accounting,
                qty=qty,
                unit=_cell(get("Ед. изм.")),
                serial=_cell(get("Серийный номер")),
                floor=_cell(get("Этаж")),
                room=_cell(get("Помещение")),
                room_name=_cell(get("Название помещения")),
                responsible=_cell(get("Ответственный")),
                department=_cell(get("Подразделение")),
                state=STATE_BY_TITLE.get(state_title, "in_use"),
                price=price,
                commissioned=commissioned,
                life=life,
                note=_cell(get("Примечание")),
            )
        )
    if not out.rows:
        raise AppError("В листе «Имущество» нет строк.", code="bad_file")
    return out


# ---------------------------------------------------------------- сопоставление


def _floor_number(name: str) -> str | None:
    m = re.search(r"-?\d+", name)
    return m.group(0) if m else None


def match(session: Session, actor: Actor, parsed: Parsed, building_id: uuid.UUID) -> dict[str, Any]:
    """Что с чем сопоставится: наименования — с типами каталога, помещения — с планом."""
    b = building.get_building(session, actor, building_id)
    types = [t for t in catalog.all_types(session) if t.archived_at is None]
    names: dict[str, dict[str, Any]] = {}
    for row in parsed.rows:
        if row.name in names:
            names[row.name]["rows"].append(row.n)
            continue
        scored = sorted(((similarity(row.name, t.name), t) for t in types), key=lambda x: -x[0])
        best = scored[0] if scored else (0.0, None)
        how = "exact" if best[0] >= 1.0 else ("similar" if best[0] >= 0.6 else "none")
        names[row.name] = {
            "name": row.name,
            "layer": row.layer,
            "accounting": row.accounting,
            "unit": row.unit,
            "rows": [row.n],
            "how": how,
            "type_id": best[1].id if best[1] is not None and how != "none" else None,
            "candidates": [
                {"type_id": t.id, "name": t.name, "score": round(s, 2)}
                for s, t in scored[:5]
                if s > 0.3
            ],
        }
    floors = building.floors(session, b.id)
    rooms_by_floor: dict[str, list[Any]] = {}
    for f in floors:
        key = _floor_number(f.name) or str(f.position)
        rooms_by_floor.setdefault(key, []).extend(building.live_rooms(session, f.id))
    places = Places(session, actor)
    rooms: dict[str, dict[str, Any]] = {}
    for row in parsed.rows:
        key = f"{row.floor}|{row.room}"
        if key in rooms:
            rooms[key]["rows"].append(row.n)
            continue
        candidates = rooms_by_floor.get(row.floor, [])
        exact = [r for r in candidates if r.number and r.number.strip().lower() == row.room.lower()]
        by_name = sorted(
            (
                (similarity(row.room_name, r.name), r)
                for r in candidates
                if row.room_name and r.name
            ),
            key=lambda x: -x[0],
        )
        chosen, how, confirm = None, "none", False
        if exact:
            chosen, how = exact[0], "exact"
            # R-002, ТЗ 4.6 п. 1: номер совпал, название другое — кабинет мог смениться;
            # порог выше, чем у поиска по названию: «невролога» ↔ «кардиолога» — 0,8
            if row.room_name and chosen.name and similarity(row.room_name, chosen.name) < 0.9:
                how, confirm = "similar", True
        elif by_name and by_name[0][0] >= 0.75:
            chosen, how = by_name[0][1], "similar"
        rooms[key] = {
            "key": key,
            "floor": row.floor,
            "room": row.room,
            "room_name": row.room_name,
            "rows": [row.n],
            "how": how,
            "confirm": confirm,
            "place": room_key(chosen.id) if chosen else None,
            "place_title": places.title(room_key(chosen.id)) if chosen else None,
        }
    return {
        "building": {"id": b.id, "name": b.name},
        "names": list(names.values()),
        "rooms": list(rooms.values()),
    }


# ---------------------------------------------------------------- загрузка (5.4.9 п. 3)


def load(
    session: Session,
    actor: Actor,
    stream: BinaryIO,
    building_id: uuid.UUID,
    types: dict[str, str],
    rooms: dict[str, str],
    apply: bool,
) -> dict[str, Any]:
    """Проверка (apply=False) или загрузка: всё или ничего. types — наименование → ключ
    типа или «new» (создать тип); rooms — «этаж|помещение» → ключ места."""
    admin(actor)
    parsed = parse(stream)
    matched = match(session, actor, parsed, building_id)
    errors = list(parsed.errors)
    template = number_template(session)
    taken = set(session.scalars(select(Unit.number)))
    seen: set[str] = set()
    for row in parsed.rows:
        if row.number:
            if row.number in taken:
                errors.append(
                    {"row": row.n, "message": f"инвентарный номер {row.number} уже занят"}
                )
            if row.number in seen:
                errors.append({"row": row.n, "message": f"номер {row.number} повторяется в файле"})
            seen.add(row.number)
    # ошибка сопоставления называет свою строку таблицы — окно покажет её там (R-047)
    type_of: dict[str, str] = {}
    for item in matched["names"]:
        chosen = types.get(item["name"]) or (str(item["type_id"]) if item["type_id"] else None)
        if not chosen:
            errors.append(
                {
                    "row": item["rows"][0],
                    "message": f"«{item['name']}» не сопоставлено с типом каталога — "
                    "выберите тип или «создать тип»",
                    "name": item["name"],
                }
            )
        else:
            type_of[item["name"]] = chosen
    place_of: dict[str, str] = {}
    for item in matched["rooms"]:
        chosen = rooms.get(item["key"]) or item["place"]
        if not chosen:
            errors.append(
                {
                    "row": item["rows"][0],
                    "message": f"помещение {item['room']} ({item['floor']} этаж) не найдено "
                    "на плане — выберите место",
                    "room": item["key"],
                }
            )
        elif item["confirm"] and not rooms.get(item["key"]):
            # подтверждение — явный выбор места в сопоставлении, хоть того же самого
            plan = item["place_title"].rsplit(" › ", 1)[-1]
            errors.append(
                {
                    "row": item["rows"][0],
                    "message": f"помещение {item['room']} «{item['room_name']}» "
                    f"({item['floor']} этаж) сопоставлено по номеру с «{plan}» — "
                    "названия разные: подтвердите или выберите другое место",
                    "room": item["key"],
                }
            )
        else:
            place_of[item["key"]] = chosen
    units = sum(int(r.qty) if r.accounting == "поштучно" else 0 for r in parsed.rows)
    report: dict[str, Any] = {
        **matched,
        "rows": len(parsed.rows),
        "errors": sorted(errors, key=lambda e: e["row"]),
        "units": units,
        "stock": sum(1 for r in parsed.rows if r.accounting == "количеством"),
        "total": float(sum(r.qty * r.price for r in parsed.rows)),
        "number_template": template,
        "ok": not errors,
        "applied": False,
    }
    if errors or not apply:
        return report
    # тип создаётся по первой строке с этим наименованием
    layers = {name.lower(): lid for lid, name in catalog.layer_names(session).items()}
    created_types: dict[str, uuid.UUID] = {}
    for item in matched["names"]:
        if type_of[item["name"]] == "new":
            layer_id = layers.get(item["layer"].lower()) if item["layer"] else None
            t = catalog.create_type(
                session,
                actor,
                {
                    "name": item["name"],
                    "layer_id": layer_id,
                    "accounting": "quantity" if item["accounting"] == "количеством" else "piece",
                    "unit": item["unit"] or "шт.",
                    **({} if layer_id else {"mount": "none"}),
                },
            )
            created_types[item["name"]] = t.id
    lines = []
    for row in parsed.rows:
        type_id = created_types.get(row.name) or uuid.UUID(type_of[row.name])
        t = catalog.get_type(session, type_id)
        model_id = _model(session, actor, t, row.model)
        qty = row.qty if t.accounting == "quantity" or not row.number else Decimal(1)
        lines.append(
            {
                "type_id": type_id,
                "model_id": model_id,
                "qty": qty,
                "price": row.price,
                "number": row.number if t.accounting == "piece" else "",
                "serial": row.serial,
                "responsible": row.responsible,
                "department": row.department,
                "state": row.state,
                "commissioned_on": row.commissioned,
                "life_months": row.life,
                "note": row.note,
                "to_place": place_of[f"{row.floor}|{row.room}"],
            }
        )
    doc = documents.new_draft(
        session, actor, "opening", {"basis": "Загрузка списка имущества из Excel"}, lines
    )
    documents.post(session, actor, doc.id, doc.version)
    report["applied"] = True
    report["document_id"] = doc.id
    report["created_types"] = list(created_types)
    return report


def _model(session: Session, actor: Actor, t: Any, text: str) -> uuid.UUID | None:
    """Модель из файла: найти у типа по названию (с производителем) или завести."""
    if not text:
        return None
    norm = _norm(text)
    models = t_models(session, t.id)
    for m in models:
        full = _norm(f"{m.manufacturer} {m.name}")
        if norm in (_norm(m.name), full) or (m.article and norm == _norm(m.article)):
            return m.id
    # в файле название короче каталожного («Hikvision DS-2CD2143G2-IS» — «… 2.8 мм»): все
    # слова из файла есть в модели каталога, и среди них — артикульное (с цифрами)
    words = set(norm.split())
    if any(any(ch.isdigit() for ch in w) for w in words):
        fits = [
            (len(set(_norm(f"{m.manufacturer} {m.name}").split()) - words), m)
            for m in models
            if words <= set(_norm(f"{m.manufacturer} {m.name} {m.article or ''}").split())
        ]
        if fits:
            return min(fits, key=lambda f: f[0])[1].id
    m = catalog.create_model(session, actor, t.id, {"name": text[:200]})
    return m.id


def t_models(session: Session, type_id: uuid.UUID) -> list[Any]:
    return catalog.models_of(session, type_id)


# ---------------------------------------------------------------- выгрузки (7.4)


def _book(title: str, head: list[str], rows: list[list[Any]], widths: list[int]) -> bytes:
    # потоком: реестр на 50 000 строк не держится в памяти целиком (8.1)
    wb = Workbook(write_only=True)
    ws = wb.create_sheet(title[:31])
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    cells = []
    for v in head:
        c = WriteOnlyCell(ws, value=v)
        c.font, c.fill = Font(bold=True), LIGHT
        cells.append(c)
    ws.append(cells)
    for r in rows:
        ws.append(text_row(ws, r))
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def registry_export(items: list[dict[str, Any]], actor: Actor) -> bytes:
    head = [
        "Наименование",
        "Модель",
        "Серийный номер",
        "Место",
        "Состояние",
        "Ответственный",
        "Подразделение",
        "Дата ввода",
    ]
    if actor.sees_inventory_numbers:
        head.insert(0, "Инвентарный номер")
    if actor.sees_cost:
        head += ["Цена, ₽", "Остаточная стоимость, ₽", "Срок службы, мес."]
    rows = []
    for u in items:
        r: list[Any] = [
            u["type_name"],
            u["model_name"],
            u["serial"],
            u["place"]["title"] if u["place"] else "",
            u["state_title"],
            u["responsible"],
            u["department"],
            u["commissioned_on"],
        ]
        if actor.sees_inventory_numbers:
            r.insert(0, u["number"])
        if actor.sees_cost:
            r += [u["price"], u["value"], u["life_months"]]
        rows.append(r)
    return _book(
        "Реестр", head, rows, [18, 32, 24, 18, 40, 14, 28, 28, 12, 14, 18, 12][: len(head)]
    )


def statement_export(st: dict[str, Any]) -> bytes:
    head = [*st["group_titles"], "Единиц", "Позиций остатков", "Первоначальная, ₽", "Остаточная, ₽"]
    rows = [
        [*r["group"], r["units"], r["stock_positions"], r["initial"], r["value"]]
        for r in st["rows"]
    ]
    rows.append(
        [
            "Итого",
            *[""] * (len(st["group_titles"]) - 1),
            st["total"]["units"],
            "",
            st["total"]["initial"],
            st["total"]["value"],
        ]
    )
    return _book(
        f"Стоимость на {st['at']:%d.%m.%Y}",
        head,
        rows,
        [30] * len(st["group_titles"]) + [10, 16, 18, 18],
    )


STATE_TITLES = STATES
