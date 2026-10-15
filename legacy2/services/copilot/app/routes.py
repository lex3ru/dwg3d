"""Requests of the service, under /api/copilot/v1 (contracts/openapi/copilot.v1.json)."""
# ruff: noqa: E501
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, insert, select
from twin_chassis import Identity, Problem, forbid_guests, require_admin

from . import agent, config, prompt, tools
from .models import chats, messages

router = APIRouter(tags=["copilot"])
log = logging.getLogger("copilot")
HEARTBEAT_S = 15
STREAM_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}


def _token(request: Request) -> str:
    return request.headers.get("authorization", "").partition(" ")[2].strip()


async def _cfg(request: Request) -> dict:
    async with request.app.state.db.begin() as session:
        return await config.load(session, config.secret_of(request.app.state.settings))


async def _mode(request: Request, me: Identity, building_id: str | None) -> str:
    """propose — the user administers the building (or the system); read — anyone else."""
    if me.is_admin:
        return "propose"
    try:
        scopes = await request.app.state.rights.scopes(request, me)
    except Problem:
        return "read"
    for g in scopes.get("grants") or []:
        if g.get("role") == "admin" and g.get("scope", {}).get("kind") == "building" and (
                building_id is None or g["scope"].get("id") == building_id):
            return "propose"
    return "read"


# -------------------------------------------------------------------- status ---
class Status(BaseModel):
    enabled: bool
    model: str = ""
    daily_limit: int = 0
    used_today: int = 0
    can_propose: bool = False


@router.get("/status", response_model=Status, summary="Показывать ли помощника и что о нём знать")
async def status(request: Request, building_id: UUID | None = None, me: Identity = Depends(forbid_guests)):
    async with request.app.state.db.begin() as session:
        cfg = await config.load(session, config.secret_of(request.app.state.settings))
        used = await config.requests_today(session, me.sub)
    if not config.ready(cfg):
        return Status(enabled=False)
    return Status(enabled=True, model=cfg["model"], daily_limit=cfg["daily_limit"], used_today=used,
                  can_propose=(await _mode(request, me, str(building_id) if building_id else None)) == "propose")


# ------------------------------------------------------------------ settings ---
class SettingsIn(BaseModel):
    enabled: bool | None = None
    base_url: str | None = Field(None, description="адрес OpenAI-совместимого API, например http://llm:8000/v1")
    api_key: str | None = Field(None, description="ключ; не передан — остаётся прежний, пустая строка — удалить")
    model: str | None = None
    daily_limit: int | None = Field(None, description="запросов к модели на пользователя в день; 0 — без лимита")
    max_steps: int | None = Field(None, description="шагов (обращений к модели) на один вопрос")
    temperature: float | None = None
    context_tokens: int | None = Field(None, description="размер контекста модели, для оценки")


@router.get("/settings", summary="Настройки модели (администратор системы)")
async def get_settings(request: Request, _: Identity = Depends(require_admin)) -> dict:
    return config.public(await _cfg(request))


@router.put("/settings", summary="Изменить настройки модели (администратор системы)")
async def put_settings(body: SettingsIn, request: Request, me: Identity = Depends(require_admin)) -> dict:
    change = body.model_dump(exclude_unset=True)
    secret = config.secret_of(request.app.state.settings)
    async with request.app.state.db.begin() as session:
        cfg = config.clean(await config.load(session, secret), change)
        await config.save(session, secret, cfg, me.sub)
    return config.public(cfg)


@router.post("/settings/check", summary="Проверить связь с моделью (с переданными или сохранёнными значениями)")
async def check_settings(body: SettingsIn, request: Request, _: Identity = Depends(require_admin)) -> dict:
    change = {k: v for k, v in body.model_dump(exclude_unset=True).items() if k in ("base_url", "model", "api_key")}
    if change.get("api_key") == "":
        change.pop("api_key")
    try:
        cfg = config.clean(await _cfg(request), change)
        return {"ok": True, **await config.check(request.app.state.model_http, cfg,
                                                 prompt.prompt_size(tools.specs("propose")))}
    except config.ModelError as ex:
        return {"ok": False, "error": str(ex)}
    except Problem as ex:
        return {"ok": False, "error": ex.detail or ex.code}


# --------------------------------------------------------------------- chats ---
class ChatIn(BaseModel):
    building_id: UUID | None = None
    title: str | None = Field(None, max_length=200)


