"""Каталог в Excel и обратно (5.2.6, 7.3, 7.4): выгрузка загружается назад без правок.

Загрузка: сначала проверка — что будет создано и изменено, ошибки по строкам; потом, после
подтверждения, загрузка целиком или никак. Тип узнаётся по названию, модель — по типу,
производителю и названию; ничего не удаляется."""

import io
import re
from dataclasses import dataclass, field
from typing import Any, BinaryIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.actor import Actor
from app.core.errors import AppError
from app.modules.catalog import api
from app.modules.catalog.models import Characteristic, CharSet, ItemType, Layer, Model, Purpose

SHEETS = {
    "layers": ("Слои", ["Слой", "Цвет", "Порядок", "Виден сразу", "Что в нём"]),
    "sets": (
        "Наборы характеристик",
        ["Набор", "Характеристика", "Вид значения", "Ед.", "Уровень", "Обязательная", "Примечание"],
    ),
    "types": (
        "Типы",
        [
            "Тип",
            "Слой",
            "Наборы",
            "Ширина, мм",
            "Глубина, мм",
            "Высота, мм",
            "Установка",
            "Высота установки, м",
            "Вид учёта",
            "Ед. изм.",
            "Срок службы, мес.",
            "Ориентир. цена, ₽",
            "Может содержать другие",
            "Свои характеристики",
            "Значения характеристик",
        ],
    ),
    "models": (
        "Модели",
        [
            "Тип",
            "Производитель",
            "Модель",
            "Артикул",
            "Поставщик",
            "Цена, ₽",
            "Значения характеристик",
        ],
    ),
    "purposes": (
        "Назначения помещений",
        ["Назначение", "Рабочая поверхность, м", "Норма освещённости, лк", "Примечание"],
    ),
}
HOWTO = [
    "Каталог: слои, наборы характеристик, типы, модели, назначения помещений.",
    "Файл загружается обратно в систему («Каталог › Загрузить из Excel»): тип узнаётся по "
    "названию, модель — по типу, производителю и названию; при загрузке ничего не удаляется.",
    "",
    "«Наборы характеристик»: вид значения — текст, число, дата, да/нет или «выбор: a / b / c»; "
    "уровень — тип, модель или вещь (у каждой инвентарной единицы своё).",
    "«Типы»: габариты в мм; установка — на пол, на стену, на потолок, не ставится; учёт — "
    "поштучно или количеством; пустой слой — расходный материал, на план не ставится. "
    "«Наборы» — через «;». «Свои характеристики» — через «;», каждая как "
    "«Название, ед. (уровень, вид)», например «Допустимая нагрузка, кг (модель, число)».",
    "«Значения характеристик» (у типа и у модели) — через «;», каждое как «Название: значение»; "
    "даты — ДД.ММ.ГГГГ, да/нет — словами.",
    "«Назначения помещений» — высота рабочей поверхности и норма освещённости для расчёта (5.3.5).",
]
YES = {"да", "yes", "true", "1", "+"}
MOUNT_BY_TITLE = {v: k for k, v in api.MOUNTS.items()}
KIND_BY_TITLE = {"текст": "text", "число": "number", "дата": "date", "да/нет": "bool"}
LEVEL_BY_TITLE = {v: k for k, v in api.LEVELS.items()}
ACCOUNTING_BY_TITLE = {v: k for k, v in api.ACCOUNTING.items()}


# ---------------------------------------------------------------- выгрузка


def _kind_title(ch: Characteristic) -> str:
    if ch.kind == "choice":
        return "выбор: " + " / ".join(ch.choices)
    return api.KINDS[ch.kind]


def _own_title(c: Characteristic) -> str:
    """«Название, ед. (уровень[, вид])»: число с единицей и текст без неё вида не пишут."""
    implied = (c.kind == "number" and c.unit) or (c.kind == "text" and not c.unit)
    unit = f", {c.unit}" if c.unit else ""
    kind = "" if implied else f", {_kind_title(c)}"
    return f"{c.name}{unit} ({api.LEVELS[c.level]}{kind})"


def _values_text(
    session: Session, chars: list[Characteristic], values: dict[Any, Any], level: str
) -> str:
    out = []
    for ch in chars:
        if ch.level == level and values.get(ch.id) is not None:
            out.append(f"{ch.name}: {api.format_value(ch, values[ch.id])}")
    return "; ".join(out)


