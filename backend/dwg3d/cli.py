"""Command line interface.

  python -m dwg3d build plan.dwg -o out/ [-c my_config.yaml]
  python -m dwg3d analyze plan.dwg        # layers + detected floors, no 3D
  python -m dwg3d db upgrade              # migrate PostgreSQL to the latest schema
  python -m dwg3d catalog load [file]     # upsert the catalog from YAML (catalog_seed.yaml)
  python -m dwg3d migrate-files [--dry-run]  # import data/jobs/*/job.json into PostgreSQL
  python -m dwg3d worker [-n 2]           # build-only process sharing the queue with the API
  python -m dwg3d user add LOGIN --role editor [--name "Имя"]   # asks for the password
  python -m dwg3d user passwd LOGIN | role LOGIN ROLE | disable LOGIN | enable LOGIN | list
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from pathlib import Path

from .config import load_config
from .pipeline import analyze, run


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dwg3d")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build model.glb + metadata.json")
    b.add_argument("input")
    b.add_argument("-o", "--out", default="out")
    b.add_argument("-c", "--config", help="YAML/JSON config override")
    b.add_argument("--no-debug", action="store_true", help="skip debug PNGs")
    a = sub.add_parser("analyze", help="print layers and floor candidates")
    a.add_argument("input")
    a.add_argument("-c", "--config")
    d = sub.add_parser("db", help="database schema (DWG3D_DATABASE_URL)")
    d.add_argument("action", choices=["upgrade", "current"])
    k = sub.add_parser("catalog", help="equipment catalog in the database")
    k.add_argument("action", choices=["load"])
    k.add_argument("file", nargs="?", help="YAML (default: dwg3d/catalog_seed.yaml)")
    m = sub.add_parser("migrate-files", help="import file-based projects (job.json) into the database")
    m.add_argument("--dry-run", action="store_true", help="only print what would be imported")
    m.add_argument("--data", help="data directory (default: DWG3D_DATA or <project>/data)")
    w = sub.add_parser("worker", help="run build workers only (no HTTP)")
    w.add_argument("-n", type=int, default=2, help="worker threads")
    u = sub.add_parser("user", help="users and roles (viewer, editor, catalog_admin)")
    u.add_argument("action", choices=["add", "passwd", "role", "disable", "enable", "list"])
    u.add_argument("login", nargs="?")
    u.add_argument("new_role", nargs="?", help="for `role`")
    u.add_argument("--role", default="viewer", choices=["viewer", "editor", "catalog_admin"], help="for `add`")
    u.add_argument("--name", default="", help="for `add`: name shown in the journal")
    u.add_argument("--password-stdin", action="store_true", help="read the password from stdin (scripts)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose or args.cmd == "build" else logging.WARNING,
                        format="%(message)s")

    if args.cmd == "db":
        from alembic import command

        from . import db
        if args.action == "upgrade":
            db.migrate()
        command.current(db.alembic_config())
        return 0
    if args.cmd == "catalog":
        from . import catalog, db
        db.migrate()
        try:
            print(json.dumps(catalog.load(Path(args.file) if args.file else catalog.SEED), ensure_ascii=False))
        except catalog.CatalogError as ex:
            print(f"Ошибка в каталоге: {ex}", file=sys.stderr)
            return 1
        return 0
    if args.cmd == "migrate-files":
        from . import db, migrate_files
        db.migrate()
        st = migrate_files.migrate(args.data and Path(args.data), dry_run=args.dry_run)
        print(("Будет перенесено" if args.dry_run else "Перенесено") +
              f": проектов {st['imported']} (уже в базе {st['skipped']}, не читается {st['unreadable']}), "
              f"сборок {st['builds']}, этажей {st['floors']}, оборудования {st['furniture']}, меток {st['pins']}")
        if args.dry_run:
            return 0
        problems = migrate_files.verify(args.data and Path(args.data))
        for x in problems:
            print("  ! " + x)
        print("Сверка с файлами: " + ("расхождений нет" if not problems else f"расхождений {len(problems)}"))
        return 1 if problems else 0
    if args.cmd == "user":
        return _user_cmd(args)
    if args.cmd == "worker":
        from . import worker
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
        worker.serve(args.n)
        return 0
    if args.cmd == "build":
        meta = run(args.input, args.out, args.config, debug_png=not args.no_debug)
        print(f"\n{meta['model']}: {len(meta['floors'])} floors, {meta['triangles']} triangles, "
              f"{meta['elapsed_s']} s -> {Path(args.out).resolve()}")
        for f in meta["floors"]:
            print(f"  {f['id']:>4} L{f['level']:>3}  {f['name']:<32} elev {f['elevation']:>7.2f}  "
                  f"h {f['height']:.2f} ({f['height_source']})  {f['stats']['openings']}  rooms {f['stats']['rooms']}")
        for w in meta["warnings"]:
            print("  ! " + w)
    else:
        cfg = load_config(args.config)
        with tempfile.TemporaryDirectory() as tmp:
            d, cands, info = analyze(Path(args.input), Path(tmp), cfg)
        print(json.dumps({k: v for k, v in info.items() if k != "layers"}, ensure_ascii=False, indent=1))
        print("\nLayers:")
        for name, st in info["layers"].items():
            print(f"  {str(st['role'] or '-'):8} {st['count']:>6}  {name}")
        print("\nFloor candidates:")
        for c in cands:
            print(f"  {c.id:>4} {c.source:8} level={c.level} kind={c.kind} include={c.include} "
                  f"mark={c.mark} name={c.name!r}")


def _user_cmd(args) -> int:
    import getpass

    from . import auth, db
    db.migrate()

    def password() -> str:
        if args.password_stdin:
            return sys.stdin.readline().rstrip("\n")
        p1 = getpass.getpass("Пароль: ")
        if p1 != getpass.getpass("Ещё раз: "):
            raise auth.UserError("пароли не совпадают")
        return p1

    try:
        if args.action == "list":
            for x in auth.list_users():
                print(f"  {x['login']:<20} {x['role']:<14} {'' if x['active'] else 'отключён':<9} "
                      f"{x['name']:<30} вход: {x['last_login'] or '—'}")
            return 0
        if not args.login:
            raise auth.UserError("нужен логин")
        if args.action == "role" and args.new_role not in auth.ROLES:
            raise auth.UserError(f"роль: {', '.join(auth.ROLES)}")
        if args.action == "add":
            auth.add_user(args.login, password(), role=args.role, name=args.name)
        elif args.action == "passwd":
            auth.set_password(args.login, password())
        elif args.action == "role":
            auth.set_role(args.login, args.new_role or "")
        else:
            auth.set_active(args.login, args.action == "enable")
        print("Готово")
        return 0
    except auth.UserError as ex:
        print(f"Ошибка: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