class Chat(BaseModel):
    id: UUID
    building_id: UUID | None
    title: str
    created_at: datetime
    updated_at: datetime


class ChatFull(Chat):
    items: list[dict[str, Any]]


class ChatList(BaseModel):
    items: list[Chat]


@router.get("/chats", response_model=ChatList, summary="Беседы пользователя (последние 30)")
async def list_chats(request: Request, building_id: UUID | None = None, me: Identity = Depends(forbid_guests)):
    where = [chats.c.user_sub == me.sub]
    if building_id is not None:
        where.append(chats.c.building_id == building_id)
    async with request.app.state.db.begin() as session:
        rows = (await session.execute(select(chats).where(*where).order_by(chats.c.updated_at.desc()).limit(30))).all()
    return {"items": [r._mapping for r in rows]}


@router.post("/chats", status_code=201, response_model=Chat, summary="Новая беседа")
async def create_chat(body: ChatIn, request: Request, me: Identity = Depends(forbid_guests)):
    async with request.app.state.db.begin() as session:
        row = (await session.execute(insert(chats).values(
            id=agent.new_chat_id(), user_sub=me.sub, building_id=body.building_id,
            title=body.title or "Новая беседа").returning(chats))).one()
    return row._mapping


async def _own(request: Request, chat_id: UUID, me: Identity):
    async with request.app.state.db.begin() as session:
        row = (await session.execute(select(chats).where(chats.c.id == chat_id, chats.c.user_sub == me.sub))).one_or_none()
    if row is None:
        raise Problem(404, "not_found", "Беседа не найдена")
    return row._mapping


@router.get("/chats/{chat_id}", response_model=ChatFull, summary="Беседа с сообщениями")
async def get_chat(chat_id: UUID, request: Request, me: Identity = Depends(forbid_guests)):
    chat = await _own(request, chat_id, me)
    async with request.app.state.db.begin() as session:
        history = await agent.load_history(session, chat_id)
    return {**chat, "items": agent.shown(history)}


@router.delete("/chats/{chat_id}", status_code=204, summary="Удалить беседу")
async def delete_chat(chat_id: UUID, request: Request, me: Identity = Depends(forbid_guests)):
    await _own(request, chat_id, me)
    async with request.app.state.db.begin() as session:
        await session.execute(delete(messages).where(messages.c.chat_id == chat_id))
        await session.execute(delete(chats).where(chats.c.id == chat_id))


# ------------------------------------------------------------------ messages ---
class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=agent.MAX_TEXT)
    ui: dict[str, Any] | None = Field(None, description="что открыто у пользователя: section, building{id,name}, floor, room, asset, variant, drawing, selected[]")


def _sse(ev: dict) -> bytes:
    return f"event: {ev.get('type', 'message')}\ndata: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n".encode()


@router.post("/chats/{chat_id}/messages", summary="Сообщение в беседу; ответ — поток событий (SSE)",
             responses={200: {"content": {"text/event-stream": {}}}})
async def post_message(chat_id: UUID, body: MessageIn, request: Request, me: Identity = Depends(forbid_guests)):
    chat = await _own(request, chat_id, me)
    secret = config.secret_of(request.app.state.settings)
    async with request.app.state.db.begin() as session:
        cfg = await config.load(session, secret)
        used = await config.requests_today(session, me.sub)
    if not config.ready(cfg):
        raise Problem(409, "not_configured", "Копилот не настроен: администратор системы задаёт модель в настройках")
    if cfg["daily_limit"] and used >= cfg["daily_limit"]:
        raise Problem(429, "daily_limit", f"Дневной лимит копилота исчерпан ({cfg['daily_limit']} запросов к модели)")
    building = (body.ui or {}).get("building") if isinstance((body.ui or {}).get("building"), dict) else None
    building_id = (building or {}).get("id") or (str(chat["building_id"]) if chat["building_id"] else None)
    mode = await _mode(request, me, building_id)
    turn = agent.Turn(request.app, me, _token(request), chat_id, mode, cfg)

    async def produce(queue: asyncio.Queue) -> None:
        try:
            async for ev in turn.run(body.text, body.ui):
                await queue.put(ev)
        except agent.ChatError as ex:
            await turn.failed(str(ex))
            await queue.put({"type": "error", "message": str(ex)})
        except config.ModelError as ex:
            await turn.failed(str(ex))
            await queue.put({"type": "error", "message": str(ex)})
        except Exception:
            log.exception("copilot turn failed")
            await turn.failed("внутренняя ошибка помощника")
            await queue.put({"type": "error", "message": "внутренняя ошибка помощника"})
        finally:
            await queue.put(None)

    async def stream():
        queue: asyncio.Queue = asyncio.Queue()
        task = asyncio.create_task(produce(queue))
        yield _sse({"type": "chat", "id": str(chat_id), "mode": mode})
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(queue.get(), HEARTBEAT_S)
                except TimeoutError:
                    yield b": ping\n\n"
                    continue
                if ev is None:
                    break
                yield _sse(ev)
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(stream(), media_type="text/event-stream", headers=STREAM_HEADERS)


