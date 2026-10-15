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



# The second portion, added by migration 0003: the furniture and the medical equipment of the old program's catalog
# (legacy/backend/dwg3d/catalog_seed.yaml). Sizes in metres, shapes are the viewer's procedural models; `elev` is
# the mounting height of what hangs on a wall. Flags: c — container, p — portable, w — mounted on a wall,
# t — on the ceiling (migration 0004: it hangs under the ceiling of its floor, `elev` is for a floor of unknown height).
# (number, section, name, (w, d, h), shape, color, elev, flags)
_OLD = [
    (0x306, FURNITURE, "Стойка регистратуры", (2.0, 0.8, 1.1), "reception", "#d2b48c", None, "c"),
    (0x307, FURNITURE, "Секция кресел ожидания, 3 места", (1.7, 0.6, 0.8), "seats", "#20c997", None, ""),
    (0x308, FURNITURE, "Секция кресел ожидания, 4 места", (2.25, 0.6, 0.8), "seats", "#20c997", None, ""),
    (0x309, FURNITURE, "Диван, 2 места", (1.4, 0.75, 0.8), "sofa", "#339af0", None, ""),
    (0x30A, FURNITURE, "Кресло мягкое", (0.75, 0.75, 0.8), "sofa", "#339af0", None, ""),
    (0x30B, FURNITURE, "Журнальный столик", (0.8, 0.5, 0.45), "table", "#d2b48c", None, ""),
    (0x30C, FURNITURE, "Кулер для воды", (0.33, 0.33, 1.1), "cooler", None, None, "p"),
    (0x30D, FURNITURE, "Инфокиоск / терминал очереди", (0.5, 0.45, 1.5), "kiosk", None, None, ""),
    (0x30E, FURNITURE, "Гардеробная стойка", (1.5, 0.6, 1.8), "rack", "#adb5bd", None, ""),
    (0x30F, FURNITURE, "Вешалка напольная", (0.5, 0.5, 1.8), "iv", "#8d6e63", None, "p"),
    (0x310, FURNITURE, "Растение в кашпо", (0.5, 0.5, 1.2), "plant", None, None, "p"),
    (0x311, FURNITURE, "Стол врача с компьютером", (1.4, 0.7, 0.75), "desk_pc", "#d2b48c", None, "c"),
    (0x312, FURNITURE, "Стол письменный", (1.2, 0.6, 0.75), "desk", "#d2b48c", None, "c"),
    (0x313, FURNITURE, "Кресло врача", (0.6, 0.6, 1.05), "chair_office", "#343a40", None, ""),
    (0x314, FURNITURE, "Стул посетителя", (0.5, 0.52, 0.85), "chair", "#20c997", None, ""),
    (0x315, FURNITURE, "Ширма медицинская, 3 секции", (1.6, 0.45, 1.7), "folding", "#e3fafc", None, "p"),
    (0x316, FURNITURE, "Шкаф медицинский, стеклянный", (0.6, 0.4, 1.75), "cabinet_glass", None, None, "c"),
    (0x317, FURNITURE, "Раковина для мытья рук", (0.55, 0.45, 0.85), "sink", None, None, ""),
    (0x318, FURNITURE, "Стул стоматолога", (0.5, 0.5, 0.6), "stool", "#343a40", None, "p"),
    (0x319, FURNITURE, "Тумба с мойкой", (1.2, 0.5, 0.9), "counter_sink", None, None, "c"),
    (0x31A, FURNITURE, "Тумба медицинская", (0.8, 0.5, 0.9), "counter", None, None, "c"),
    (0x31B, FURNITURE, "Пульт оператора КТ / МРТ", (1.6, 0.8, 0.75), "desk_pc", "#dee2e6", None, "c"),
    (0x31C, FURNITURE, "Стол лабораторный", (1.5, 0.75, 0.9), "counter", None, None, "c"),
    (0x31D, FURNITURE, "Кровать функциональная", (1.0, 2.15, 0.9), "bed", None, None, ""),
    (0x31E, FURNITURE, "Тумба прикроватная", (0.45, 0.45, 0.8), "nightstand", None, None, "c"),
    (0x31F, FURNITURE, "Шкаф для документов", (0.8, 0.4, 1.9), "cabinet", "#d2b48c", None, "c"),
    (0x320, FURNITURE, "Шкаф для одежды", (0.8, 0.55, 1.9), "cabinet", "#f1f3f5", None, "c"),
    (0x321, FURNITURE, "Стеллаж открытый", (0.9, 0.35, 1.9), "rack", "#d2b48c", None, "c"),
    (0x322, FURNITURE, "Стеллаж металлический", (1.0, 0.5, 2.0), "rack", "#adb5bd", None, "c"),
    (0x323, FURNITURE, "Шкаф для персонала (4 ячейки)", (0.8, 0.5, 1.8), "lockers", "#a5d8ff", None, "c"),
    (0x324, FURNITURE, "Стол для совещаний", (2.4, 1.0, 0.75), "table", "#d2b48c", None, ""),

    (0x340, MEDICAL, "Рециркулятор бактерицидный (настенный)", (0.3, 0.15, 0.9), "device_wall", None, 1.0, "w"),
    (0x341, MEDICAL, "Ростомер с весами", (0.45, 0.5, 2.05), "stadiometer", None, None, ""),
    (0x342, MEDICAL, "Контейнер для медотходов", (0.35, 0.35, 0.5), "bin", "#fab005", None, "p"),
    (0x343, MEDICAL, "Стол манипуляционный", (0.7, 0.5, 0.85), "cart", None, None, "cp"),
    (0x344, MEDICAL, "Тележка медицинская", (0.6, 0.45, 0.9), "cart", "#a5d8ff", None, "cp"),
    (0x345, MEDICAL, "Штатив для капельниц", (0.5, 0.5, 1.9), "iv", None, None, "p"),
    (0x346, MEDICAL, "Кресло процедурное (забор крови)", (0.7, 0.8, 1.1), "armchair_med", "#20c997", None, ""),
    (0x347, MEDICAL, "Холодильник фармацевтический", (0.6, 0.6, 1.5), "fridge", None, None, "c"),
    (0x348, MEDICAL, "Стерилизатор / автоклав на тумбе", (0.6, 0.55, 0.95), "device", None, None, ""),
    (0x349, MEDICAL, "Кресло гинекологическое", (0.7, 1.4, 1.2), "exam_chair", "#20c997", None, ""),
    (0x34A, MEDICAL, "Стоматологическая установка", (1.6, 2.0, 1.6), "dental", "#63e6be", None, ""),
    (0x34B, MEDICAL, "Рентген дентальный (настенный)", (0.4, 0.5, 0.35), "device_wall", "#e9ecef", 1.4, "w"),
    (0x34C, MEDICAL, "Аппарат УЗИ", (0.6, 0.85, 1.45), "ultrasound", None, None, "p"),
    (0x34D, MEDICAL, "Электрокардиограф на тележке", (0.5, 0.45, 1.0), "cart", "#e9ecef", None, "p"),
    (0x34E, MEDICAL, "Рентгеновский стол со штативом", (2.4, 1.0, 1.9), "xray", None, None, ""),
    (0x34F, MEDICAL, "Магнитно-резонансный томограф (МРТ) 1,5 Тл", (2.3, 4.6, 2.3), "mri", "#7048e8", None, "c"),
    (0x350, MEDICAL, "Шкафы электроники МРТ (техпомещение)", (2.4, 0.8, 2.1), "server", None, None, ""),
    (0x351, MEDICAL, "Инжектор контрастного вещества", (0.6, 0.6, 1.5), "iv", "#e9ecef", None, "p"),
    (0x352, MEDICAL, "Бокс биологической безопасности", (1.3, 0.8, 2.0), "hood", None, None, ""),
    (0x353, MEDICAL, "Центрифуга настольная", (0.4, 0.5, 0.3), "device", None, 0.9, "pw"),
    (0x354, MEDICAL, "Кресло-коляска", (0.65, 1.05, 0.95), "wheelchair", "#343a40", None, "p"),
    (0x355, MEDICAL, "Каталка", (0.7, 2.0, 0.9), "gurney", None, None, "p"),
    (0x356, MEDICAL, "Кислородный концентратор", (0.4, 0.4, 0.7), "device", "#e9ecef", None, "p"),
]


