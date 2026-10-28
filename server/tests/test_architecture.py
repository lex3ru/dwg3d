"""Порядок зависимостей между модулями (9.2): модуль обращается только к модулям нижних
уровней и только через их `api`; ядро не зависит от модулей; таблицы модуля — в его
схеме, внешние ключи — только к своим таблицам, ядру или модулям ниже."""

import ast
import re
from pathlib import Path

from app.core.db import Base
from app.models import load_all
from app.modules import INSTALLED, TIERS

ROOT = Path(__file__).resolve().parent.parent / "app"
# SQL к таблице в схеме: «FROM inventory.unit», «JOIN "inventory".unit», «UPDATE inventory.unit»
SQL_TABLE = re.compile(r'\b(?:FROM|JOIN|INTO|UPDATE|TABLE|TRUNCATE)\s+(?:ONLY\s+)?"?(\w+)"?\s*\.',
                       re.IGNORECASE)


def _imports(path: Path, root: Path) -> list[tuple[str, int]]:
    """Что файл пакета `app` (каталог `root`) берёт из других модулей Python, в абсолютных
    именах: импорты, в том числе относительные; строки «app.modules.…» (importlib,
    __import__); SQL к таблицам схемы модуля — как «app.modules.<схема>.<sql>» (R-010)."""
    package = ["app", *path.relative_to(root).parent.parts]
    out: list[tuple[str, int]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), str(path))):
        if isinstance(node, ast.ImportFrom):
            base = package[:len(package) - node.level + 1] if node.level else []
            module = ".".join([*base, *(node.module or "").split(".")]).strip(".")
            out.extend((f"{module}.{a.name}", node.lineno) for a in node.names)
        elif isinstance(node, ast.Import):
            out.extend((a.name, node.lineno) for a in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith("app.modules."):
                out.append((node.value, node.lineno))
            out.extend((f"app.modules.{m[1]}.<sql>", node.lineno)
                       for m in SQL_TABLE.finditer(node.value) if m[1] in TIERS)
    return out


def test_every_module_has_a_tier() -> None:
    present = {p.name for p in (ROOT / "modules").iterdir()
               if p.is_dir() and (p / "__init__.py").exists()}
    assert present <= set(TIERS), f"модули без уровня: {present - set(TIERS)}"
    assert set(INSTALLED) <= present


def test_core_depends_on_no_module() -> None:
    bad = [f"{p.relative_to(ROOT)}:{line} {name}"
           for p in (ROOT / "core").rglob("*.py") for name, line in _imports(p, ROOT)
           if name.startswith("app.modules")]
    assert not bad, "ядро обращается к модулям:\n" + "\n".join(bad)


def _module_violations(root: Path) -> list[str]:
    """Нарушения правил 9.2 в модулях `root/modules/*`; `root` — каталог пакета `app`."""
    bad: list[str] = []
    for module_dir in sorted((root / "modules").iterdir()):
        if not module_dir.is_dir():
            continue
        me = module_dir.name
        for path in sorted(module_dir.rglob("*.py")):
            for name, line in _imports(path, root):
                parts = name.split(".")
                if parts[:2] != ["app", "modules"] or len(parts) < 3:
                    continue
                other = parts[2]
                if other == me:
                    continue
                where = f"{path.relative_to(root).as_posix()}:{line} → {name}"
                if TIERS.get(other, 99) >= TIERS[me]:
                    bad.append(f"{where}: «{me}» (уровень {TIERS[me]}) не может зависеть от "
                               f"«{other}» (уровень {TIERS.get(other)})")
                elif parts[3:4] == ["<sql>"]:
                    bad.append(f"{where}: SQL к таблицам чужого модуля — только через его api")
                elif parts[3:4] != ["api"]:
                    # пакет модуля целиком («from app.modules import inventory») — тоже обход
                    bad.append(f"{where}: к чужому модулю — только через его api")
    return bad


def test_modules_depend_downwards_through_api() -> None:
    bad = _module_violations(ROOT)
    assert not bad, "\n".join(bad)


# Обходы правил модулей, которые ревью подложило в копию кода (R-010)
BYPASSES = {
    "link/zz_import.py": "import app.modules.inventory.units\n",
    "catalog/zz_relative.py": "from ..inventory import units\n",
    "link/zz_package.py": "from app.modules import inventory\n\ninventory.units\n",
    "link/zz_sql.py": 'from sqlalchemy import text\n\nQ = text("SELECT id FROM inventory.unit")\n',
    "link/zz_importlib.py": ('import importlib\n\n'
                            'importlib.import_module("app.modules.inventory.units")\n'),
}


def test_module_rule_bypasses_are_caught(tmp_path: Path) -> None:
    for name, source in BYPASSES.items():
        path = tmp_path / "modules" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    bad = _module_violations(tmp_path)
    caught = {line.split(":")[0] for line in bad}
    assert caught == {f"modules/{name}" for name in BYPASSES}, "\n".join(bad)


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


def test_r013_second_create_app_does_not_double_subscriptions(app) -> None:  # type: ignore[no-untyped-def]
    """Модули подписываются (`on_*`, `register`) в `create_app()`; второй вызов в том же
    процессе не удваивает подписчиков — иначе каждое событие обрабатывалось бы дважды (R-013)."""
    import sys

    from app.main import create_app

    def lists() -> dict[str, list]:  # type: ignore[type-arg]
        return {f"{name}.{attr}": value for name, module in list(sys.modules.items())
                if name.startswith("app.") and module is not None
                for attr, value in vars(module).items() if type(value) is list}

    before = {k: list(v) for k, v in lists().items()}
    try:
        create_app()
        grown = {k: (len(before[k]), len(v)) for k, v in lists().items()
                 if k in before and len(v) != len(before[k])}
        assert not grown, grown
    finally:
        for k, v in lists().items():
            if k in before:
                v[:] = before[k]


def test_uploads_are_received_after_the_access_check() -> None:
    """ADR-0012: FastAPI разбирает `UploadFile`, `File` и `Form` раньше проверки входа — тело
    ложится на диск и без прав. Файл принимает зависимость `core/uploads.py` (R-014)."""
    found = []
    for path in sorted(ROOT.rglob("routes.py")):
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), 1):
            if re.search(r"\b(UploadFile|File|Form)\b", line):
                found.append(f"{path.relative_to(ROOT)}:{line_no}: {line.strip()}")
    assert not found, "\n".join(found)
