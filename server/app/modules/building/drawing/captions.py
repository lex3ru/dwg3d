"""Подписи на листе (5.1.3 п. 1–2): строки текста, подписи в несколько строк и что за
чертёж называет подпись — план этажа, фасад, разрез, таблица (R-061…R-063)."""

import bisect
import re
from dataclasses import dataclass

from app.modules.building.drawing.read import Text

MAX_LINE = 60  # знаков: строка длиннее — примечание, а не подпись
MAX_ROWS = 4  # строк в одной подписи
STEP = (0.8, 2.2)  # шаг строк одной подписи — в высотах текста

# что за чертёж называет подпись; порядок важен — первое совпадение решает
KINDS: list[tuple[str, re.Pattern[str]]] = [
    (kind, re.compile(pattern, re.IGNORECASE))
    for kind, pattern in (
        ("table", r"^(экспликац|спецификац|ведомост|таблиц|перечень|общие\s+данные|"
                  r"условн\w*\s+обозначени|график|диаграмм|эпюр)"),
        ("site", r"генплан|генеральн\w*\s+план|ситуационн\w*\s+план|план\s+благоустройств|"
                 r"план\s+организации\s+рельеф"),
        # «Фасад 1-12», «Главный фасад»; «Фасадные панели», «см. разрез 1-1» — не подписи
        ("facade", r"^(\w+\s+)?(фасад|фасады|развертк|развёртк)(?!\w)"),
        ("section", r"^(\w+\s+)?(разрез|сечени)"),
        # «Тепловой узел» — название помещения, а не узел чертежа
        ("detail", r"^(узел|узлы|деталь|детали|фрагмент)(?!\w)"),
        ("scheme", r"^схем"),
        ("roof", r"^план\s+(кровл|крыш)|^кровля$"),
        ("plan", r"^(\w+\s+)?план(?!\w)|(?<!\w)(этаж\w{0,2}|подвал\w{0,2}|цокол\w*|мансард\w*|"
                 r"чердак\w{0,2}|техподполь\w*)(?!\w)"),
    )
]
NOTE = re.compile(r"^\d+\s*[.)]\s")  # «4. Выполнить уклон…» — пункт примечаний
SCALE = re.compile(r"\s*\(?\s*м\s*1\s*:\s*\d+\s*\)?\s*$", re.IGNORECASE)  # «… М 1:100»
LEVEL = re.compile(r"(-?\d+)\s*-?\s*(го|й|ой|ий)?\s*этаж", re.IGNORECASE)


@dataclass
class Line:
    """Строка текста; MTEXT в несколько строк — по строкам."""

    layer: str
    x: float
    y: float
    height: float
    text: str


@dataclass
class Caption:
    """Подпись чертежа: одна или несколько строк одной колонки."""

    x: float
    y: float
    height: float
    text: str
    kind: str


def lines(texts: list[Text]) -> list[Line]:
    out = []
    for t in texts:
        h = max(t.height, 1.0)
        for i, row in enumerate(t.text.split("\n")):
            row = " ".join(row.split())
            if row:
                out.append(Line(t.layer, t.x, t.y - i * 1.5 * h, h, row))
    return out


def _width(line: Line) -> float:
    return 0.6 * line.height * len(line.text)


def follows(upper: Line, lower: Line) -> bool:
    """lower — следующая строка той же подписи: та же высота, шаг в строку, та же колонка
    (выровнены по левому краю или по середине)."""
    h = max(upper.height, lower.height)
    if abs(upper.height - lower.height) > 0.3 * h:
        return False
    if not STEP[0] * h <= upper.y - lower.y <= STEP[1] * h:
        return False
    if abs(upper.x - lower.x) <= 1.5 * h:
        return True
    wu, wl = _width(upper), _width(lower)
    return abs(upper.x + wu / 2 - lower.x - wl / 2) <= max(1.5 * h, 0.2 * max(wu, wl))


