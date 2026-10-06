"""The reconciliation after a restore (docs/ACCEPTANCE.md, 12.3): is the restored stack the stack it was copied from?

    python tools/acceptance/compare.py snapshot <project> <file.json>   # what a stack holds
    python tools/acceptance/compare.py diff <a.json> <b.json>           # two snapshots side by side
    python tools/acceptance/compare.py check <project>                  # links between the services

A snapshot: for every table of every database the number of rows and a checksum of their contents,
and every file of the object storage with its checksum. `diff` lists what differs; the bookkeeping of
the event bus (inbox, outbox) and the gateway's sessions are reported apart, since a stack that runs
changes them by itself. `check` follows the links one service keeps to another's data
(docs/DATA_MODEL.md, 11): objects and people in rooms that exist, rights of people that exist,
drawings the import knows, types the catalog knows. <project> is the compose project: twin for the
working stack. Exit code 1 when something differs.
"""
from __future__ import annotations

import json
import subprocess
import sys

VOLATILE = {"inbox", "outbox", "sessions"}
SKIP_DATABASES = {"keycloak"}            # Keycloak writes its own sessions and events; checked by signing in


def psql(project: str, db: str, sql: str) -> list[list[str]]:
    out = subprocess.run(["docker", "exec", "-i", f"{project}-db-1", "psql", "-U", "twin", "-d", db, "-AtF", "\t", "-c", sql],
                         check=True, capture_output=True, text=True).stdout
    return [line.split("\t") for line in out.splitlines() if line]


def snapshot(project: str) -> dict:
    out: dict = {"databases": {}, "files": {}}
    dbs = [r[0] for r in psql(project, "postgres", "select datname from pg_database where not datistemplate "
                                                   "and datname <> 'postgres' order by 1")]
    for db in dbs:
        if db in SKIP_DATABASES:
            continue
        tables = [r[0] for r in psql(project, db, "select table_name from information_schema.tables "
                                                  "where table_schema = 'public' order by 1")]
        out["databases"][db] = {}
        for t in tables:
            n, digest = psql(project, db, f'select count(*), md5(coalesce(string_agg(md5(t::text), \'\' '
                                          f'order by md5(t::text)), \'\')) from "{t}" t')[0]
            out["databases"][db][t] = {"rows": int(n), "md5": digest}
    files = subprocess.run(["docker", "exec", f"{project}-s3-1", "sh", "-c",
                            "cd /data && find . -type f ! -path './.rustfs.sys/*' -exec md5sum {} +"],
                           check=True, capture_output=True, text=True).stdout
    for line in files.splitlines():
        digest, path = line.split(None, 1)
        out["files"][path] = digest
    return out


def diff(a: dict, b: dict) -> int:
    bad = 0
    for db in sorted(set(a["databases"]) | set(b["databases"])):
        ta, tb = a["databases"].get(db, {}), b["databases"].get(db, {})
        for t in sorted(set(ta) | set(tb)):
            x, y = ta.get(t), tb.get(t)
            if x == y:
                continue
            note = f"{db}.{t}: {x and x['rows']} → {y and y['rows']} строк" + ("" if x and y and x["rows"] != y["rows"]
                                                                              else ", содержимое другое")
            if t in VOLATILE:
                print(f"  служебное, меняется само: {note}")
            else:
                print(f"  РАСХОЖДЕНИЕ {note}")
                bad += 1
    fa, fb = a["files"], b["files"]
    missing = sorted(set(fa) - set(fb))
    extra = sorted(set(fb) - set(fa))
    changed = sorted(p for p in set(fa) & set(fb) if fa[p] != fb[p])
    for label, items in (("нет файла", missing), ("лишний файл", extra), ("другой файл", changed)):
        for p in items[:10]:
            print(f"  РАСХОЖДЕНИЕ {label}: {p}")
        bad += len(items)
    rows = sum(t["rows"] for d in a["databases"].values() for t in d.values())
    print(f"таблиц {sum(len(d) for d in a['databases'].values())}, строк {rows}, файлов {len(fa)}; расхождений: {bad}")
    return bad


def ids(project: str, db: str, sql: str) -> set[str]:
    return {r[0] for r in psql(project, db, sql)}


def check(project: str) -> int:
    rooms = ids(project, "buildings", "select id from rooms where status = 'active'")
    all_rooms = ids(project, "buildings", "select id from rooms")
    floors = ids(project, "buildings", "select id from floors")
    buildings = ids(project, "buildings", "select id from buildings")
    persons = ids(project, "people", "select id from persons")
    assets = ids(project, "assets", "select id from assets")
    types = ids(project, "catalog", "select id from types")
    drawings = ids(project, "import", "select id from drawings")
    problems: list[str] = []

    def need(what: str, rows: list[list[str]]):
        if rows:
            problems.append(f"{what}: {len(rows)}, например {rows[0]}")

    placed = psql(project, "assets", "select id, room_id, floor_id, type_id, needs_placement from assets "
                                     "where state <> 'retired' and container_id is null")
    need("объекты в несуществующих или снятых помещениях без «требует размещения»",
         [r for r in placed if r[1] and r[1] not in rooms and r[4] != "t"])
    need("объекты на несуществующих этажах", [r for r in placed if r[2] and r[2] not in floors])
    need("объекты неизвестных каталогу типов", [r for r in psql(project, "assets", "select id, type_id from assets")
                                                if r[1] not in types])
    need("люди привязаны к несуществующим или снятым помещениям",
         [r for r in psql(project, "people", "select person_id, room_id from assignments") if r[1] not in rooms])
    grants = psql(project, "access", "select id, person_id, scope_kind, scope_id, building_id from grants")
    need("права у несуществующих людей", [g for g in grants if g[1] not in persons])
    scopes = {"building": buildings, "floor": floors, "room": all_rooms, "asset": assets}
    need("права на несуществующие области", [g for g in grants if g[3] not in scopes.get(g[2], set())])
    need("права в несуществующих зданиях", [g for g in grants if g[4] not in buildings])
    need("чертежи зданий, которых нет в импорте",
         [r for r in psql(project, "buildings", "select id from drawings") if r[0] not in drawings])
    for p in problems:
        print("  РАСХОЖДЕНИЕ", p)
    print(f"помещений {len(rooms)}, объектов {len(assets)}, людей {len(persons)}, прав {len(grants)}; "
          f"расхождений связей: {len(problems)}")
    return len(problems)


if __name__ == "__main__":
    cmd = sys.argv[1:2]
    if cmd == ["snapshot"] and len(sys.argv) == 4:
        with open(sys.argv[3], "w") as f:
            json.dump(snapshot(sys.argv[2]), f)
        print(f"снимок {sys.argv[2]} → {sys.argv[3]}")
    elif cmd == ["diff"] and len(sys.argv) == 4:
        sys.exit(1 if diff(*(json.load(open(p)) for p in sys.argv[2:4])) else 0)
    elif cmd == ["check"] and len(sys.argv) == 3:
        sys.exit(1 if check(sys.argv[2]) else 0)
    else:
        print(__doc__)
        sys.exit(2)
