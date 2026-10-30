"""Что значит слой чертежа — по его названию. Названия слоёв у проектировщиков разные,
поэтому роль угадывается по началу слов названия; неизвестный слой в стены не идёт."""

import re
from functools import cache

ROLES: list[tuple[str, tuple[str, ...]]] = [
    # порядок важен: первое совпадение решает; слово названия должно начинаться с корня
    (
        "ignore",
        (
            "размер",
            "dim",
            "bemaß",
            "bemass",
            "maß",
            "ось",
            "оси",
            "осей",
            "осев",
            "axis",
            "axes",
            "achs",
            "grid",
            "raster",
            "текст",
            "text",
            "schrift",
            "beschrift",
            "надпис",
            "формат",
            "лист",
            "рамк",
            "frame",
            "rahmen",
            "title",
            "plankopf",
            "штамп",
            "мебел",
            "furn",
            "möbel",
            "сантех",
            "оборуд",
            "equip",
            "defpoints",
            "зон",
            "zone",
            "связи",
            "тонкая",
            "thin",
            "отметк",
            "выносн",
            "leader",
            "сеч",
            "разрез",
            "пера",
            "anno",
            "площад",
            "задание",
            "канал",
            "отв",
            "мусор",
        ),
    ),
    ("window", ("окн", "окон", "window", "fenster", "витраж", "glaz")),
    ("door", ("двер", "door", "tür", "ворот")),
    ("column", ("колон", "column", "stütz", "пилон", "двутавр", "стойк")),
    ("stair", ("лестн", "stair", "trepp", "марш", "ступен")),
    ("lift", ("лифт", "lift", "elev", "aufzug")),
    ("partition", ("перегор", "partition", "trennw", "гипсок", "гкл")),
    (
        "wall",
        (
            # «блок» — не стены: так называют и функциональные блоки, зоны (R-058)
            "стен",
            "wall",
            "wand",
            "wände",
            "mauer",
            "кирпич",
            "газоблок",
            "пеноблок",
            "бетон",
            "газобетон",
            "пенобетон",
            "железобетон",
            "жб",
            "монолит",
            "несущ",
            "конструкц",
            "кладк",
            "утепл",
            "insul",
        ),
    ),
    ("fill", ("штрих", "hatch", "schraff")),
]

# латинские буквы, неотличимые от кириллицы: «Cтены» с латинской C — это «Стены»
LOOKALIKE = str.maketrans("aceopxykmthb", "асеорхукмтнв")
CYRILLIC = re.compile(r"[а-яё]")


def words(layer: str) -> list[str]:
    """Слова названия слоя: «A-WALL_ext» → a, wall, ext; «НесущиеСтены» → несущие, стены."""
    split = re.sub(r"(?<=[a-zа-яёß])(?=[A-ZА-ЯЁ])", " ", layer).lower().replace("ё", "е")
    out = []
    for word in re.findall(r"[a-zа-яäöüß]+", split):
        if CYRILLIC.search(word):
            word = word.translate(LOOKALIKE)
        out.append(word)
    return out


@cache  # слоёв на листе десятки, а отрезков — сотни тысяч
def role(layer: str) -> str:
    found = words(layer)
    for role_name, roots in ROLES:
        if any(w.startswith(roots) for w in found):
            return role_name
    return "other"


AREA = re.compile(r"^\d{1,4}([.,]\d{1,2})?\s*(м2|м²|кв\.?\s*м)?$")
DIMENSION = re.compile(r"^[\d\s ]{4,}$|^[+−-]\d+[.,]\d{3}$")
NUMBER = re.compile(r"^(№\s*)?[А-ЯA-Z]?\d{1,4}([./-]\d{1,4}){0,3}[а-яa-z]?$", re.IGNORECASE)
MARK = re.compile(r"^[А-ЯЁA-Z]{1,5}[-\s]?\d[\d.,\-/хx]*[А-ЯЁA-Zа-я]?$")
FLOOR = re.compile(
    r"(план\s+)?(-?\d+)\s*-?\s*(го|й|ой|ий)?\s*этаж|подвал|цокол|техн[^\s]*\s+этаж|"
    r"мансард|кровл|чердак",
    re.IGNORECASE,
)


def text_kind(text: str) -> str:
    """Что за текст стоит в помещении: номер, площадь, название или ничего полезного."""
    t = text.strip().replace(" ", " ")
    if not t:
        return "none"
    if DIMENSION.match(t):
        return "none"
    if AREA.match(t) and ("," in t or "." in t or "м" in t):
        return "area"
    if NUMBER.match(t):
        return "number"
    if MARK.match(t):
        return "none"  # марка двери, окна, перемычки: ДГ21-8, ОК-3
    if re.search(r"[а-яА-ЯёЁa-zA-Z]{3,}", t):
        return "name"
    return "none"
