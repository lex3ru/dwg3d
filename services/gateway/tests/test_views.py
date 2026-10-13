"""Assembled answers, reports and the QR link: what several services know, through the gateway."""
from __future__ import annotations

from io import BytesIO
from urllib.parse import urlsplit

import httpx
import pytest_asyncio
from twin_chassis.testing import running, test_settings

from app.config import GatewayConfig
from app.main import SERVICE, build

from .conftest import PUBLIC, UPSTREAM, sign_in

B, F, R1, R2, P = (f"0192f000-0000-7000-8000-00000000000{n}" for n in range(1, 6))
D = "0192f000-0000-7000-8000-000000000009"
SERVICES = {name: UPSTREAM for name in ("ping", "access", "buildings", "assets", "catalog", "people", "import")}


def asset(n: int, room: str, **extra) -> dict:
    return {"id": f"a-{n}", "type_id": "t-1", "type_name": "Кушетка", "building_id": B, "floor_id": F, "room_id": room,
            "x": 1.0 + n, "y": 2.0, "angle": 0, "inventory_no": f"К-{n:04d}", "serial_no": None, "state": "in_use",
            "responsible_id": None, "props": {"wear": "good"}, "note": "", "needs_placement": False,
            "needs_fill": False,
            "qr_code": f"CODE{n}", "updated_at": f"2026-10-06T00:00:0{n}Z", **extra}


def world_of(world) -> None:
    """A building of one floor and two rooms; three objects; the user answers for one and sees room 1."""
    tree = {"floors": [{"id": F, "name": "1 этаж", "level": 1, "drawing_id": D, "candidate": "c0",
                        "rooms": [{"id": R1, "name": "Кабинет", "number": "101"},
                                  {"id": R2, "name": "Склад", "number": None}]}]}
    items = [asset(1, R1, state="faulty"), asset(2, R1, responsible_id=P, needs_fill=True), asset(3, R2)]

    def assets(request: httpx.Request):
        q = dict(request.url.params)
        out = items
        if q.get("state"):
            out = [a for a in out if a["state"] == q["state"]]
        if q.get("needs_fill"):
            out = [a for a in out if a["needs_fill"]]
        if q.get("needs_placement"):
            out = [a for a in out if a["needs_placement"]]
        if q.get("responsible_id"):
            out = [a for a in out if a["responsible_id"] == q["responsible_id"]]
        if q.get("room_id"):
            out = [a for a in out if a["room_id"] == q["room_id"]]
        return 200, {"items": out, "total": len(out), "next": None}

    world.answers.update({
        ("GET", "/api/access/v1/me/scopes"): {"admin": False, "person_id": P, "buildings": [B],
                                            "grants": [{"role": "responsible", "scope": {"kind": "room", "id": R1},
                                                        "building_id": B}]},
        ("GET", f"/api/buildings/v1/buildings/{B}/tree"): tree,
        ("GET", f"/api/buildings/v1/buildings/{B}"): {"id": B, "name": "Корпус", "address": ""},
        ("GET", f"/api/buildings/v1/rooms/{R1}"): {"id": R1, "name": "Кабинет", "number": "101", "floor_id": F,
                                                   "building_id": B},
        ("GET", "/api/assets/v1/assets"): assets,
        ("POST", "/api/catalog/v1/types/batch-get"): {"items": [{
            "id": "t-1", "name": "Кушетка", "size": [1.8, 0.6, 0.5], "values": {},
            "schema": [{"key": "wear", "title": "Износ", "kind": "choice", "stored": "asset",
                        "options": [{"value": "good", "title": "хороший"}]}]}]},
        ("POST", "/api/people/v1/people/batch-get"): {"items": [{"id": P, "full_name": "Иван Иванов", "position": ""}]},
        ("POST", f"/api/import/v1/drawings/{D}/export"): lambda r: (200, b"0\nSECTION\n" + r.content[:0]),
    })


@pytest_asyncio.fixture
async def app(database_url, tokens, world):
    config = GatewayConfig(public_url=PUBLIC, client_secret="s3cret", secret="test-secret", services=SERVICES)
    http = httpx.AsyncClient(transport=httpx.MockTransport(world.handle))
    async with running(build(test_settings(SERVICE, database_url), tokens.verifier(), config, http)) as app:
        yield app


@pytest_asyncio.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=PUBLIC) as client:
        yield client


@pytest_asyncio.fixture
async def signed_in(client, world):
    world_of(world)
    await sign_in(client)
    return client


