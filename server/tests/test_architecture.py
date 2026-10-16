"""Порядок зависимостей между модулями (9.2): модуль обращается только к модулям нижних
уровней и только через их `api`; ядро не зависит от модулей; таблицы модуля — в его
схеме, внешние ключи — только к своим таблицам, ядру или модулям ниже."""

import ast
from pathlib import Path

from app.core.db import Base
from app.models import load_all
from app.modules import INSTALLED, TIERS

ROOT = Path(__file__).resolve().parent.parent / "app"


def _imports(path: Path) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for node in ast.walk(ast.parse(path.read_text(), str(path))):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.append((node.module, node.lineno))
            out.extend((f"{node.module}.{a.name}", node.lineno) for a in node.names)
        elif isinstance(node, ast.Import):
            out.extend((a.name, node.lineno) for a in node.names)
    return out


def test_every_module_has_a_tier() -> None:
    present = {p.name for p in (ROOT / "modules").iterdir()
               if p.is_dir() and (p / "__init__.py").exists()}
    assert present <= set(TIERS), f"модули без уровня: {present - set(TIERS)}"
    assert set(INSTALLED) <= present


def test_core_depends_on_no_module() -> None:
    bad = [f"{p.relative_to(ROOT)}:{line} {name}"
           for p in (ROOT / "core").rglob("*.py") for name, line in _imports(p)
           if name.startswith("app.modules")]
    assert not bad, "ядро обращается к модулям:\n" + "\n".join(bad)


def test_modules_depend_downwards_through_api() -> None:
    bad: list[str] = []
    for module_dir in (ROOT / "modules").iterdir():
        if not module_dir.is_dir():
            continue
        me = module_dir.name
        for path in module_dir.rglob("*.py"):
            for name, line in _imports(path):
                parts = name.split(".")
                if parts[:2] != ["app", "modules"] or len(parts) < 3:
                    continue
                other = parts[2]
                if other == me:
                    continue
                where = f"{path.relative_to(ROOT)}:{line} → {name}"
                if TIERS.get(other, 99) >= TIERS[me]:
                    bad.append(f"{where}: «{me}» (уровень {TIERS[me]}) не может зависеть от "
                               f"«{other}» (уровень {TIERS.get(other)})")
                elif len(parts) > 3 and parts[3] != "api":
                    bad.append(f"{where}: к чужому модулю — только через его api")
    assert not bad, "\n".join(bad)


def test_tables_live_in_their_module_schema() -> None:
    load_all()
    bad: list[str] = []
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        parts = cls.__module__.split(".")
        owner = parts[2] if parts[:2] == ["app", "modules"] else "core"
        table = mapper.local_table
        if table.schema != owner:
            bad.append(f"{cls.__name__}: таблица в схеме {table.schema}, а модуль — {owner}")
        for fk in table.foreign_keys:
            target = fk.target_fullname.split(".")[0]
            if target not in {owner, "core"} and TIERS.get(target, 99) >= TIERS.get(owner, 0):
                bad.append(f"{cls.__name__}: внешний ключ на {fk.target_fullname} — не ниже")
    assert not bad, "\n".join(bad)