# ----------------------------------------------------------------- proposals ---
from . import proposals as props  # noqa: E402


class RejectIn(BaseModel):
    reason: str | None = Field(None, max_length=2000)


async def _proposal(request: Request, pid: UUID, me: Identity, *, decide: bool = False, session=None):
    """One's own proposal, or any of a building one administers; `decide` — only an administrator of the building."""
    row = await props.one(session, pid, lock=decide) if session is not None else None
    if session is None:
        async with request.app.state.db.begin() as s:
            row = await props.one(s, pid)
    if row is None:
        raise Problem(404, "not_found", "Предложение не найдено")
    building = str(row.building_id) if row.building_id else None
    manages = (await _mode(request, me, building)) == "propose"
    if row.user_sub != me.sub and not manages:
        raise Problem(404, "not_found", "Предложение не найдено")
    if decide and not manages:
        raise Problem(403, "forbidden", "Применяет и отклоняет предложения администратор здания")
    return row


@router.get("/proposals", summary="Предложения копилота: свои, а администратору здания — все по зданию")
async def list_proposals(request: Request, building_id: UUID | None = None, status: str | None = None,
                         me: Identity = Depends(forbid_guests)) -> dict:
    from sqlalchemy import or_

    from .models import proposals as table
    where = []
    if building_id is not None:
        where.append(table.c.building_id == building_id)
    if status:
        where.append(table.c.status == status)
    manages = building_id is not None and (await _mode(request, me, str(building_id))) == "propose"
    if not manages:
        where.append(or_(table.c.user_sub == me.sub, table.c.id.is_(None)))
    async with request.app.state.db.begin() as session:
        rows = (await session.execute(select(table).where(*where).order_by(table.c.created_at.desc()).limit(100))).all()
    return {"items": [props.as_json(r) for r in rows]}


@router.get("/proposals/{proposal_id}", summary="Предложение: действия и состояние (с планом, если он в нём)")
async def get_proposal(proposal_id: UUID, request: Request, me: Identity = Depends(forbid_guests)) -> dict:
    row = await _proposal(request, proposal_id, me)
    return {**props.as_json(row), "actions": [{k: v for k, v in a.items() if k != "sketch" or a.get("kind") == "sketch"} for a in row.actions or []]}


@router.post("/proposals/{proposal_id}/apply", summary="Применить предложение: действия выполняются с токеном применяющего")
async def apply_proposal(proposal_id: UUID, request: Request, by: str | None = None,
                         me: Identity = Depends(forbid_guests)) -> dict:
    """`by=editor` — the open editor of the drawn plan has applied the plan itself (and saves it with undo);
    the proposal is only marked applied. Only for a proposal that is a plan."""
    await _proposal(request, proposal_id, me, decide=True)
    async with request.app.state.db.begin() as session:
        row = await _proposal(request, proposal_id, me, decide=True, session=session)
        if by == "editor":
            return await props.applied_elsewhere(session, row, me)
        return await props.apply(session, request.app.state.client, row, me, _token(request))


@router.post("/proposals/{proposal_id}/reject", summary="Отклонить предложение с причиной")
async def reject_proposal(proposal_id: UUID, body: RejectIn, request: Request, me: Identity = Depends(forbid_guests)) -> dict:
    await _proposal(request, proposal_id, me, decide=True)
    async with request.app.state.db.begin() as session:
        row = await _proposal(request, proposal_id, me, decide=True, session=session)
        return await props.reject(session, row, me, body.reason)
