"""Rights by area: who may do what in which building, floor, room, object.

The access service keeps the grants (person — role — scope); a service asks
for the caller's scopes once and decides locally — `decide()` is the one rule,
used by the access service itself too:

    rights = Rights(client)                       # client: ServiceClient that knows "access"
    await rights.require(request, me, "manage", [("building", building_id)])

Roles: viewer < responsible < admin. Actions:

  plan            see the plan and the model of a building — any grant inside that building
  view            see what is in the area (objects, people) — any role on the area or above it
  edit            change permitted properties and the state — responsible or admin
  move_portable   move portable objects — responsible or admin
  manage          everything else — admin

`chain` is the area and everything above it, e.g. [("room", r), ("floor", f), ("building", b)]:
the access service does not know what is inside what. A guest by a link may look at its
area only: `plan` of its floor (of the floor of its room; any floor for a whole building)
and `view` of what is inside the area; nothing else. The system administrator
(Keycloak client role dwg3d.admin) may everything; another service calling with its own
token may read everything and change nothing — changes come with a user's token.

Scopes are remembered for 20 s, so a right given or taken away works within
30 s everywhere. While the access service is away, reading goes
on by what was last known for up to 5 minutes; changes are refused.
"""
from __future__ import annotations

import time
from collections.abc import Iterable

from fastapi import Request

from .auth import Identity
from .client import ServiceClient
from .errors import Problem

RANK = {"viewer": 1, "responsible": 2, "admin": 3}
NEEDS = {"view": 1, "plan": 1, "edit": 2, "move_portable": 2, "manage": 3}
READING = ("view", "plan")
FRESH_S, STALE_S = 20, 300
Chain = Iterable[tuple[str, object]]


def decide(scopes: dict, action: str, chain: Chain) -> bool:
    """Whether someone with these scopes may do the action.
    `scopes`: {admin, grants: [{role, scope: {kind, id}, building_id}]}."""
    if action not in NEEDS:
        raise ValueError(f"unknown action: {action}")
    if scopes.get("guest"):
        return _guest_may(scopes["guest"], action, chain)
    if scopes.get("admin") or (scopes.get("service") and action in READING):
        return True
    area = {(kind, str(id_)) for kind, id_ in chain}
    grants = scopes.get("grants") or []
    if action == "plan":
        buildings = {id_ for kind, id_ in area if kind == "building"}
        return any(g["building_id"] in buildings for g in grants)
    best = max((RANK[g["role"]] for g in grants if (g["scope"]["kind"], g["scope"]["id"]) in area), default=0)
    return best >= NEEDS[action]


def _guest_may(area: dict, action: str, chain: Chain) -> bool:
    if action not in READING:
        return False
    chain = {(kind, str(id_)) for kind, id_ in chain}
    kind, id_, building, floor = area["kind"], area["id"], area["building_id"], area.get("floor_id") or ""
    if not chain or any(k == "building" and i != building for k, i in chain):
        return False                                     # another building does not exist for a guest
    if action == "view":
        return (kind, id_) in chain
    if all(k == "building" for k, _ in chain):          # the building as a whole: its name, its list of floors
        return True
    return kind == "building" or ("floor", floor) in chain


def guest_scopes(me: Identity) -> dict:
    """The scopes of a guest, from the token itself: one area to look at."""
    kind, id_, building, floor = me.guest
    grant = {"role": "viewer", "scope": {"kind": kind, "id": id_}, "building_id": building}
    return {"admin": False, "service": False, "person_id": None, "grants": [grant], "buildings": [building],
            "guest": {"kind": kind, "id": id_, "building_id": building, "floor_id": floor}}


class Rights:
    def __init__(self, client: ServiceClient):
        self.client = client
        self._known: dict[str, tuple[float, dict]] = {}

    def forget(self) -> None:
        self._known.clear()

    async def scopes(self, request: Request, me: Identity, *, reading: bool = True) -> dict:
        if me.kind == "guest":
            return guest_scopes(me)
        if me.is_admin or me.kind == "service":
            return {"admin": me.is_admin, "service": me.kind == "service", "person_id": None, "grants": [],
                    "buildings": []}
        now = time.monotonic()
        at, scopes = self._known.get(me.sub, (0.0, None))
        if scopes is not None and now - at < FRESH_S:
            return scopes
        token = request.headers.get("authorization", "").partition(" ")[2].strip()
        try:
            r = await self.client.get("access", "/me/scopes", token=token)
            if r.status_code != 200:
                raise Problem(503, "access_unavailable", "Сервис прав ответил ошибкой")
            fresh = r.json()
            self._known[me.sub] = (now, fresh)
            return fresh
        except Problem as ex:
            if ex.status != 503:
                raise
            if reading and scopes is not None and now - at < STALE_S:
                return scopes                      # reading goes on by what was last known
            message = ("Сервис прав недоступен — попробуйте позже" if reading
                       else "Сервис прав недоступен — изменения временно невозможны")
            raise Problem(503, "access_unavailable", message) from ex

    async def allowed(self, request: Request, me: Identity, action: str, chain: Chain) -> bool:
        return decide(await self.scopes(request, me, reading=action in READING), action, list(chain))

    async def require(self, request: Request, me: Identity, action: str, chain: Chain, *,
                      what: str = "Не найдено") -> None:
        """Raise unless allowed: 404 when the area is not even visible to the caller, 403 when it is."""
        chain = list(chain)
        scopes = await self.scopes(request, me, reading=action in READING)
        if decide(scopes, action, chain):
            return
        if action in READING or not decide(scopes, "plan", chain) and not decide(scopes, "view", chain):
            raise Problem(404, "not_found", what)
        raise Problem(403, "forbidden", "Недостаточно прав для этого действия")

    async def buildings(self, request: Request, me: Identity) -> list[str] | None:
        """The buildings the caller may see the plan of; None — all of them."""
        scopes = await self.scopes(request, me)
        return None if scopes.get("admin") or scopes.get("service") else list(scopes.get("buildings") or [])
