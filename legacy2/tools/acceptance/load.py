# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
"""The load test (docs/ACCEPTANCE.md, 12.2) on what seed.py made:

    uv run tools/acceptance/load.py [--users 50] [--minutes 5] [--think 0.5:1.5]

Each user signs in with its own account (through Keycloak, as a browser) and goes about its building
as the interface does: the cabinet, the tree and plans of floors, lists of rooms, objects and people,
an object's card with its history; administrators of a building also read the journal and now and then
change an object's note. Between steps a user thinks for a random while. In the end: for each kind of
request the count, errors, median, 95th percentile and the longest; the verdict — 95 % of reads faster
than a second and no errors. Exit code 1 when it fails.
"""
from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from common import load_state, sign_in  # noqa: E402

READS: dict[str, list[float]] = defaultdict(list)
WRITES: dict[str, list[float]] = defaultdict(list)
ERRORS: dict[str, list[str]] = defaultdict(list)


class User:
    def __init__(self, login: str, password: str, building: str, admin: bool, think: tuple[float, float]):
        self.login, self.password, self.building, self.admin, self.think = login, password, building, admin, think
        self.rnd = random.Random(login)
        self.floors: list[dict] = []
        self.assets: list[str] = []
        self.http: httpx.AsyncClient | None = None

    async def get(self, label: str, path: str, **params) -> httpx.Response | None:
        return await self._do("GET", label, path, params=params)

    async def _do(self, method: str, label: str, path: str, **kw) -> httpx.Response | None:
        t = time.perf_counter()
        try:
            r = await self.http.request(method, path, **kw)
        except httpx.HTTPError as ex:
            ERRORS[label].append(f"{type(ex).__name__}")
            return None
        (READS if method == "GET" else WRITES)[label].append(time.perf_counter() - t)
        if r.status_code >= 400:
            ERRORS[label].append(f"{r.status_code} {r.text[:120]}")
            return None
        return r

    async def run(self, until: float) -> None:
        self.http = await sign_in(self.login, self.password)
        await self.get("me", "/api/people/v1/me")
        b = self.building
        r = await self.get("tree", f"/api/buildings/v1/buildings/{b}/tree")
        self.floors = r.json()["floors"] if r else []
        steps = [self.cabinet, self.tree, self.assets_list, self.asset_card, self.rooms, self.room, self.plan, self.people]
        if self.admin:
            steps += [self.journal, self.edit]
        while time.monotonic() < until:
            await self.rnd.choice(steps)()
            await asyncio.sleep(self.rnd.uniform(*self.think))
        await self.http.aclose()

    # ---- what a user does
    async def cabinet(self):
        await self.get("cabinet", "/api/views/cabinet", building_id=self.building)

    async def tree(self):
        await self.get("tree", f"/api/buildings/v1/buildings/{self.building}/tree")

    async def assets_list(self):
        params = {"building_id": self.building, "limit": 50}
        if self.rnd.random() < 0.5 and self.floors:
            params["floor_id"] = self.rnd.choice(self.floors)["id"]
        if self.rnd.random() < 0.3:
            params["q"] = f"-{self.rnd.randint(1, 5)}-"
        r = await self.get("assets", "/api/assets/v1/assets", **params)
        if r:
            self.assets = [a["id"] for a in r.json()["items"]] or self.assets

    async def asset_card(self):
        if not self.assets:
            return await self.assets_list()
        a = self.rnd.choice(self.assets)
        await self.get("asset", f"/api/assets/v1/assets/{a}")
        await self.get("asset history", f"/api/assets/v1/assets/{a}/history")

    async def rooms(self):
        await self.get("rooms", "/api/buildings/v1/rooms", building_id=self.building)

    def _room(self) -> str | None:
        rooms = [r for f in self.floors for r in f["rooms"]]
        return self.rnd.choice(rooms)["id"] if rooms else None

    async def room(self):
        if (room := self._room()) is None:
            return
        await self.get("room", f"/api/buildings/v1/rooms/{room}")
        await self.get("room people", f"/api/people/v1/rooms/{room}/people")
        await self.get("room assets", "/api/assets/v1/assets", room_id=room, limit=50)

    async def plan(self):
        if self.floors:
            await self.get("plan", f"/api/buildings/v1/floors/{self.rnd.choice(self.floors)['id']}/plan")

    async def people(self):
        await self.get("people", "/api/people/v1/people", building_id=self.building, limit=50)

    async def journal(self):
        await self.get("journal", "/api/journal/v1/events", building_id=self.building, limit=50)

    async def edit(self):
        if not self.assets:
            return await self.assets_list()
        a = await self.get("asset", f"/api/assets/v1/assets/{self.rnd.choice(self.assets)}")
        if a:
            body = a.json()
            r = await self._do("PATCH", "edit asset", f"/api/assets/v1/assets/{body['id']}",
                               json={"note": f"проверка {time.time():.0f}", "version": body["version"]})
            if r is None and ERRORS["edit asset"] and ERRORS["edit asset"][-1].startswith("409"):
                ERRORS["edit asset"].pop()      # someone else changed it a moment before: not a failure


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))] if xs else 0.0


def report(minutes: float, users: int) -> bool:
    print(f"\n{users} пользователей, {minutes:g} мин\n")
    print(f"{'запрос':<16}{'число':>8}{'ошибок':>8}{'медиана':>10}{'95 %':>9}{'макс.':>9}   мс")
    for kind, table in (("чтение", READS), ("изменение", WRITES)):
        for label in sorted(table):
            xs = table[label]
            print(f"{label:<16}{len(xs):>8}{len(ERRORS.get(label, [])):>8}{statistics.median(xs) * 1000:>10.0f}"
                  f"{pct(xs, 95) * 1000:>9.0f}{max(xs) * 1000:>9.0f}   {kind}")
    reads = [x for xs in READS.values() for x in xs]
    errors = sum(len(e) for e in ERRORS.values())
    p95 = pct(reads, 95)
    total = len(reads) + sum(len(x) for x in WRITES.values())
    print(f"\nвсего запросов {total} ({total / (minutes * 60):.0f} в секунду), чтение: 95 % быстрее {p95 * 1000:.0f} мс, "
          f"ошибок {errors}")
    for label, errs in ERRORS.items():
        if errs:
            print(f"  {label}: {errs[:3]}")
    ok = p95 < 1.0 and errors == 0
    print("ПРИНЯТО" if ok else "НЕ ПРИНЯТО")
    return ok


async def main(a) -> int:
    state = load_state()
    if not state.get("users"):
        print("нет tools/acceptance/.state.json — сначала seed.py")
        return 2
    think = tuple(float(x) for x in a.think.split(":"))
    logins = sorted(state["users"])[:a.users]
    users = [User(u, state["users"][u], state["users_of"][u], u in state["admins"], think) for u in logins]
    until = time.monotonic() + a.minutes * 60
    started = await asyncio.gather(*(u.run(until) for u in users), return_exceptions=True)
    failed = [f"{u.login}: {ex}" for u, ex in zip(users, started) if isinstance(ex, Exception)]
    for f in failed:
        print("не отработал:", f)
    return 0 if report(a.minutes, len(users)) and not failed else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--users", type=int, default=50)
    p.add_argument("--minutes", type=float, default=5)
    p.add_argument("--think", default="0.5:1.5", help="пауза пользователя между шагами, секунд: от:до")
    sys.exit(asyncio.run(main(p.parse_args())))
