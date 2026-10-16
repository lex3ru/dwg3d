"""Что значит слой чертежа — по его названию. Названия слоёв у проектировщиков разные,
поэтому роли угадываются по частям слов; неизвестный слой в стены не идёт."""

import re

ROLES: list[tuple[str, tuple[str, ...]]] = [
    # порядок важен: первое совпадение решает
    (
        "ignore",
        (
            "размер",
            "dim",
            "ось",
            "оси",
            "axis",
            "grid",
            "текст",
            "text",
            "надпис",
            "формат",
            "лист",
            "рамк",
            "frame",
            "title",
            "штамп",
            "мебел",
            "furn",
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
    ("window", ("окн", "окон", "window", "витраж", "glaz")),
    ("door", ("двер", "door", "ворот")),
    ("column", ("колон", "column", "пилон", "двутавр", "стойк")),
    ("stair", ("лестн", "stair", "марш", "ступен")),
    ("lift", ("лифт", "lift", "elev")),
    ("partition", ("перегор", "partition", "гипсок", "гкл")),
    (
        "wall",
        (
            "стен",
            "wall",
            "кирпич",
            "блок",
            "бетон",
            "жб",
            "монолит",
            "несущ",
            "конструкц",
            "кладк",
            "утепл",
            "insul",
        ),
    ),
    ("fill", ("штрих", "hatch")),
]


def role(layer: str) -> str:
    name = layer.lower()
    for role_name, words in ROLES:
        if any(w in name for w in words):
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