def export(session: Session) -> bytes:
    wb = Workbook()
    howto = wb.active
    howto.title = "Как читать"
    for i, line in enumerate(HOWTO, 1):
        howto.cell(i, 1, line).alignment = Alignment(wrap_text=True, vertical="top")
    howto.column_dimensions["A"].width = 110
    rows: dict[str, list[list[Any]]] = {k: [] for k in SHEETS}
    layers = {x.id: x for x in session.scalars(select(Layer).order_by(Layer.position))}
    for layer in layers.values():
        rows["layers"].append(
            [layer.name, layer.color, layer.position, "да" if layer.visible else "нет", layer.note]
        )
    sets = {s.id: s for s in session.scalars(select(CharSet).order_by(CharSet.position))}
    for s in sets.values():
        for ch in s.characteristics:
            rows["sets"].append(
                [
                    s.name,
                    ch.name,
                    _kind_title(ch),
                    ch.unit,
                    api.LEVELS[ch.level],
                    "да" if ch.required else "нет",
                    ch.note,
                ]
            )
    for t in session.scalars(
        select(ItemType).where(ItemType.archived_at.is_(None)).order_by(ItemType.name)
    ):
        chars = api.characteristics_of(session, t)
        own = [c for c in chars if c.type_id == t.id]
        set_names = [s.name for s in sets.values() if any(c.set_id == s.id for c in chars)]
        own_text = "; ".join(_own_title(c) for c in own)
        rows["types"].append(
            [
                t.name,
                layers[t.layer_id].name if t.layer_id in layers else None,
                "; ".join(set_names) or None,
                t.width,
                t.depth,
                t.height,
                api.MOUNTS[t.mount],
                t.mount_height / 1000 if t.mount_height else None,
                api.ACCOUNTING[t.accounting],
                t.unit,
                t.life_months,
                float(t.price) if t.price is not None else None,
                "да" if t.container else "нет",
                own_text or None,
                _values_text(session, chars, api._values(session, type_id=t.id), "type") or None,
            ]
        )
        for m in session.scalars(
            select(Model)
            .where(Model.type_id == t.id, Model.archived_at.is_(None))
            .order_by(Model.manufacturer, Model.name)
        ):
            rows["models"].append(
                [
                    t.name,
                    m.manufacturer or None,
                    m.name,
                    m.article or None,
                    m.supplier or None,
                    float(m.price) if m.price is not None else None,
                    _values_text(session, chars, api._values(session, model_id=m.id), "model")
                    or None,
                ]
            )
    for p in api.purposes(session):
        rows["purposes"].append([p.name, p.surface / 1000, p.norm, p.note or None])
    head = Font(bold=True)
    fill = PatternFill("solid", fgColor="EEF0F3")
    for key, (title, columns) in SHEETS.items():
        ws = wb.create_sheet(title)
        ws.append(columns)
        for c in range(1, len(columns) + 1):
            ws.cell(1, c).font = head
            ws.cell(1, c).fill = fill
            ws.column_dimensions[get_column_letter(c)].width = max(
                12, min(48, len(columns[c - 1]) + 6)
            )
        for row in rows[key]:
            ws.append(row)
        ws.freeze_panes = "A2"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ---------------------------------------------------------------- загрузка


@dataclass
class Report:
    created: dict[str, list[str]] = field(default_factory=dict)
    updated: dict[str, list[str]] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def add(self, bucket: str, kind: str, name: str) -> None:
        getattr(self, bucket).setdefault(kind, []).append(name)

    def view(self) -> dict[str, Any]:
        return {
            "created": self.created,
            "updated": self.updated,
            "errors": self.errors,
            "ok": not self.errors,
        }


def _cell(v: Any) -> Any:
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def _rows(wb, title: str, columns: list[str], report: Report):  # type: ignore[no-untyped-def]
    if title not in wb.sheetnames:
        return []
    ws = wb[title]
    header = [str(c.value).strip() if c.value else "" for c in ws[1]]
    index = {name: header.index(name) for name in columns if name in header}
    missing = [c for c in columns[:1] if c not in index]
    if missing:
        report.errors.append(
            {"sheet": title, "row": 1, "message": f"Нет столбца «{missing[0]}» — лист пропущен."}
        )
        return []
    out = []
    for n, row in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
        values = {name: _cell(row[i]) if i < len(row) else None for name, i in index.items()}
        if all(v is None for v in values.values()):
            continue
        out.append((n, values))
    return out