def _old(row) -> dict:
    n, category, name, size, shape, color, elev, flags = row
    sets = [ACCOUNTING, FURNISHING if category == FURNITURE else DEVICE]
    t = _t(n, category, name, size, sets, [], container="c" in flags, portable="p" in flags, color=color)
    return {**t, "shape": shape, "elevation": elev, "wall_mounted": "w" in flags, "ceiling_mounted": "t" in flags}


MORE_TYPES = [_old(row) for row in _OLD]


# The rest of the old catalog's sections: bathrooms, engineering, CCTV, cabling, fire alarm, access control, Wi-Fi, lighting.
# They get their own sections and property sets whose values are the same for every object of a type (stored on the type).
SANITARY, ENGINEERING, SECURITY, NETWORK, FIRE, ACCESS, WIFI, LIGHTING = (_id(n) for n in range(0x103, 0x10B))
EXTRA_CATEGORIES = [
    {"id": SANITARY, "name": "Санузел", "color": "#74b816", "sort": 30},
    {"id": ENGINEERING, "name": "Инженерное оборудование", "color": "#495057", "sort": 40},
    {"id": SECURITY, "name": "Видеонаблюдение", "color": "#7048e8", "sort": 50},
    {"id": NETWORK, "name": "СКС и электрика", "color": "#f59f00", "sort": 60},
    {"id": FIRE, "name": "Пожарная сигнализация", "color": "#e03131", "sort": 70},
    {"id": ACCESS, "name": "СКУД", "color": "#1971c2", "sort": 80},
    {"id": WIFI, "name": "Wi-Fi", "color": "#0ca678", "sort": 90},
    {"id": LIGHTING, "name": "Освещение", "color": "#f59f00", "sort": 100},
]

