"""Settings of the model: only the system administrator, validation, the key hidden, the check, the status."""
from __future__ import annotations

import json

from conftest import API, configure


async def test_only_admin_touches_settings(client, tokens):
    me = tokens.bearer("user-1")
    assert (await client.get(f"{API}/settings", headers=me)).status_code == 403
    assert (await client.put(f"{API}/settings", headers=me, json={"enabled": True})).status_code == 403
    assert (await client.post(f"{API}/settings/check", headers=me, json={})).status_code == 403
    assert (await client.get(f"{API}/settings", headers=tokens.admin())).json()["enabled"] is False


async def test_validation(client, tokens):
    admin = tokens.admin()
    r = await client.put(f"{API}/settings", headers=admin, json={"enabled": True})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "enabled"
    r = await client.put(f"{API}/settings", headers=admin, json={"base_url": "ftp://x"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "base_url"
    r = await client.put(f"{API}/settings", headers=admin, json={"max_steps": 0})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "max_steps"
    r = await client.put(f"{API}/settings", headers=admin, json={"temperature": 3})
    assert r.status_code == 422


async def test_key_is_kept_secret_and_kept(client, tokens):
    admin = tokens.admin()
    cfg = await configure(client, tokens, api_key="sk-secret-12345678", daily_limit=50)
    assert cfg["base_url"] == "http://llm.test/v1" and cfg["api_key_set"] and cfg["api_key_hint"] == "…5678"
    assert "sk-secret" not in json.dumps(cfg) and "api_key" not in cfg
    # a trailing /chat/completions is forgiven
    cfg = (await client.put(f"{API}/settings", headers=admin, json={"base_url": "http://llm.test/v1/chat/completions/"})).json()
    assert cfg["base_url"] == "http://llm.test/v1"
    # the key stays when not sent, goes when sent empty
    assert (await client.put(f"{API}/settings", headers=admin, json={"daily_limit": 40})).json()["api_key_set"]
    assert not (await client.put(f"{API}/settings", headers=admin, json={"api_key": ""})).json()["api_key_set"]


async def test_check_talks_to_the_model(client, tokens, model):
    model.script = [{"text": "Готов"}]
    await configure(client, tokens, api_key="sk-secret-12345678")
    chk = (await client.post(f"{API}/settings/check", headers=tokens.admin(), json={})).json()
    assert chk["ok"] and chk["answer"] == "Готов" and chk["models"] == ["fake-model", "other"]
    assert chk["prompt_tokens"] >= 1000
    assert model.requests[-1]["headers"]["authorization"] == "Bearer sk-secret-12345678"
    assert model.requests[-1]["body"].get("stream") is not True
    # the check may try unsaved values
    model.script = [{"text": "Ок"}]
    chk = (await client.post(f"{API}/settings/check", headers=tokens.admin(), json={"model": "other"})).json()
    assert chk["ok"] and model.requests[-1]["body"]["model"] == "other"
    assert (await client.get(f"{API}/settings", headers=tokens.admin())).json()["model"] == "fake-model"
    # a failing endpoint is reported, not raised
    import httpx
    model.script = [httpx.Response(500, text="boom")]
    chk = (await client.post(f"{API}/settings/check", headers=tokens.admin(), json={})).json()
    assert chk["ok"] is False and "500" in chk["error"]


async def test_status(app, client, tokens, world):
    me = tokens.bearer("user-1")
    assert (await client.get(f"{API}/status", headers=me)).json() == {
        "enabled": False, "model": "", "daily_limit": 0, "used_today": 0, "can_propose": False}
    await configure(client, tokens, daily_limit=10)
    s = (await client.get(f"{API}/status", headers=me)).json()
    assert s["enabled"] and s["model"] == "fake-model" and s["daily_limit"] == 10 and s["can_propose"] is False
    world.admins.add("user-1")
    app.state.rights.forget()                      # the rights are cached for 20 s
    assert (await client.get(f"{API}/status", headers=me)).json()["can_propose"] is True
    assert (await client.get(f"{API}/status", headers=tokens.admin())).json()["can_propose"] is True
    # a guest by a link has no copilot
    from conftest import BUILDING, FLOOR
    assert (await client.get(f"{API}/status", headers=tokens.guest("floor", FLOOR, BUILDING, FLOOR))).status_code == 403