def _num(v: Any, what: str) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", ".").replace(" ", "").replace(" ", ""))
    except ValueError:
        raise AppError(f"«{what}» — число, а не «{v}».") from None


def _kind(text: Any) -> tuple[str, list[str]]:
    t = str(text or "текст").strip()
    if t.lower().startswith("выбор"):
        choices = [c.strip() for c in t.split(":", 1)[-1].split("/") if c.strip()]
        return "choice", choices
    kind = KIND_BY_TITLE.get(t.lower())
    if kind is None:
        raise AppError(f"Вид значения «{t}» — нужно: текст, число, дата, да/нет или «выбор: …».")
    return kind, []


def _level(text: Any) -> str:
    level = LEVEL_BY_TITLE.get(str(text or "тип").strip().lower())
    if level is None:
        raise AppError(f"Уровень «{text}» — нужно: тип, модель или вещь.")
    return level


OWN = re.compile(r"^(?P<name>[^(]+?)\s*\((?P<level>[^,)]+)(?:,\s*(?P<kind>[^)]+))?\)$")


def _own_chars(text: str) -> list[dict[str, Any]]:
    out = []
    for part in [p.strip() for p in text.split(";") if p.strip()]:
        m = OWN.match(part)
        if not m:
            raise AppError(f"Своя характеристика «{part}» — нужно «Название, ед. (уровень, вид)».")
        name, unit = m.group("name"), ""
        if "," in name:
            name, unit = (x.strip() for x in name.rsplit(",", 1))
        kind, choices = (
            _kind(m.group("kind"))
            if m.group("kind")
            else (("number", []) if unit else ("text", []))
        )
        out.append(
            {
                "name": name.strip(),
                "unit": unit,
                "level": _level(m.group("level")),
                "kind": kind,
                "choices": choices,
            }
        )
    return out


def _pairs(text: str | None) -> list[tuple[str, str]]:
    out = []
    for part in [p.strip() for p in (text or "").split(";") if p.strip()]:
        if ":" not in part:
            raise AppError(f"Значение «{part}» — нужно «Название: значение».")
        name, value = part.split(":", 1)
        out.append((name.strip(), value.strip()))
    return out


def _by_name(chars: list[Characteristic], name: str) -> Characteristic:
    ch = next((c for c in chars if c.name.lower() == name.lower()), None)
    if ch is None:
        raise AppError(f"У типа нет характеристики «{name}».")
    return ch


