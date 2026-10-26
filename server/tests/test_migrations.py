"""Миграции приводят базу в точности к тому, что описано в models.py."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.core.db import Base, engine
from app.models import load_all
from app.modules import TIERS


def test_migrations_match_models() -> None:
    load_all()
    with engine().connect() as conn:
        context = MigrationContext.configure(conn, opts={
            "include_schemas": True, "compare_type": True,
            "include_name": lambda name, type_, _: type_ != "schema"
            or name in {"core", *TIERS},
        })
        diff = [d for d in compare_metadata(context, Base.metadata)
                if not (isinstance(d, tuple) and d[0] in {"remove_table"}
                        and d[1].name == "alembic_version")]
    assert not diff, diff


def _alembic(action: str, revision: str) -> None:
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    here = Path(__file__).resolve().parents[1]
    cfg = Config(str(here / "alembic.ini"))
    cfg.set_main_option("script_location", str(here / "migrations"))
    with engine().connect() as conn:
        cfg.attributes["connection"] = conn
        getattr(command, action)(cfg, revision)
        conn.commit()


def test_0013_moves_count_recount_of_drafts_to_the_position(admin) -> None:  # type: ignore[no-untyped-def]
    """ADR-0005: пересчёт по типу в черновике ведомости получает модель, если позиция у типа
    в этом месте одна; позиций несколько — пересчёт удаляется; позиций нет — без модели.
    Проведённые ведомости не трогаются."""
    from sqlalchemy import text

    from app.core.db import transaction
    from tests.test_inventory import document, post, setup

    _, rooms, _, k = setup(admin)
    place = rooms["214"]

    def kind(name: str) -> str:
        r = admin.post("/api/catalog/types", json={"name": name, "accounting": "quantity"})
        return r.json()["id"]

    def model(type_id: str, name: str) -> str:
        r = admin.post(f"/api/catalog/types/{type_id}/models", json={"name": name})
        return next(m["id"] for m in r.json()["models"] if m["name"] == name)

    gloves, covers, paper = k["перчатки"]["id"], kind("Бахилы"), kind("Бумага")
    m, s, pairs = model(gloves, "M"), model(gloves, "S"), model(covers, "100 пар")
    got = document(admin, "receipt", {"to_place": place}, [
        {"type_id": gloves, "model_id": m, "qty": 10, "price": 1},
        {"type_id": gloves, "model_id": s, "qty": 5, "price": 1},
        {"type_id": covers, "model_id": pairs, "qty": 25, "price": 1},
    ])
    assert post(admin, got).status_code == 200
    done = admin.post("/api/inventory/counts", json={"places": [place]}).json()
    assert admin.post(f"/api/inventory/counts/{done['id']}/post",
                      json={"version": done["version"]}).status_code == 200
    draft = admin.post("/api/inventory/counts", json={"places": [place]}).json()

    try:
        _alembic("downgrade", "0012")
        with transaction() as session:
            for doc, type_id in [(draft, gloves), (draft, covers), (draft, paper),
                                 (done, covers)]:
                session.execute(text(
                    "INSERT INTO inventory.count_stock (document_id, place, type_id, counted) "
                    "VALUES (:d, :p, :t, 7)"), {"d": doc["id"], "p": place, "t": type_id})
    finally:
        _alembic("upgrade", "head")

    with transaction() as session:
        rows = session.execute(text(
            "SELECT document_id::text, type_id::text, model_id::text "
            "FROM inventory.count_stock ORDER BY 1, 2")).all()
    assert sorted(rows) == sorted([
        (draft["id"], covers, pairs),
        (draft["id"], paper, None),
        (done["id"], covers, None),
    ])