CAMERA, RADIO, DETECTOR, LIGHT = _id(0x204), _id(0x205), _id(0x206), _id(0x207)
EXTRA_SETS = [
    {"id": CAMERA, "name": "Видеокамера", "description": "Поле зрения камеры", "properties": [
        _p("cam_fov", "Угол обзора", "number", by="system", stored="type", unit="°"),
        _p("cam_range", "Дальность обзора", "number", by="system", stored="type", unit="м"),
        _p("cam_ident", "Дальность опознавания лица", "number", by="system", stored="type", unit="м"),
    ]},
    {"id": RADIO, "name": "Радиосвязь", "description": "Точки доступа Wi-Fi", "properties": [
        _p("radio_tx", "Мощность передатчика", "number", by="system", stored="type", unit="дБм"),
        _p("radio_range", "Радиус покрытия", "number", by="system", stored="type", unit="м"),
    ]},
    {"id": DETECTOR, "name": "Пожарный извещатель", "description": "Защищаемая площадь", "properties": [
        _p("detect_radius", "Радиус контроля", "number", by="system", stored="type", unit="м"),
    ]},
    {"id": LIGHT, "name": "Светильник", "description": "Световые характеристики", "properties": [
        _p("light_flux", "Световой поток", "number", by="system", stored="type", unit="лм"),
        _p("light_power", "Мощность", "number", by="system", stored="type", unit="Вт"),
        _p("light_beam", "Угол светового пучка", "number", by="system", stored="type", unit="°"),
        _p("light_cct", "Цветовая температура", "number", by="system", stored="type", unit="К"),
    ]},
]


