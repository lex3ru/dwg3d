# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx", "openpyxl", "shapely", "ezdxf"]
# ///
"""Fill the stack for the load test (docs/ACCEPTANCE.md, 12.2), through the API as people would:

    uv run tools/acceptance/seed.py [--buildings 20] [--assets 50000] [--people 5000] [--users 50]

Makes the system administrator `load-admin` and the users `load-u01`… in Keycloak; the buildings
«Нагрузка NN», each from an office drawing of 5 floors (tools/acceptance/make_office.py, 105 rooms);
the objects spread over the rooms; the directory of people loaded from Excel, a hundred of them in
the rooms of each building. The first users administer a building, the rest see one. Passwords and
ids go to tools/acceptance/.state.json for load.py.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import os
import random
import sys
import tempfile
import time
from pathlib import Path

import httpx
from openpyxl import Workbook
from shapely.geometry import Point, Polygon

sys.path.insert(0, str(Path(__file__).parent))
from common import Keycloak, check, save_state, sign_in  # noqa: E402
from make_office import make  # noqa: E402

FIRST = ["Иван", "Пётр", "Анна", "Мария", "Олег", "Елена", "Сергей", "Ольга", "Дмитрий", "Наталья", "Алексей", "Ирина"]
LAST = ["Иванов", "Петров", "Сидоров", "Смирнов", "Кузнецов", "Попов", "Васильев", "Соколов", "Михайлов", "Новиков"]
DEPTS = ["Хирургия", "Терапия", "Бухгалтерия", "Хозяйственная служба", "Лаборатория", "Регистратура", "ИТ"]


async def gather(limit: int, jobs) -> list:
    sem = asyncio.Semaphore(limit)

    async def one(job):
        async with sem:
            return await job

    return await asyncio.gather(*(one(j) for j in jobs))


def people_xlsx(n: int, users: int) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["ФИО", "Должность", "Подразделение", "Почта"])
    rnd = random.Random(1)
    for i in range(n):
        if i < users:
            ws.append([f"Нагрузка Пользователь {i + 1:02d}", "Проверяющий", "Нагрузка", f"load-u{i + 1:02d}@example.test"])
        else:
            last, first = rnd.choice(LAST), rnd.choice(FIRST)
            ws.append([f"{last}{'а' if first[-1] in 'ая' else ''} {first} {i:05d}", "Сотрудник", rnd.choice(DEPTS),
                       f"person{i:05d}@load.test"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def points_in(poly: Polygon, k: int, rnd: random.Random) -> list[tuple[float, float]]:
    inner = poly.buffer(-0.3)
    inner = inner if not inner.is_empty else poly
    x0, y0, x1, y1 = inner.bounds
    out = []
    while len(out) < k:
        x, y = rnd.uniform(x0, x1), rnd.uniform(y0, y1)
        if inner.contains(Point(x, y)):
            out.append((round(x, 2), round(y, 2)))
    return out


async def main(a) -> None:
    t0 = time.time()
    state: dict = {"users": {}}
    async with httpx.AsyncClient(timeout=60) as http, Keycloak(http) as kc:
        state["admin"] = {"login": "load-admin", "password": await kc.user("load-admin", "Нагрузка", "Администратор", admin=True)}
        for k in range(1, a.users + 1):
            login = f"load-u{k:02d}"
            state["users"][login] = await kc.user(login, "Нагрузка", f"Пользователь {k:02d}")
    print(f"учётные записи: администратор и {a.users} пользователей")
    admin = await sign_in("load-admin", state["admin"]["password"], timeout=300)

    # ---- the directory
    r = check(await admin.post("/api/people/v1/people/import", files={"file": ("people.xlsx", people_xlsx(a.people, a.users))}))
    print("люди:", r.json() if len(r.text) < 300 else r.text[:300])
    # the list gives at most 500 at a time: ask by the beginning of the e-mail, a hundred at a time
    everyone = check(await admin.get("/api/people/v1/people", params={"q": "load-u"})).json()["items"]
    for k in range(a.people // 100 + 1):
        everyone += check(await admin.get("/api/people/v1/people", params={"q": f"person{k:03d}"})).json()["items"]
    by_email = {p.get("email"): p["id"] for p in everyone}
    staff = sorted(p["id"] for p in everyone if (p.get("email") or "").endswith("@load.test"))
    print(f"в справочнике {len(by_email)} человек")

    # ---- buildings from the office drawing
    dxf = Path(tempfile.mkdtemp()) / "Офис.dxf"
    make(dxf, 5)
    buildings = []
    for i in range(1, a.buildings + 1):
        b = check(await admin.post("/api/buildings/v1/buildings", json={"name": f"Нагрузка {i:02d}", "address": "проверка"})).json()
        check(await admin.post("/api/import/v1/drawings", data={"building_id": b["id"]},
                               files={"file": (dxf.name, dxf.read_bytes(), "application/dxf")}))
        buildings.append(b["id"])
    print(f"здания: {len(buildings)}, чертежи загружены — жду сборок")
    trees: dict[str, list] = {}
    while len(trees) < len(buildings):
        for b in buildings:
            if b in trees:
                continue
            floors = check(await admin.get(f"/api/buildings/v1/buildings/{b}/tree")).json()["floors"]
            if len(floors) == 5 and all(f["rooms"] for f in floors):
                trees[b] = floors
        print(f"  собрано {len(trees)} из {len(buildings)} ({time.time() - t0:.0f} с)")
        if len(trees) < len(buildings):
            await asyncio.sleep(10)

    # ---- objects, spread over the rooms of each floor
    types = check(await admin.get("/api/catalog/v1/types", params={"active": "true"})).json()["items"]
    rnd = random.Random(2)
    per_floor = a.assets // (len(buildings) * 5)
    jobs = []
    for bi, b in enumerate(buildings, 1):
        for f in trees[b]:
            plan = check(await admin.get(f"/api/buildings/v1/floors/{f['id']}/plan")).json()["plan"]
            polys = [Polygon(r["poly"][0], r["poly"][1:]) for r in plan["rooms"] if r.get("poly")]
            pts = [p for poly in polys for p in points_in(poly, per_floor // len(polys) + 1, rnd)][:per_floor]
            for c in range(0, len(pts), 100):
                t = rnd.choice(types)
                jobs.append(admin.post("/api/assets/v1/assets/batch", json={
                    "type_id": t["id"], "floor_id": f["id"], "points": pts[c:c + 100],
                    "prefix": f"Н{bi:02d}-{f['level']}-{c // 100}-", "start": 1, "width": 4}))
    done = await gather(8, jobs)
    for r in done:
        check(r, 201)
    print(f"объекты: {sum(len(r.json()['items']) for r in done)} ({time.time() - t0:.0f} с)")

    # ---- people in rooms, rights of the users
    puts = []
    for bi, b in enumerate(buildings):
        rooms = [r["id"] for f in trees[b] for r in f["rooms"]]
        for pid in staff[bi * 100:(bi + 1) * 100]:
            puts.append(admin.put(f"/api/people/v1/people/{pid}/assignments/{rnd.choice(rooms)}", json={}))
    for r in await gather(8, puts):
        check(r)
    grants = []
    for k in range(1, a.users + 1):
        b = buildings[(k - 1) % len(buildings)]
        role = "admin" if k <= a.users // 5 else "viewer"
        grants.append(admin.post("/api/access/v1/grants", json={
            "person_id": by_email[f"load-u{k:02d}@example.test"], "role": role,
            "scope": {"kind": "building", "id": b}, "building_id": b}))
    for r in await gather(8, grants):
        check(r, 201, 409)
    print(f"привязки: {len(puts)}, права: {len(grants)} ({time.time() - t0:.0f} с)")
    await admin.aclose()

    state.update(project=os.environ.get("COMPOSE_PROJECT_NAME", "twin"), buildings=buildings, users_of={f"load-u{k:02d}": buildings[(k - 1) % len(buildings)]
                                                for k in range(1, a.users + 1)},
                 admins=[f"load-u{k:02d}" for k in range(1, a.users // 5 + 1)])
    save_state(state)
    print(f"готово за {time.time() - t0:.0f} с; состояние — tools/acceptance/.state.json")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--buildings", type=int, default=20)
    p.add_argument("--assets", type=int, default=50000)
    p.add_argument("--people", type=int, default=5000)
    p.add_argument("--users", type=int, default=50)
    asyncio.run(main(p.parse_args()))
