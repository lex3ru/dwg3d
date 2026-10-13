"""The copilot's tools: what the model may call. Each one is a request (or a few) to the other services
with the user's token, so the user's rights decide what comes back; the tool only shapes the answer.

    @tool("find_rooms", "Помещения здания …")
    async def find_rooms(ctx: Ctx, args: FindRooms) -> dict: ...

Tools of kind "propose" are offered only when the user administers the building (Ctx.mode == "propose").
"""
from __future__ import annotations

import inspect
import json
import logging
import typing
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError
from twin_chassis import Identity, Problem
from twin_chassis.client import ServiceClient

MAX_RESULT = 20000
log = logging.getLogger("copilot")


class ToolError(Exception):
    """Told to the model as the result of the call; it is expected to read it and try otherwise."""


@dataclass
class Ctx:
    client: ServiceClient
    me: Identity
    token: str
    mode: str                                     # read | propose
    ui: dict = field(default_factory=dict)        # what the user has open (from the panel)
    chat_id: str | None = None
    public_url: str = ""
    events: list[dict] = field(default_factory=list)   # ui commands and other things the panel gets
    db: Any = None                                    # the service's database (proposals are written there)

    @property
    def building_id(self) -> str | None:
        b = self.ui.get("building")
        return b.get("id") if isinstance(b, dict) else None

    async def call(self, method: str, service: str, path: str, *, ok=(200, 201), **kw) -> Any:
        """A request with the user's token; anything but `ok` becomes a ToolError the model can read."""
        try:
            r = await self.client.request(method, service, path, token=self.token, **kw)
        except Problem as ex:
            raise ToolError(f"Сервис «{service}» недоступен: {ex.detail or ex.code}") from ex
        if r.status_code in ok:
            return r.json() if r.content else None
        raise ToolError(_refusal(service, r))

    async def get(self, service: str, path: str, **params) -> Any:
        return await self.call("GET", service, path, params={k: v for k, v in params.items() if v is not None})


def _refusal(service: str, r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        body = {}
    detail = body.get("detail") or body.get("title") or ""
    if r.status_code == 404:
        return f"Не найдено или недоступно пользователю ({service}): {detail or 'нет такого'}"
    if r.status_code == 403:
        return f"У пользователя нет права на это ({service}): {detail or 'отказано'}"
    if r.status_code == 401:
        return "Сеанс пользователя истёк: попросите повторить вопрос"
    if r.status_code == 409:
        return f"Конфликт ({service}): {detail or 'данные изменились'}"
    errors = "; ".join(f"{e.get('field')}: {e.get('message')}" for e in body.get("errors") or [])
    return f"Ошибка {r.status_code} ({service}): {detail} {errors}".strip()


@dataclass
class Tool:
    name: str
    description: str
    kind: str                                     # read | propose
    args: type[BaseModel]
    run: Callable[[Ctx, BaseModel], Awaitable[Any]]

    def spec(self) -> dict:
        schema = self.args.model_json_schema()
        _strip_titles(schema)
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": schema}}


def _strip_titles(node) -> None:
    if isinstance(node, dict):
        node.pop("title", None)
        for v in node.values():
            _strip_titles(v)
    elif isinstance(node, list):
        for v in node:
            _strip_titles(v)


REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, *, kind: str = "read"):
    def wrap(fn):
        params = list(inspect.signature(fn).parameters.values())
        args = typing.get_type_hints(fn)[params[1].name]
        assert isinstance(args, type) and issubclass(args, BaseModel), name
        REGISTRY[name] = Tool(name, description.strip(), kind, args, fn)
        return fn
    return wrap


def specs(mode: str) -> list[dict]:
    return [t.spec() for t in REGISTRY.values() if mode == "propose" or t.kind == "read"]


async def run(ctx: Ctx, name: str, raw: str) -> tuple[str, bool, Any]:
    """Run a tool by the model's call: (text for the model, is error, the data)."""
    t = REGISTRY.get(name)
    if t is None or (t.kind != "read" and ctx.mode != "propose"):
        return f"Нет инструмента {name}", True, None
    try:
        args = json.loads(raw or "{}")
        if not isinstance(args, dict):
            raise ValueError
    except ValueError:
        return "Аргументы — не JSON-объект: повторите вызов с корректным JSON", True, None
    try:
        parsed = t.args.model_validate(args)
    except ValidationError as ex:
        errors = "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in ex.errors())
        return f"Неверные аргументы: {errors}", True, None
    try:
        data = await t.run(ctx, parsed)
    except ToolError as ex:
        return str(ex), True, None
    except Exception as ex:                       # a tool crashed: the model is told, the log has the cause
        log.exception("copilot tool %s failed", name)
        return (f"Ошибка инструмента {name}: {ex.__class__.__name__} — попробуйте иначе или сообщите пользователю",
                True, None)
    text = json.dumps(data, ensure_ascii=False, default=str)
    if len(text) > MAX_RESULT:
        text = text[:MAX_RESULT] + "… (обрезано: уточните запрос фильтрами или уменьшите limit)"
    return text, False, data


from . import checks, drawing, placing, plan, proposing, reading, texts  # noqa: E402,F401  (registers the tools)
