"""What the catalog starts with: the sections, the property sets and the five types the
spec was agreed on (docs/TZ.md, appendix А). Written once by the first migration; what
administrators change afterwards is theirs.

Inventory and serial numbers, the state, who answers and the note are fields of every
object (the assets service), not properties of a schema.
"""
from __future__ import annotations

from uuid import UUID


def _id(n: int) -> UUID:
    return UUID(f"0192f000-0000-7000-8000-{n:012x}")


def _p(key, title, kind, *, by="admin", stored="asset", unit=None, required=False, options=None) -> dict:
    return {"key": key, "title": title, "kind": kind, "unit": unit, "required": required, "stored": stored,
            "editable_by": by, "options": [{"value": v, "title": t} for v, t in options] if options else None}


MEDICAL, FURNITURE = _id(0x101), _id(0x102)
CATEGORIES = [
    {"id": MEDICAL, "name": "Медицинская техника", "color": "#1c7ed6", "sort": 10},
    {"id": FURNITURE, "name": "Мебель", "color": "#868e96", "sort": 20},
]

ACCOUNTING, DEVICE, FURNISHING = _id(0x201), _id(0x202), _id(0x203)
SETS = [
    {"id": ACCOUNTING, "name": "Учёт", "description": "Общее для всего, что стоит на учёте", "properties": [
        _p("commissioned", "Дата ввода в эксплуатацию", "date"),
        _p("warranty_until", "Гарантия до", "date"),
    ]},
    {"id": DEVICE, "name": "Медицинское изделие", "description": "Техника с регистрационным удостоверением и ТО",
     "properties": [
        _p("manufacturer", "Производитель", "text", by="system", stored="type"),
        _p("model", "Модель", "text", by="system", stored="type"),
        _p("registration", "Регистрационное удостоверение", "text", by="system", stored="type"),
        _p("made", "Год выпуска", "number"),
        _p("service_last", "Дата последнего ТО", "date", by="responsible"),
        _p("service_next", "Дата следующего ТО", "date", by="responsible"),
        _p("service_by", "Организация, проводящая ТО", "text"),
        _p("service_contract", "Договор на ТО", "text"),
     ]},
    {"id": FURNISHING, "name": "Мебель", "description": "", "properties": [
        _p("material", "Материал, цвет", "text"),
        _p("wear", "Износ", "choice", by="responsible",
           options=[("new", "новый"), ("good", "хороший"), ("worn", "изношен"), ("replace", "под замену")]),
    ]},
]


def _t(n, category, name, size, sets, properties, *, values=None, container=False, portable=False, color=None) -> dict:
    return {"id": _id(n), "category_id": category, "name": name, "w": size[0], "d": size[1], "h": size[2],
            "sets": sets, "properties": properties, "values": values or {}, "container": container,
            "portable": portable, "color": color, "sort": n, "shape": SHAPES.get(n, "box")}


# how a type is drawn in 3D until a model is loaded for it: one of the viewer's procedural models
SHAPES = {0x301: "ct", 0x302: "device", 0x303: "desk", 0x304: "couch", 0x305: "chair"}


TYPES = [
    _t(0x301, MEDICAL, "Аппарат КТ", (2.3, 2.0, 1.9), [ACCOUNTING, DEVICE], [
        _p("slices", "Число срезов", "number", by="system", stored="type"),
        _p("power", "Потребляемая мощность", "number", by="system", stored="type", unit="кВт"),
        _p("tube_load", "Наработка трубки", "number", by="responsible", unit="сканов"),
        _p("tube_replaced", "Дата замены трубки", "date", by="responsible"),
        _p("params_checked", "Дата контроля эксплуатационных параметров", "date", by="responsible"),
        _p("params_next", "Следующий контроль параметров", "date", by="responsible"),
        _p("sanitary_permit", "Санитарно-эпидемиологическое заключение на кабинет", "text"),
    ], container=True),
    _t(0x302, MEDICAL, "Гастроскоп", (0.6, 0.4, 0.2), [ACCOUNTING, DEVICE], [
        _p("scope_kind", "Вид", "choice", by="system", stored="type", options=[("video", "видео"), ("fibre", "фибро")]),
        _p("insertion_diameter", "Диаметр вводимой части", "number", by="system", stored="type", unit="мм"),
        _p("working_length", "Рабочая длина", "number", by="system", stored="type", unit="мм"),
        _p("channel_diameter", "Диаметр инструментального канала", "number", by="system", stored="type", unit="мм"),
        _p("examinations", "Число проведённых исследований", "number", by="responsible"),
        _p("leak_tested", "Дата последней проверки на герметичность", "date", by="responsible"),
        _p("repairs", "Число ремонтов", "number"),
    ], values={"scope_kind": "video"}, portable=True),
    _t(0x303, FURNITURE, "Рабочий стол", (1.4, 0.7, 0.75), [ACCOUNTING, FURNISHING], [
        _p("assigned_to", "За кем закреплён", "person"),
        _p("height_adjustable", "Регулировка высоты", "bool", by="system", stored="type"),
    ], values={"height_adjustable": False}, container=True),
    _t(0x304, FURNITURE, "Кушетка", (1.9, 0.65, 0.55), [ACCOUNTING, FURNISHING], [
        _p("couch_kind", "Вид", "choice", by="system", stored="type",
           options=[("exam", "смотровая"), ("massage", "массажная"), ("procedure", "процедурная")]),
        _p("max_load", "Допустимая нагрузка", "number", by="system", stored="type", unit="кг"),
        _p("disinfectable", "Обивка допускает дезинфекцию", "bool", by="system", stored="type"),
    ], values={"couch_kind": "exam", "disinfectable": True}),
    _t(0x305, FURNITURE, "Кресло посетителя", (0.6, 0.6, 0.85), [ACCOUNTING, FURNISHING], []),
]