def _cam(fov, rng, ident) -> tuple:
    return [CAMERA], {"cam_fov": fov, "cam_range": rng, "cam_ident": ident}


def _light(flux, power, beam, cct) -> tuple:
    return [LIGHT], {"light_flux": flux, "light_power": power, "light_beam": beam, "light_cct": cct}


NONE = ([], {})
# (number, section, name, (w, d, h), shape, color, elev, flags, (extra sets, values of the type))
_REST = [
    (0x360, SANITARY, "Унитаз", (0.4, 0.7, 0.8), "toilet", None, None, "", NONE),
    (0x361, SANITARY, "Раковина", (0.55, 0.45, 0.85), "sink", None, None, "", NONE),
    (0x362, SANITARY, "Кабина для МГН (зона разворота Ø1,5 м)", (1.65, 1.8, 0.05), "zone", "#74c0fc", None, "", NONE),

    (0x370, ENGINEERING, "Электрощит", (0.6, 0.2, 0.9), "panel", None, 1.0, "w", NONE),
    (0x371, ENGINEERING, "Серверный шкаф", (0.6, 1.0, 2.0), "server", None, None, "c", NONE),
    (0x372, ENGINEERING, "Кондиционер (внутренний блок)", (0.9, 0.25, 0.3), "ac", None, 2.3, "w", NONE),
    (0x373, ENGINEERING, "Радиатор отопления", (1.0, 0.1, 0.5), "radiator", None, 0.12, "w", NONE),
    (0x374, ENGINEERING, "Огнетушитель", (0.2, 0.2, 0.6), "extinguisher", None, None, "p", NONE),

    (0x380, SECURITY, "Камера купольная (потолок)", (0.14, 0.14, 0.1), "cam_dome", None, 2.6, "t", _cam(100, 12, 4)),
    (0x381, SECURITY, "Камера цилиндрическая (настенная)", (0.12, 0.3, 0.14), "cam_bullet", None, 2.5, "w", _cam(90, 20, 6)),
    (0x382, SECURITY, "Камера с узким углом (коридор)", (0.12, 0.35, 0.14), "cam_bullet", None, 2.5, "w", _cam(35, 40, 15)),
    (0x383, SECURITY, "Камера панорамная 360°", (0.16, 0.16, 0.06), "cam_fisheye", None, 2.6, "t", _cam(360, 8, 2.5)),
    (0x384, SECURITY, "Камера поворотная (PTZ)", (0.22, 0.22, 0.3), "cam_ptz", None, 2.4, "t", _cam(60, 50, 20)),
    (0x385, SECURITY, "Видеорегистратор в шкафу", (0.6, 0.6, 1.2), "server", None, None, "c", NONE),
    (0x386, SECURITY, "Пост видеонаблюдения (стол с мониторами)", (1.4, 0.7, 0.75), "desk_pc", "#adb5bd", None, "c", NONE),

    (0x390, NETWORK, "Розетка компьютерная RJ-45 (двойная)", (0.08, 0.04, 0.08), "device_wall", "#f8f9fa", 0.3, "w", NONE),
    (0x391, NETWORK, "Розетка 220 В (двойная)", (0.14, 0.04, 0.08), "device_wall", "#f8f9fa", 0.3, "w", NONE),
    (0x392, NETWORK, "Блок розеток медицинской консоли", (0.3, 0.08, 0.12), "device_wall", "#e9ecef", 1.2, "w", NONE),
    (0x393, NETWORK, "Шкаф телекоммуникационный 19″ 42U", (0.6, 0.6, 2.0), "server", None, None, "c", NONE),
    (0x394, NETWORK, "Щит электрический этажный", (0.5, 0.15, 0.7), "panel", None, 1.2, "w", NONE),

    (0x3A0, FIRE, "Извещатель пожарный дымовой", (0.1, 0.1, 0.05), "cam_dome", "#f8f9fa", 2.7, "t",
     ([DETECTOR], {"detect_radius": 5})),
    (0x3A1, FIRE, "Извещатель пожарный тепловой", (0.1, 0.1, 0.05), "cam_dome", "#fff5f5", 2.7, "t",
     ([DETECTOR], {"detect_radius": 3.5})),
    (0x3A2, FIRE, "Извещатель пожарный ручной (ИПР)", (0.1, 0.05, 0.12), "device_wall", "#e03131", 1.5, "w", NONE),
    (0x3A3, FIRE, "Оповещатель звуковой", (0.12, 0.06, 0.1), "device_wall", "#e03131", 2.3, "w", NONE),
    (0x3A4, FIRE, "Табло «Выход»", (0.35, 0.05, 0.15), "device_wall", "#2f9e44", 2.2, "w", NONE),
    (0x3A5, FIRE, "Прибор приёмно-контрольный (ППК)", (0.4, 0.12, 0.5), "panel", None, 1.5, "w", NONE),

    (0x3B0, ACCESS, "Считыватель карт доступа", (0.08, 0.03, 0.12), "device_wall", "#343a40", 1.2, "w", NONE),
    (0x3B1, ACCESS, "Замок электромагнитный", (0.25, 0.05, 0.05), "device_wall", "#868e96", 2.0, "w", NONE),
    (0x3B2, ACCESS, "Кнопка выхода", (0.08, 0.04, 0.08), "device_wall", "#2f9e44", 1.2, "w", NONE),
    (0x3B3, ACCESS, "Турникет-трипод", (0.9, 0.3, 1.0), "kiosk", None, None, "", NONE),
    (0x3B4, ACCESS, "Контроллер СКУД", (0.3, 0.1, 0.3), "device_wall", None, 1.8, "w", NONE),

    (0x3C0, WIFI, "Точка доступа Wi-Fi потолочная", (0.2, 0.2, 0.04), "cam_dome", "#f8f9fa", 2.8, "t",
     ([RADIO], {"radio_tx": 20, "radio_range": 40})),
    (0x3C1, WIFI, "Точка доступа Wi-Fi настенная", (0.15, 0.04, 0.1), "device_wall", "#f8f9fa", 2.2, "w",
     ([RADIO], {"radio_tx": 17, "radio_range": 30})),

    (0x3D0, LIGHTING, "Светильник светодиодный, панель 600×600", (0.6, 0.6, 0.04), "lamp_panel", None, 2.7, "t", _light(3600, 36, 120, 4000)),
    (0x3D1, LIGHTING, "Светильник медицинский, панель 600×600 (IP54, CRI 90)", (0.6, 0.6, 0.05), "lamp_panel", None, 2.7, "t", _light(4400, 40, 110, 4000)),
    (0x3D2, LIGHTING, "Светильник линейный 1200 мм", (1.2, 0.1, 0.06), "lamp_panel", None, 2.7, "t", _light(4000, 36, 120, 4000)),
    (0x3D3, LIGHTING, "Светильник линейный пылевлагозащищённый (IP65)", (1.27, 0.14, 0.1), "lamp_panel", None, 2.7, "t", _light(3800, 38, 120, 5000)),
    (0x3D4, LIGHTING, "Светильник встраиваемый точечный (даунлайт)", (0.17, 0.17, 0.06), "lamp_round", None, 2.7, "t", _light(1500, 15, 90, 4000)),
    (0x3D5, LIGHTING, "Светильник акцентный, узкий луч", (0.1, 0.1, 0.12), "lamp_round", None, 2.6, "t", _light(900, 10, 36, 3000)),
    (0x3D6, LIGHTING, "Светильник накладной круглый", (0.3, 0.3, 0.08), "lamp_round", None, 2.65, "t", _light(1800, 18, 120, 4000)),
    (0x3D7, LIGHTING, "Светильник настенный (бра)", (0.2, 0.1, 0.25), "device_wall", "#fff3bf", 1.9, "w", _light(800, 9, 180, 3000)),
    (0x3D8, LIGHTING, "Светильник прикроватный настенный (палатный)", (0.9, 0.1, 0.12), "device_wall", "#f8f9fa", 1.7, "w", _light(2000, 24, 150, 4000)),
    (0x3D9, LIGHTING, "Светильник аварийного освещения", (0.35, 0.08, 0.14), "device_wall", "#f8f9fa", 2.3, "w", _light(300, 4, 120, 6000)),
    (0x3DA, LIGHTING, "Светильник смотровой передвижной", (0.5, 0.5, 1.8), "lamp_floor", None, None, "p", _light(1600, 20, 30, 4500)),
    (0x3DB, LIGHTING, "Торшер", (0.35, 0.35, 1.6), "lamp_floor", None, None, "p", _light(1000, 11, 200, 2700)),
]