def _sync(session: Session, actor: Actor, wb, report: Report) -> None:  # type: ignore[no-untyped-def]
    def run(sheet: str, row: int, fn) -> None:  # type: ignore[no-untyped-def]
        try:
            with session.begin_nested():
                fn()
        except AppError as e:
            report.errors.append({"sheet": sheet, "row": row, "message": e.message})

    # слои
    title, cols = SHEETS["layers"]
    for n, r in _rows(wb, title, cols, report):

        def layer_row(r=r) -> None:  # type: ignore[no-untyped-def]
            name = api._name(r["Слой"], limit=100)
            values = {
                "name": name,
                "color": r.get("Цвет") or "#607D8B",
                "visible": str(r.get("Виден сразу") or "да").lower() in YES,
                "note": r.get("Что в нём") or "",
            }
            if r.get("Порядок") is not None:
                values["position"] = int(_num(r["Порядок"], "Порядок") or 0)
            layer = session.scalars(
                select(Layer).where(func.lower(Layer.name) == name.lower())
            ).first()
            if layer is None:
                api.create_layer(session, actor, values)
                report.add("created", "Слои", name)
            else:
                before = layer.version
                api.update_layer(session, actor, layer.id, dict(values))
                if layer.version != before:
                    report.add("updated", "Слои", name)

        run(title, n, layer_row)
    # наборы и характеристики
    title, cols = SHEETS["sets"]
    for n, r in _rows(wb, title, cols, report):

        def set_row(r=r) -> None:  # type: ignore[no-untyped-def]
            set_name = api._name(r["Набор"], limit=100)
            s = session.scalars(
                select(CharSet).where(func.lower(CharSet.name) == set_name.lower())
            ).first()
            if s is None:
                s = api.create_set(session, actor, set_name)
                report.add("created", "Наборы", set_name)
            ch_name = api._name(r.get("Характеристика"), "характеристику", 150)
            kind, choices = _kind(r.get("Вид значения"))
            values = {
                "name": ch_name,
                "kind": kind,
                "choices": choices,
                "unit": str(r.get("Ед.") or ""),
                "level": _level(r.get("Уровень")),
                "required": str(r.get("Обязательная") or "нет").lower() in YES,
                "note": str(r.get("Примечание") or ""),
            }
            ch = session.scalars(
                select(Characteristic).where(
                    Characteristic.set_id == s.id,
                    func.lower(Characteristic.name) == ch_name.lower(),
                )
            ).first()
            if ch is None:
                api.create_characteristic(session, actor, {**values, "set_id": s.id})
                report.add("created", "Характеристики", f"{set_name}: {ch_name}")
            else:
                before = ch.version
                api.update_characteristic(session, actor, ch.id, values)
                if ch.version != before:
                    report.add("updated", "Характеристики", f"{set_name}: {ch_name}")

        run(title, n, set_row)
    # типы
    title, cols = SHEETS["types"]
    for n, r in _rows(wb, title, cols, report):

        def type_row(r=r) -> None:  # type: ignore[no-untyped-def]
            name = api._name(r["Тип"])
            layer_id = None
            if r.get("Слой"):
                layer = session.scalars(
                    select(Layer).where(func.lower(Layer.name) == str(r["Слой"]).lower())
                ).first()
                if layer is None:
                    raise AppError(f"Слоя «{r['Слой']}» нет — добавьте его на лист «Слои».")
                layer_id = layer.id
            set_ids = []
            for set_name in [x.strip() for x in str(r.get("Наборы") or "").split(";") if x.strip()]:
                s = session.scalars(
                    select(CharSet).where(func.lower(CharSet.name) == set_name.lower())
                ).first()
                if s is None:
                    raise AppError(
                        f"Набора «{set_name}» нет — добавьте его на лист «Наборы характеристик»."
                    )
                set_ids.append(s.id)
            mount_title = str(
                r.get("Установка") or ("на пол" if layer_id else "не ставится")
            ).lower()
            if mount_title not in MOUNT_BY_TITLE:
                raise AppError(
                    f"Установка «{mount_title}» — на пол, на стену, на потолок или не ставится."
                )
            acc_title = str(r.get("Вид учёта") or "поштучно").lower()
            if acc_title not in ACCOUNTING_BY_TITLE:
                raise AppError(f"Вид учёта «{acc_title}» — поштучно или количеством.")
            mh = _num(r.get("Высота установки, м"), "Высота установки")
            life = _num(r.get("Срок службы, мес."), "Срок службы")
            values = {
                "name": name,
                "layer_id": layer_id,
                "set_ids": set_ids,
                "width": _num(r.get("Ширина, мм"), "Ширина"),
                "depth": _num(r.get("Глубина, мм"), "Глубина"),
                "height": _num(r.get("Высота, мм"), "Высота"),
                "mount": MOUNT_BY_TITLE[mount_title],
                "mount_height": mh * 1000 if mh is not None else None,
                "accounting": ACCOUNTING_BY_TITLE[acc_title],
                "unit": str(r.get("Ед. изм.") or "шт."),
                "life_months": int(life) if life is not None else None,
                "price": _num(r.get("Ориентир. цена, ₽"), "Цена"),
                "container": str(r.get("Может содержать другие") or "нет").lower() in YES,
            }
            t = session.scalars(
                select(ItemType)
                .where(func.lower(ItemType.name) == name.lower())
                .order_by(ItemType.archived_at.is_not(None))
            ).first()
            if t is None:
                t = api.create_type(session, actor, values)
                report.add("created", "Типы", name)
                changed = True
            else:
                before = t.version
                api.update_type(session, actor, t.id, values)
                changed = t.version != before
            for spec in _own_chars(str(r.get("Свои характеристики") or "")):
                ch = session.scalars(
                    select(Characteristic).where(
                        Characteristic.type_id == t.id,
                        func.lower(Characteristic.name) == spec["name"].lower(),
                    )
                ).first()
                if ch is None:
                    api.create_characteristic(session, actor, {**spec, "type_id": t.id})
                    changed = True
                else:
                    before = ch.version
                    api.update_characteristic(session, actor, ch.id, spec)
                    changed = changed or ch.version != before
            pairs = _pairs(r.get("Значения характеристик"))
            if pairs:
                chars = api.characteristics_of(session, t)
                values = {str(_by_name(chars, k).id): v for k, v in pairs}
                current = api._values(session, type_id=t.id)
                api.set_values(session, actor, values, item_type=t)
                changed = changed or current != api._values(session, type_id=t.id)
            if changed and name not in report.created.get("Типы", []):
                report.add("updated", "Типы", name)

        run(title, n, type_row)
    # модели
    title, cols = SHEETS["models"]
    for n, r in _rows(wb, title, cols, report):

        def model_row(r=r) -> None:  # type: ignore[no-untyped-def]
            type_name = api._name(r["Тип"], "тип")
            t = session.scalars(
                select(ItemType).where(
                    func.lower(ItemType.name) == type_name.lower(), ItemType.archived_at.is_(None)
                )
            ).first()
            if t is None:
                raise AppError(f"Типа «{type_name}» нет — добавьте его на лист «Типы».")
            name = api._name(r.get("Модель"), "модель")
            manufacturer = str(r.get("Производитель") or "")
            values = {
                "name": name,
                "manufacturer": manufacturer,
                "article": str(r.get("Артикул") or ""),
                "supplier": str(r.get("Поставщик") or ""),
                "price": _num(r.get("Цена, ₽"), "Цена"),
            }
            m = session.scalars(
                select(Model).where(
                    Model.type_id == t.id,
                    Model.archived_at.is_(None),
                    func.lower(Model.name) == name.lower(),
                    func.lower(Model.manufacturer) == manufacturer.lower(),
                )
            ).first()
            title_text = f"{type_name}: {manufacturer} {name}".replace(":  ", ": ")
            if m is None:
                m = api.create_model(session, actor, t.id, values)
                report.add("created", "Модели", title_text)
                changed = False
            else:
                before = m.version
                api.update_model(session, actor, m.id, values)
                changed = m.version != before
            pairs = _pairs(r.get("Значения характеристик"))
            if pairs:
                chars = api.characteristics_of(session, t)
                vals = {str(_by_name(chars, k).id): v for k, v in pairs}
                current = api._values(session, model_id=m.id)
                api.set_values(session, actor, vals, item_type=t, model=m)
                changed = changed or current != api._values(session, model_id=m.id)
            if changed:
                report.add("updated", "Модели", title_text)

        run(title, n, model_row)
    # назначения помещений
    title, cols = SHEETS["purposes"]
    for n, r in _rows(wb, title, cols, report):

        def purpose_row(r=r) -> None:  # type: ignore[no-untyped-def]
            name = api._name(r["Назначение"], limit=150)
            surface = _num(r.get("Рабочая поверхность, м"), "Рабочая поверхность")
            norm = _num(r.get("Норма освещённости, лк"), "Норма освещённости")
            values: dict[str, Any] = {"name": name, "note": str(r.get("Примечание") or "")}
            if surface is not None:
                values["surface"] = surface * 1000
            if norm is not None:
                values["norm"] = int(norm)
            p = session.scalars(
                select(Purpose).where(
                    func.lower(Purpose.name) == name.lower(), Purpose.archived_at.is_(None)
                )
            ).first()
            if p is None:
                api.create_purpose(session, actor, values)
                report.add("created", "Назначения помещений", name)
            else:
                before = p.version
                api.update_purpose(session, actor, p.id, values)
                if p.version != before:
                    report.add("updated", "Назначения помещений", name)

        run(title, n, purpose_row)


def load(session: Session, actor: Actor, stream: BinaryIO, apply: bool) -> dict[str, Any]:
    """Проверка (apply=False) — всё делается и откатывается; загрузка — целиком или никак."""
    api._admin(actor)
    try:
        wb = load_workbook(stream, read_only=True, data_only=True)
    except Exception:
        raise AppError("Файл не читается как Excel (.xlsx).", code="bad_xlsx") from None
    report = Report()
    point = session.begin_nested()
    _sync(session, actor, wb, report)
    if apply and not report.errors:
        point.commit()
    else:
        point.rollback()
    out = report.view()
    out["applied"] = apply and not report.errors
    return out