def blocks(found: list[Line]) -> list[list[Line]]:
    """Строки одной колонки с шагом в строку — один текст: «Комната» / «персонала» (R-063).
    Для немногих строк (одно помещение): каждая с каждой."""
    out: list[list[Line]] = []
    for line in sorted(found, key=lambda t: (-t.y, t.x)):
        block = next((b for b in out if len(b) < MAX_ROWS and follows(b[-1], line)), None)
        if block is None:
            out.append([line])
        else:
            block.append(line)
    return out


def kind_of(text: str) -> str:
    """Вид чертежа, который называет строка; "" — не подпись."""
    t = text.strip().replace("ё", "е").replace("Ё", "Е")
    if not t or len(t) > MAX_LINE or NOTE.match(t):
        return ""
    return next((kind for kind, pattern in KINDS if pattern.search(t)), "")


def level(text: str) -> int | None:
    """Номер этажа из названия: «План 3-го этажа» — 3, подвал и цоколь — −1."""
    m = LEVEL.search(text)
    if m:
        return int(m.group(1))
    if re.search(r"подвал|цокол", text, re.IGNORECASE):
        return -1
    return None


def _same_kind(a: str, b: str) -> bool:
    """Строки одной подписи: «Обмерный план» и «1 этажа» — да, «План подвала» и
    «Спецификация» — две подписи в одной графе штампа."""
    return not a or not b or a == b


def find(texts: list[Text]) -> list[Caption]:
    """Подписи чертежей на листе. Строка с видом чертежа вместе со строкой над ней и
    строками под ней в той же колонке, и с продолжением в той же строке, — одна подпись:
    «Обмерный план» / «1 этажа», «Расстановка мебели» / «2 этажа» (R-062)."""
    found = lines(texts)
    order = sorted(found, key=lambda t: t.y)
    ys = [t.y for t in order]
    used: set[int] = set()

    def near(y0: float, y1: float) -> list[Line]:
        return [t for t in order[bisect.bisect_left(ys, y0):bisect.bisect_right(ys, y1)]
                if id(t) not in used and len(t.text) <= MAX_LINE and not NOTE.match(t.text)]

    out = []
    for line in sorted(found, key=lambda t: (-t.y, t.x)):
        kind = kind_of(line.text)
        if id(line) in used or not kind:
            continue
        used.add(id(line))
        h = line.height
        # продолжение в той же строке: подпись, набранная двумя текстами
        row = [line]
        while True:
            last = row[-1]
            nxt = next((t for t in sorted(near(last.y - 0.2 * h, last.y + 0.2 * h),
                                          key=lambda t: t.x)
                        if last.x < t.x <= last.x + _width(last) + 8 * h
                        and abs(t.height - h) <= 0.3 * h and kind_of(t.text)
                        and _same_kind(kind, kind_of(t.text))), None)
            if nxt is None:
                break
            used.add(id(nxt))
            row.append(nxt)
        rows = [" ".join(t.text for t in row)]
        # строка над подписью, которая начинается не с начала: «Расстановка мебели» /
        # «1 этажа»; над «Узлы» в штампе — название объекта, оно не нужно
        above = None if not re.match(r"[\d\-a-zа-яё]", line.text) else next(
            (t for t in near(line.y + STEP[0] * h * 0.7, line.y + STEP[1] * h * 1.3)
             if follows(t, line) and not kind_of(t.text)), None)
        if above is not None:
            used.add(id(above))
            rows.insert(0, above.text)
        # строки под ней в той же колонке, пока не начнётся подпись другого чертежа
        last = line
        while len(rows) < MAX_ROWS:
            nxt = next((t for t in near(last.y - STEP[1] * last.height * 1.3,
                                        last.y - STEP[0] * last.height * 0.7)
                        if follows(last, t)), None)
            if nxt is None or not _same_kind(kind, kind_of(nxt.text)):
                break
            used.add(id(nxt))
            rows.append(nxt.text)
            last = nxt
        text = SCALE.sub("", " ".join(rows)).strip(" :;,.")
        out.append(Caption(line.x, line.y, h, text, kind_of(text[:MAX_LINE]) or kind))
    return out
