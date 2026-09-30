from sqlalchemy import inspect, text

from dwg3d import db


def test_migrated_to_head(pg):
    with db.session() as s:
        assert s.execute(text("SELECT current_database()")).scalar() == pg.database
    assert "alembic_version" in inspect(db.engine()).get_table_names()
    db.migrate()                                  # idempotent


def test_session_rolls_back(pg):
    try:
        with db.session() as s:
            s.execute(text("CREATE TABLE tmp_rollback (x int)"))
            raise ValueError
    except ValueError:
        pass
    assert "tmp_rollback" not in inspect(db.engine()).get_table_names()
