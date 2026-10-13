"""The model and how to reach it: one row of settings, set by the system administrator.
The API key is kept encrypted (TWIN_COPILOT_SECRET, else the service secret) and never given back."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import date
from urllib.parse import urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from twin_chassis import Problem

from .models import settings as settings_t
from .models import usage as usage_t

DEFAULTS: dict = {"enabled": False, "base_url": "", "api_key": "", "model": "", "daily_limit": 200,
                  "temperature": None, "max_steps": 12, "context_tokens": 32000}
MAX_KEY = 4000


class ModelError(Exception):
    """The model or its endpoint did not do what was asked; the message is for the user."""


def _fernet(secret: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def secret_of(app_settings) -> str:
    return os.environ.get("TWIN_COPILOT_SECRET") or app_settings.service_secret or "twin-copilot"


async def load(session: AsyncSession, secret: str) -> dict:
    """The settings with the key decrypted (a key that cannot be read any more counts as absent)."""
    row = (await session.execute(select(settings_t.c.value).where(settings_t.c.id == 1))).scalar_one_or_none()
    cfg = {**DEFAULTS, **(row or {})}
    if cfg.get("api_key"):
        try:
            cfg["api_key"] = _fernet(secret).decrypt(cfg["api_key"].encode()).decode()
        except (InvalidToken, ValueError):
            cfg["api_key"] = ""
    return cfg


def ready(cfg: dict) -> bool:
    return bool(cfg["enabled"] and cfg["base_url"] and cfg["model"])


def public(cfg: dict) -> dict:
    """As the administrator sees it: the key replaced by whether it is set and its tail."""
    out = {k: v for k, v in cfg.items() if k != "api_key"}
    key = cfg.get("api_key") or ""
    out["api_key_set"] = bool(key)
    out["api_key_hint"] = ("…" + key[-4:]) if len(key) >= 8 else ("задан" if key else "")
    return out


def clean(cfg: dict, change: dict) -> dict:
    """The stored settings with a change applied; raises Problem 422 on bad values."""
    out = dict(cfg)
    errors = []
    if "base_url" in change:
        url = str(change["base_url"] or "").strip().rstrip("/")
        if url.endswith("/chat/completions"):
            url = url[: -len("/chat/completions")]
        parts = urlsplit(url) if url else None
        if url and (parts.scheme not in ("http", "https") or not parts.netloc):
            errors.append({"field": "base_url", "message": "адрес вида http(s)://host[:port]/v1"})
        out["base_url"] = url
    if "api_key" in change and change["api_key"] is not None:
        key = str(change["api_key"])
        if len(key) > MAX_KEY:
            errors.append({"field": "api_key", "message": f"не длиннее {MAX_KEY} знаков"})
        out["api_key"] = key.strip()
    if "model" in change:
        model = str(change["model"] or "").strip()
        if len(model) > 200:
            errors.append({"field": "model", "message": "не длиннее 200 знаков"})
        out["model"] = model
    for field, lo, hi in (("daily_limit", 0, 100000), ("max_steps", 1, 50), ("context_tokens", 4000, 2000000)):
        if field in change:
            try:
                v = int(change[field])
                if not lo <= v <= hi:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append({"field": field, "message": f"целое от {lo} до {hi}"})
                continue
            out[field] = v
    if "temperature" in change:
        t = change["temperature"]
        if t is not None:
            try:
                t = float(t)
                if not 0 <= t <= 2:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append({"field": "temperature", "message": "число от 0 до 2 или пусто"})
        out["temperature"] = t
    if "enabled" in change:
        out["enabled"] = bool(change["enabled"])
    if out["enabled"] and not (out["base_url"] and out["model"]):
        errors.append({"field": "enabled", "message": "чтобы включить, задайте адрес и модель"})
    if errors:
        raise Problem(422, "invalid", "Настройки не приняты", errors=errors)
    return out


async def save(session: AsyncSession, secret: str, cfg: dict, by: str) -> None:
    stored = dict(cfg)
    if stored.get("api_key"):
        stored["api_key"] = _fernet(secret).encrypt(stored["api_key"].encode()).decode()
    exists = (await session.execute(select(settings_t.c.id).where(settings_t.c.id == 1))).scalar_one_or_none()
    if exists:
        await session.execute(update(settings_t).where(settings_t.c.id == 1)
                              .values(value=stored, updated_at=func.now(), updated_by=by))
    else:
        await session.execute(insert(settings_t).values(id=1, value=stored, updated_by=by))


def headers(cfg: dict) -> dict:
    return {"Authorization": f"Bearer {cfg['api_key']}"} if cfg.get("api_key") else {}


async def check(http: httpx.AsyncClient, cfg: dict, prompt_tokens: int) -> dict:
    """Try the endpoint: its models (GET /models), then a one-word answer from the model."""
    if not cfg["base_url"] or not cfg["model"]:
        raise ModelError("задайте адрес и модель")
    out: dict = {"prompt_tokens": prompt_tokens}
    try:
        r = await http.get(f"{cfg['base_url']}/models", headers=headers(cfg), timeout=20)
        if r.status_code == 200:
            out["models"] = [m.get("id") for m in (r.json().get("data") or []) if isinstance(m, dict)][:200]
    except (httpx.HTTPError, ValueError):
        pass
    try:
        r = await http.post(f"{cfg['base_url']}/chat/completions", headers=headers(cfg), timeout=120, json={
            "model": cfg["model"], "max_tokens": 16,
            "messages": [{"role": "user", "content": "Ответь одним словом: готов?"}]})
    except httpx.HTTPError as ex:
        raise ModelError(f"не удалось соединиться: {ex.__class__.__name__}: {ex}") from ex
    if r.status_code != 200:
        raise ModelError(f"модель ответила {r.status_code}: {r.text[:500]}")
    try:
        out["answer"] = (r.json()["choices"][0]["message"].get("content") or "").strip()[:200]
    except (ValueError, KeyError, IndexError, TypeError) as ex:
        raise ModelError(f"ответ не в формате OpenAI: {r.text[:300]}") from ex
    return out


# ------------------------------------------------------------------- usage ---
async def requests_today(session: AsyncSession, sub: str) -> int:
    row = (await session.execute(select(usage_t.c.requests).where(
        usage_t.c.user_sub == sub, usage_t.c.day == date.today()))).scalar_one_or_none()
    return row or 0


async def count(session: AsyncSession, sub: str, used: dict | None) -> None:
    """One request to the model, with the tokens it reports."""
    used = used or {}
    vals = {"requests": 1, "prompt_tokens": int(used.get("prompt_tokens") or 0),
            "completion_tokens": int(used.get("completion_tokens") or 0)}
    stmt = pg_insert(usage_t).values(user_sub=sub, day=date.today(), **vals)
    await session.execute(stmt.on_conflict_do_update(index_elements=["user_sub", "day"], set_={
        k: getattr(usage_t.c, k) + getattr(stmt.excluded, k) for k in vals}))


def dumps(x) -> str:
    return json.dumps(x, ensure_ascii=False, default=str)
