"""Requests: the successful case, refusals by rights, invalid data."""
from __future__ import annotations

import httpx

from app import routes

API = "/api/ping/v1"


async def test_create_and_read(client, tokens):
    me = tokens.bearer("user-1")
    r = await client.post(f"{API}/notes", json={"text": "привет"}, headers=me)
    assert r.status_code == 201, r.text
    note = r.json()
    assert note["text"] == "привет" and note["created_by"] == "user-1"

    assert (await client.get(f"{API}/notes/{note['id']}", headers=me)).json()["id"] == note["id"]
    assert [n["id"] for n in (await client.get(f"{API}/notes", headers=me)).json()["items"]] == [note["id"]]


async def test_no_token_is_401(client):
    for r in (await client.get(f"{API}/notes"), await client.post(f"{API}/notes", json={"text": "x"}),
              await client.get(f"{API}/notes", headers={"Authorization": "Bearer not-a-token"})):
        assert r.status_code == 401
        assert r.headers["content-type"].startswith("application/problem+json")
        assert r.json()["code"] == "unauthenticated"


async def test_expired_token_is_401(client, tokens):
    r = await client.get(f"{API}/notes", headers=tokens.bearer("user-1", expires_in=-60))
    assert r.status_code == 401


async def test_someone_elses_note_is_invisible(client, tokens):
    note = (await client.post(f"{API}/notes", json={"text": "моё"}, headers=tokens.bearer("user-1"))).json()

    other = tokens.bearer("user-2")
    assert (await client.get(f"{API}/notes/{note['id']}", headers=other)).status_code == 404
    assert (await client.get(f"{API}/notes", headers=other)).json()["items"] == []
    # the system administrator sees everything
    assert (await client.get(f"{API}/notes/{note['id']}", headers=tokens.admin())).status_code == 200


async def test_only_admin_deletes(client, tokens):
    me = tokens.bearer("user-1")
    note = (await client.post(f"{API}/notes", json={"text": "x"}, headers=me)).json()

    r = await client.delete(f"{API}/notes/{note['id']}", headers=me)
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    assert (await client.delete(f"{API}/notes/{note['id']}", headers=tokens.admin())).status_code == 204
    assert (await client.get(f"{API}/notes/{note['id']}", headers=me)).status_code == 404


async def test_invalid_data_is_422(client, tokens):
    r = await client.post(f"{API}/notes", json={"text": ""}, headers=tokens.bearer())
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "invalid" and body["errors"][0]["field"] == "text"


async def test_request_id_comes_back(client, tokens):
    r = await client.get(f"{API}/notes", headers={**tokens.bearer(), "X-Request-ID": "req-42"})
    assert r.headers["x-request-id"] == "req-42"
    assert (await client.get("/healthz")).headers["x-request-id"]


async def test_errors_carry_no_trace(app, tokens, monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(routes, "emit", boom)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(f"{API}/notes", json={"text": "x"}, headers=tokens.bearer())
    assert r.status_code == 500 and r.json()["code"] == "internal"
    assert "secret detail" not in r.text and "Traceback" not in r.text