async def test_qr_link_leads_to_sign_in_and_then_to_the_card(client, world):
    r = await client.get("/q/A7K2M9Q4ZX")
    assert r.status_code == 302 and r.headers["location"] == "/auth/login?next=/q/A7K2M9Q4ZX"
    back = await sign_in(client, next="/q/A7K2M9Q4ZX")
    assert back.headers["location"] == "/q/A7K2M9Q4ZX"
    r = await client.get("/q/A7K2M9Q4ZX")
    assert r.status_code == 302 and r.headers["location"] == "/#/q/A7K2M9Q4ZX"
    assert (await client.get("/q/../etc")).status_code == 404
    assert world.seen == []            # the code is not looked up here: the card asks, with the user's right


async def test_cabinet_gathers_rooms_attention_and_mine(signed_in, world):
    r = await signed_in.get("/api/views/cabinet", params={"building_id": B})
    assert r.status_code == 200
    c = r.json()
    assert c["person_id"] == P and c["whole"] is False and c["partial"] == []
    assert [x["name"] for x in c["rooms"]] == ["Кабинет"] and c["rooms"][0]["floor_name"] == "1 этаж"
    assert sorted(a["id"] for a in c["attention"]) == ["a-1", "a-2"]
    assert [a["id"] for a in c["mine"]] == ["a-2"]
    # without the people and access services the cabinet is still a cabinet, and says what is missing
    del world.answers[("GET", "/api/access/v1/me/scopes")]
    world.answers[("GET", "/api/access/v1/me/scopes")] = lambda r: (503, {"code": "down"})
    c = (await signed_in.get("/api/views/cabinet", params={"building_id": B})).json()
    assert c["partial"] == ["access"] and c["rooms"] == [] and c["mine"] == []
    assert len(c["attention"]) == 2


async def test_assets_excel_has_properties_as_columns(signed_in):
    from openpyxl import load_workbook

    r = await signed_in.get("/api/reports/assets.xlsx", params={"building_id": B, "state": "faulty"})
    assert r.status_code == 200 and r.headers["content-type"].endswith("spreadsheetml.sheet")
    ws = load_workbook(BytesIO(r.content)).active
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0][:6] == ("Тип", "Инвентарный номер", "Серийный номер", "Состояние", "Этаж", "Помещение")
    assert "Износ" in rows[0]
    assert len(rows) == 2 and rows[1][:6] == ("Кушетка", "К-0001", None, "неисправен", "1 этаж", "Кабинет")
    assert rows[1][rows[0].index("Износ")] == "хороший"


async def test_room_sheet_is_a_pdf(signed_in):
    r = await signed_in.get(f"/api/reports/rooms/{R1}/sheet.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF") and "attachment" in r.headers["content-disposition"]


async def test_room_sheet_takes_names_as_text(signed_in, world):
    """Names with «<», «>» and «&» are text in the sheet: neither a failure nor markup reportlab would act on."""
    # the image of the old sheet: reportlab opened the file named in it
    evil = '<img src="/etc/passwd"/> Рога & Копыта'
    world.answers[("GET", f"/api/buildings/v1/buildings/{B}")] = {"id": B, "name": evil}
    world.answers[("GET", f"/api/buildings/v1/rooms/{R1}")] = {"id": R1, "name": "Кабинет <1>", "number": "101",
                                                               "floor_id": F, "building_id": B}
    world.answers[("POST", "/api/people/v1/people/batch-get")] = {"items": [{"id": P, "full_name": "Иван <b>Иванов"}]}
    r = await signed_in.get(f"/api/reports/rooms/{R1}/sheet.pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")


async def test_drawing_with_objects_goes_through_import(signed_in, world):
    r = await signed_in.post(f"/api/reports/buildings/{B}/drawing", json={"drawing_id": D, "format": "dxf"})
    assert r.status_code == 200 and r.content.startswith(b"0\nSECTION") and r.headers["x-objects-drawn"] == "1"
    sent = [x for x in world.seen if x.url.path.endswith("/export")][-1]
    body = httpx.Request("POST", "http://x", content=sent.content)
    import json
    payload = json.loads(body.content)
    assert [o["inventory_no"] for o in payload["objects"]] == ["К-0001", "К-0002", "К-0003"]
    assert payload["objects"][1]["responsible"] == "Иван Иванов" and payload["objects"][0]["floor"] == "c0"
    assert payload["types"]["t-1"] == {"id": "t-1", "w": 1.8, "d": 0.6}
    nowhere = await signed_in.post(f"/api/reports/buildings/{B}/drawing",
                                   json={"drawing_id": "0192f000-0000-7000-8000-000000000099"})
    assert nowhere.status_code == 404


async def test_not_signed_in(client):
    assert (await client.get("/api/views/cabinet", params={"building_id": B})).status_code == 401
    assert (await client.get("/api/reports/assets.xlsx", params={"building_id": B})).status_code == 401
    assert urlsplit((await client.get("/q/ABCDEF")).headers["location"]).path == "/auth/login"
