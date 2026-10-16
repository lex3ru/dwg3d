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


module = Module(name="catalog", title="Каталог", routers=[router], seed=seed)
