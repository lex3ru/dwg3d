"""Properties, and the schema of a type: its sets in order, then its own properties."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator
from twin_chassis import Problem

KEY = r"^[a-z][a-z0-9_]{0,39}$"


class Option(BaseModel):
    value: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=100)


class Property(BaseModel):
    key: str = Field(pattern=KEY, description="Латиницей; не меняется после создания")
    title: str = Field(min_length=1, max_length=100)
    kind: Literal["text", "number", "date", "bool", "choice", "person"]
    unit: str | None = Field(default=None, max_length=20)
    options: list[Option] | None = Field(default=None, max_length=50, description="Варианты для kind = choice")
    required: bool = False
    stored: Literal["type", "asset"] = Field(default="asset", description="Значение одно на тип или у каждого объекта")
    editable_by: Literal["system", "admin", "responsible"] = Field(
        default="admin", description="Кто правит: система, администратор здания, ответственный")

    @model_validator(mode="after")
    def _choice_has_options(self):
        if self.kind == "choice" and not self.options:
            raise ValueError("для выбора из списка нужны варианты (options)")
        if self.kind != "choice":
            self.options = None
        return self


def unique_keys(properties: list[Property] | list[dict], where: str) -> None:
    seen: set[str] = set()
    for p in properties:
        key = p.key if isinstance(p, Property) else p["key"]
        if key in seen:
            raise Problem(422, "invalid", f"Ключ свойства «{key}» повторяется {where}",
                          errors=[{"field": "properties", "message": f"ключ {key} повторяется"}])
        seen.add(key)


def resolve(type_row, sets_by_id: dict) -> list[dict]:
    """The schema of a type: the properties of its sets in their order, then its own; each says where it is from."""
    out: list[dict] = []
    for set_id in type_row.sets:
        s = sets_by_id.get(set_id)
        if s is not None:
            out += [{**p, "set_id": str(s.id), "set": s.name} for p in s.properties]
    out += [{**p, "set_id": None, "set": None} for p in type_row.properties]
    return out


def check_resolved(name: str, schema: list[dict]) -> None:
    """A key may occur once in a type's schema, whichever set it comes from."""
    seen: dict[str, str] = {}
    for p in schema:
        source = p["set"] or "собственные свойства"
        if p["key"] in seen:
            raise Problem(409, "key_conflict",
                          f"В схеме типа «{name}» ключ «{p['key']}» встречается дважды: {seen[p['key']]} и {source}")
        seen[p["key"]] = source


def check_values(schema: list[dict], values: dict) -> None:
    """Values kept with the type are for properties stored with the type, and fit their kind."""
    by_key = {p["key"]: p for p in schema if p["stored"] == "type"}
    for key, value in values.items():
        p = by_key.get(key)
        if p is None:
            raise Problem(422, "invalid", f"«{key}» — не свойство типа",
                          errors=[{"field": f"values.{key}", "message": "нет такого свойства, хранимого у типа"}])
        ok = value is None or {
            "text": isinstance(value, str), "date": isinstance(value, str), "person": isinstance(value, str),
            "number": isinstance(value, int | float) and not isinstance(value, bool), "bool": isinstance(value, bool),
            "choice": value in [o["value"] for o in (p.get("options") or [])]}[p["kind"]]
        if not ok:
            raise Problem(422, "invalid", f"Значение свойства «{p['title']}» не подходит",
                          errors=[{"field": f"values.{key}", "message": f"ожидается {p['kind']}"}])