def _rest(row) -> dict:
    n, category, name, size, shape, color, elev, flags, (sets, values) = row
    t = _t(n, category, name, size, [ACCOUNTING, *sets], [], values=values, container="c" in flags,
           portable="p" in flags, color=color)
    return {**t, "shape": shape, "elevation": elev, "wall_mounted": "w" in flags, "ceiling_mounted": "t" in flags}


MORE_TYPES += [_rest(row) for row in _REST]


# The office: furniture of workplaces and meeting rooms into «Мебель», and the office equipment — printers,
# computers, screens, the kitchen's appliances — in a section of its own with a property set of its own
# (migration 0005). Same columns as the rows above; `elev` of what stands on a desk or a counter is the
# desk's or the counter's height.
OFFICE = _id(0x10B)
OFFICE_CATEGORIES = [
    {"id": OFFICE, "name": "Оргтехника и офисное оборудование", "color": "#be4bdb", "sort": 25},
]
EQUIPMENT = _id(0x208)
OFFICE_SETS = [
    # the make and model are the object's product (migration 0006), not properties of the type
    {"id": EQUIPMENT, "name": "Оргтехника", "description": "Техника офиса: расходные материалы, сетевое имя, сервис",
     "properties": [
        _p("consumables", "Расходные материалы", "text", by="system", stored="type"),
        _p("network_name", "Сетевое имя", "text", by="responsible"),
        _p("service_until", "Сервисный контракт до", "date"),
     ]},
]
# (number, section, name, (w, d, h), shape, color, elev, flags)
_OFFICE = [
    (0x3E0, FURNITURE, "Стол офисный 1600×800", (1.6, 0.8, 0.75), "desk", "#d2b48c", None, "c"),
    (0x3E1, FURNITURE, "Стол офисный угловой", (1.6, 1.6, 0.75), "desk", "#d2b48c", None, "c"),
    (0x3E2, FURNITURE, "Стол переговорный круглый", (1.2, 1.2, 0.75), "table", "#d2b48c", None, ""),
    (0x3E3, FURNITURE, "Стол переговорный, 8 мест", (3.2, 1.2, 0.75), "table", "#d2b48c", None, "c"),
    (0x3E4, FURNITURE, "Кресло руководителя", (0.7, 0.7, 1.2), "chair_office", "#343a40", None, ""),
    (0x3E5, FURNITURE, "Кресло офисное", (0.6, 0.6, 1.0), "chair_office", "#495057", None, ""),
    (0x3E6, FURNITURE, "Стул офисный", (0.5, 0.55, 0.85), "chair", "#868e96", None, "p"),
    (0x3E7, FURNITURE, "Тумба подкатная", (0.4, 0.5, 0.6), "nightstand", "#d2b48c", None, "cp"),
    (0x3E8, FURNITURE, "Шкаф картотечный", (0.5, 0.6, 1.3), "cabinet", "#adb5bd", None, "c"),
    (0x3E9, FURNITURE, "Стеллаж архивный", (1.0, 0.4, 2.2), "rack", "#adb5bd", None, "c"),
    (0x3EA, FURNITURE, "Диван офисный, 3 места", (2.0, 0.85, 0.8), "sofa", "#495057", None, ""),
    (0x3EB, FURNITURE, "Перегородка офисная мобильная", (1.2, 0.05, 1.6), "folding", "#dee2e6", None, "p"),
    (0x3EC, FURNITURE, "Корзина для бумаг", (0.3, 0.3, 0.35), "bin", "#868e96", None, "p"),
    (0x3ED, FURNITURE, "Доска маркерная настенная", (1.2, 0.05, 0.9), "device_wall", "#f8f9fa", 0.9, "w"),
    (0x3EE, FURNITURE, "Флипчарт", (0.7, 0.6, 1.9), "kiosk", "#f8f9fa", None, "p"),
    (0x3EF, FURNITURE, "Вешалка настенная", (0.6, 0.1, 0.2), "device_wall", "#8d6e63", 1.6, "w"),

    (0x3F0, OFFICE, "МФУ лазерное (принтер, сканер, копир)", (0.5, 0.45, 0.45), "device", "#e9ecef", 0.75, ""),
    (0x3F1, OFFICE, "Принтер лазерный", (0.4, 0.4, 0.25), "device", "#e9ecef", 0.75, "p"),
    (0x3F2, OFFICE, "МФУ напольное, формат A3", (0.6, 0.7, 1.1), "device", "#e9ecef", None, ""),
    (0x3F3, OFFICE, "Системный блок", (0.2, 0.45, 0.45), "device", "#343a40", None, ""),
    (0x3F4, OFFICE, "Монитор 27″", (0.62, 0.2, 0.45), "screen_tv", "#212529", 0.75, ""),
    (0x3F5, OFFICE, "Моноблок", (0.55, 0.2, 0.45), "screen_tv", "#212529", 0.75, ""),
    (0x3F6, OFFICE, "Ноутбук", (0.35, 0.25, 0.03), "device", "#495057", 0.75, "p"),
    (0x3F7, OFFICE, "Телефон IP настольный", (0.22, 0.2, 0.18), "device", "#343a40", 0.75, "p"),
    (0x3F8, OFFICE, "Телевизор настенный 55″", (1.25, 0.08, 0.72), "screen_tv", "#212529", 1.4, "w"),
    (0x3F9, OFFICE, "Проектор потолочный", (0.35, 0.3, 0.12), "device", "#e9ecef", 2.5, "t"),
    (0x3FA, OFFICE, "Экран проекционный настенный", (2.0, 0.1, 1.5), "device_wall", "#f8f9fa", 1.0, "w"),
    (0x3FB, OFFICE, "Шредер", (0.4, 0.3, 0.6), "bin", "#495057", None, "p"),
    (0x3FC, OFFICE, "ИБП", (0.2, 0.4, 0.35), "device", "#343a40", None, ""),
    (0x3FD, OFFICE, "Сейф", (0.45, 0.45, 0.7), "cabinet", "#495057", None, "c"),
    (0x3FE, OFFICE, "Кофемашина", (0.3, 0.45, 0.4), "device", "#343a40", 0.9, "p"),
    (0x3FF, OFFICE, "Холодильник офисный", (0.55, 0.6, 0.85), "fridge", "#f8f9fa", None, ""),
    (0x400, OFFICE, "Микроволновая печь", (0.5, 0.4, 0.3), "device", "#e9ecef", 0.9, "p"),
]


def _office(row) -> dict:
    n, category, name, size, shape, color, elev, flags = row
    sets = [ACCOUNTING, FURNISHING if category == FURNITURE else EQUIPMENT]
    t = _t(n, category, name, size, sets, [], container="c" in flags, portable="p" in flags, color=color)
    return {**t, "shape": shape, "elevation": elev, "wall_mounted": "w" in flags, "ceiling_mounted": "t" in flags}


OFFICE_TYPES = [_office(row) for row in _OFFICE]
