"""python -m app <команда>: serve, worker, migrate, create-admin."""

import argparse
import logging
import signal
import sys

from sqlalchemy import text


def migrate() -> None:
    from alembic import command
    from alembic.config import Config as AlembicConfig

    from app.core.db import engine

    here = __import__("pathlib").Path(__file__).resolve().parent.parent
    cfg = AlembicConfig(str(here / "alembic.ini"))
    cfg.set_main_option("script_location", str(here / "migrations"))
    # одна миграция за раз, даже если запущены приложение и обработчик задач сразу
    with engine().connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(7310001)"))
        try:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
            conn.commit()
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(7310001)"))


def seed() -> None:
    from app.core.db import transaction
    from app.main import installed_modules

    for module in installed_modules():
        if module.seed:
            with transaction() as session:
                done = module.seed(session)
            if done:
                logging.getLogger("app").info("seed: %s", done)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="приложение (с миграцией базы)")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    sub.add_parser("worker", help="обработчик фоновых задач")
    sub.add_parser("migrate", help="обновить базу до текущей версии")
    admin = sub.add_parser("create-admin", help="первый администратор, если его ещё нет")
    admin.add_argument("--login", default="admin")
    admin.add_argument("--name", default="Администратор")
    admin.add_argument("--password", help="временный пароль (для автоматических тестов); "
                       "без него система придумает сама")
    sample = sub.add_parser("sample", help="тестовое здание (ТЗ 7.2)")
    sample.add_argument("which", choices=["polyclinic"])
    sample.add_argument("--login", default="admin", help="от чьего имени (администратор)")
    sample.add_argument("--name", default="Поликлиника")
    reset = sub.add_parser("reset-password",
                           help="временный пароль учётной записи, если войти некому")
    reset.add_argument("login")
    args = parser.parse_args()
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.command == "migrate":
        migrate()
    elif args.command == "serve":
        import uvicorn

        migrate()
        seed()
        uvicorn.run("app.main:create_app", factory=True, host=args.host, port=args.port,
                    proxy_headers=True, forwarded_allow_ips="*")
    elif args.command == "worker":
        from app.core import tasks
        from app.main import installed_modules

        installed_modules()  # модули регистрируют свои задачи
        stopping = False

        def stop(*_: object) -> None:
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        tasks.run_worker(lambda: stopping)
    elif args.command == "create-admin":
        from app.core.db import transaction
        from app.modules.access import api

        with transaction() as session:
            temporary = api.create_first_admin(session, args.login, args.name, args.password)
        if temporary is None:
            print("Администратор уже есть — ничего не сделано.")
        else:
            print(f"Администратор «{args.login}» заведён. Временный пароль: {temporary}")
            print("При первом входе система попросит сменить его.")
    elif args.command == "sample":
        from app.core.db import transaction
        from app.main import installed_modules
        from app.modules.access import api as access
        from app.samples import polyclinic

        installed_modules()
        with transaction() as session:
            account = access.find(session, args.login)
            if account is None or account.role != "admin":
                print(f"Администратора «{args.login}» нет.")
                sys.exit(1)
            result = polyclinic.create(session, access.actor_of(account), args.name)
        print(f"Здание «{args.name}» создано: {result['building_id']}")
    elif args.command == "reset-password":
        from app.core.db import transaction
        from app.modules.access import api

        with transaction() as session:
            account = api.find(session, args.login)
            if account is None:
                print(f"Учётной записи «{args.login}» нет.")
                sys.exit(1)
            _, temporary = api.reset_password(session, None, account.id)
        print(f"Пароль «{args.login}» сброшен. Временный пароль: {temporary}")
        print("При входе система попросит сменить его.")
    sys.exit(0)


if __name__ == "__main__":
    main()
