"""Assembled answers for the interface: what several services know, in one request (docs/CONTRACTS.md, 11).
Reading only. A part whose service is away is left out and the service is named in `partial`."""
from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from .services import ask
from .sessions import Signed, not_guest

router = APIRouter()


class CabinetRoom(BaseModel):
    id: str
    name: str
    number: str | None
    floor_id: str
    floor_name: str
    level: int | None


class Cabinet(BaseModel):
    person_id: str | None = Field(description="Человек, который вошёл; null — учётной записи нет в справочнике")
    whole: bool = Field(description="Видно всё здание (администратор или право на здание целиком)")
    rooms: list[CabinetRoom] = Field(description="Мои помещения: на которые есть право (пусто, если видно всё здание)")
    attention: list[dict] = Field(description="Объекты, требующие внимания: неисправные, без места, "
                                              "с незаполненными свойствами")
    mine: list[dict] = Field(description="Объекты, за которые я отвечаю")
    partial: list[str] = Field(description="Сервисы, не ответившие: их части в ответе нет")


@router.get("/api/views/cabinet", tags=["views"], response_model=Cabinet, summary="Личный кабинет в здании")
async def cabinet(request: Request, building_id: UUID, who: Signed = Depends(not_guest)):
    b = str(building_id)
    partial: list[str] = []
    scopes = await ask(request, who, "access", "/me/scopes")
    if not scopes.ok:
        partial.append("access")
    s = scopes.body if scopes.ok else {}
    person_id = s.get("person_id")
    grants = [g for g in s.get("grants") or [] if g.get("building_id") == b]
    whole = who.identity.is_admin or bool(s.get("admin")) or any(g["scope"]["kind"] == "building" for g in grants)
    rooms: list[dict] = []
    if not whole and grants:
        tree = await ask(request, who, "buildings", f"/buildings/{b}/tree")
        if not tree.ok:
            partial.append("buildings")
        else:
            floors = {g["scope"]["id"] for g in grants if g["scope"]["kind"] == "floor"}
            wanted = {g["scope"]["id"] for g in grants if g["scope"]["kind"] == "room"}
            for f in tree.body.get("floors") or []:
                for r in f.get("rooms") or []:
                    if f["id"] in floors or r["id"] in wanted:
                        rooms.append({"id": r["id"], "name": r["name"], "number": r.get("number"), "floor_id": f["id"],
                                      "floor_name": f["name"], "level": f.get("level")})
    looks = [{"building_id": b, "state": "faulty"}, {"building_id": b, "needs_placement": "true"},
             {"building_id": b, "needs_fill": "true"}]
    if person_id:
        looks.append({"building_id": b, "responsible_id": person_id})
    answers = await asyncio.gather(*(ask(request, who, "assets", "/assets", params={**p, "limit": 200}) for p in looks))
    if not all(a.ok for a in answers):
        partial.append("assets")
    attention: dict[str, dict] = {}
    for a in answers[:3]:
        for item in (a.body or {}).get("items") or [] if a.ok else []:
            attention.setdefault(item["id"], item)
    mine = (answers[3].body or {}).get("items") or [] if person_id and answers[3].ok else []
    return {"person_id": person_id, "whole": whole, "rooms": rooms,
            "attention": sorted(attention.values(), key=lambda x: x.get("updated_at") or "", reverse=True)[:100],
            "mine": mine, "partial": partial}
