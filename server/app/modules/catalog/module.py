from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.module import Module
from app.modules.catalog.routes import router

BASE = Path(__file__).with_name("base.xlsx")


def seed(session: Session) -> str | None:
    """Базовый каталог медицинского учреждения (7.1) — один раз, в пустой каталог; правки
    администратора обновление не перезаписывает."""
    from app.core.actor import Actor
    from app.modules.catalog import excel
    from app.modules.catalog.models import ItemType, Layer

    if session.scalar(select(func.count()).select_from(Layer)) or session.scalar(
        select(func.count()).select_from(ItemType)
    ):
        return None
    system = Actor(
        user_id=__import__("uuid").UUID(int=0), login="system", full_name="система", role="admin"
    )
    with open(BASE, "rb") as f:
        result = excel.load(session, system, f, apply=True)
    if not result["applied"]:
        raise RuntimeError(f"базовый каталог не загрузился: {result['errors'][:3]}")
    return f"базовый каталог: типов {len(result['created'].get('Типы', []))}"


MODELS = Path(__file__).with_name("models3d")


def seed_models(session: Session) -> str | None:
    """3D-модели базового каталога (models3d/index.json): тип получает модель из комплекта,
    если своей у него нет и администратор модель не загружал и не убирал. Источник и
    лицензия каждой модели — в docs/3D-MODELS.md и в карточке типа."""
    import json
    import uuid

    from app.core.actor import Actor
    from app.modules.catalog import model3d
    from app.modules.catalog.models import ItemType

    index = MODELS / "index.json"
    if not index.exists():
        return None
    system = Actor(user_id=uuid.UUID(int=0), login="system", full_name="система", role="admin")
    done = 0
    for entry in json.loads(index.read_text(encoding="utf-8")):
        t = session.scalar(select(ItemType).where(ItemType.name == entry["type"]))
        if t is None or t.model_file_id is not None or t.model_credit is not None:
            continue
        with open(MODELS / entry["file"], "rb") as f:
            model3d.attach(
                session,
                system,
                t.id,
                f,
                entry["file"],
                credit=entry["credit"],
                transform={"rx": 0, "ry": entry.get("ry", 0), "rz": 0, "scale": 1, "fit": True},
            )
        done += 1
    return f"3D-модели каталога: {done}" if done else None


def seed_all(session: Session) -> str | None:
    parts = [p for p in (seed(session), seed_models(session)) if p]
    return "; ".join(parts) or None


def _setup(_: object) -> None:
    from app.modules.catalog import api
    from app.modules.files import api as files

    # каталог виден всем, и гостю по ссылке — 3D: файлы моделей открыты всем (5.7.2)
    files.on_file_access(api.is_model_file)


module = Module(name="catalog", title="Каталог", routers=[router], seed=seed_all, setup=_setup)
