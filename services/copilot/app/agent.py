"""Answering a message: the loop model → tools → model, as events for the panel.

Events: {"type": "text", "text"} (deltas), {"type": "interim"} (the text so far was said before tool calls),
{"type": "thinking", "chars"}, {"type": "tool", "name", "error"?},
{"type": "ui", "href", "label"}, {"type": "proposal", "proposal"}, {"type": "error", "message"}, {"type": "done"}.
The conversation is kept in `messages` as it goes; a turn that fails midway leaves what was said and the error."""
from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import httpx
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from twin_chassis import Identity

from . import config, llm, prompt, tools
from .models import chats, messages

log = logging.getLogger("copilot")
MAX_HISTORY = 80
MAX_TEXT = 8000


class ChatError(Exception):
    pass


def model_http() -> httpx.AsyncClient:
    """The client for the model's endpoint (a slow local model may take minutes per answer)."""
    return httpx.AsyncClient(timeout=httpx.Timeout(600, connect=15))


async def load_history(session: AsyncSession, chat_id: UUID) -> list[dict]:
    rows = (await session.execute(select(messages).where(messages.c.chat_id == chat_id).order_by(messages.c.n))).all()
    return [dict(r._mapping) for r in rows]


def wire(history: list[dict]) -> list[dict]:
    """Messages as the endpoint takes them: the last MAX_HISTORY, starting at a user message."""
    out = []
    for m in history:
        if m["role"] == "assistant" and not m.get("content") and not m.get("tool_calls"):
            continue                              # a recorded failure, not something the model said
        w: dict = {"role": m["role"]}
        if m["role"] == "tool":
            w["tool_call_id"] = m.get("tool_call_id")
            w["content"] = m.get("content") or ""
        else:
            w["content"] = m.get("content") if m["role"] != "user" else (m.get("content") or "")
            if m.get("tool_calls"):
                w["tool_calls"] = m["tool_calls"]
        out.append(w)
    if len(out) > MAX_HISTORY:
        out = out[-MAX_HISTORY:]
        first = next((i for i, m in enumerate(out) if m["role"] == "user"), len(out))
        out = out[first:]
    return out


def shown(history: list[dict]) -> list[dict]:
    """A conversation for the panel: the user's words, answers, tools used, proposals, ui commands, errors."""
    out = []
    for m in history:
        s = m.get("shown") or {}
        if m["role"] == "user":
            out.append({"type": "user", "text": s.get("text") or m.get("content") or "", "at": m.get("at")})
        elif m["role"] == "assistant":
            for tc in m.get("tool_calls") or []:
                out.append({"type": "tool", "name": tc["function"]["name"]})
            if m.get("content"):
                out.append({"type": "assistant", "text": m["content"], "at": m.get("at"),
                            **({"interim": True} if m.get("tool_calls") else {})})
            if s.get("error"):
                out.append({"type": "error", "message": s["error"]})
        elif m["role"] == "tool":
            for ev in s.get("events") or []:
                out.append(ev)
    return out


class Turn:
    """One message answered; writes the messages of the chat as it goes."""

    def __init__(self, app, me: Identity, token: str, chat_id: UUID, mode: str, cfg: dict):
        self.app, self.me, self.token, self.chat_id, self.mode, self.cfg = app, me, token, chat_id, mode, cfg
        self.n = 0

    async def _append(self, m: dict) -> None:
        async with self.app.state.db.begin() as session:
            await session.execute(insert(messages).values(chat_id=self.chat_id, n=self.n, **{
                k: m.get(k) for k in ("role", "content", "tool_calls", "tool_call_id", "name", "shown")}))
            await session.execute(update(chats).where(chats.c.id == self.chat_id).values(updated_at=func.now()))
        m.setdefault("at", datetime.now(UTC))
        self.n += 1

    async def run(self, text: str, ui: dict | None) -> AsyncIterator[dict]:
        text = (text or "").strip()
        if not text or len(text) > MAX_TEXT:
            raise ChatError(f"сообщение: от 1 до {MAX_TEXT} символов")
        async with self.app.state.db.begin() as session:
            history = await load_history(session, self.chat_id)
        self.n = len(history)
        note = prompt.ui_note(ui)
        user = {"role": "user", "content": f"{note}\n\n{text}", "shown": {"text": text}}
        await self._append(user)
        history.append(user)
        ctx = tools.Ctx(self.app.state.client, self.me, self.token, self.mode, ui or {}, str(self.chat_id),
                        public_url=self.app.state.settings.public_url or "", db=self.app.state.db)
        system = {"role": "system", "content": prompt.system(self.mode)}
        specs = tools.specs(self.mode)
        http = self.app.state.model_http
        for _ in range(self.cfg["max_steps"]):
            msg = used = None
            try:
                async for ev in llm.complete(http, self.cfg, [system, *wire(history)], specs):
                    if "text" in ev:
                        yield {"type": "text", "text": ev["text"]}
                    elif "thinking" in ev:
                        yield {"type": "thinking", "chars": ev["thinking"]}
                    else:
                        msg, used = ev["message"], ev["usage"]
            except httpx.HTTPError as ex:
                raise ChatError(f"нет связи с моделью: {ex.__class__.__name__}") from ex
            except (ValueError, KeyError, IndexError, TypeError) as ex:
                raise ChatError("ответ модели не в формате OpenAI") from ex
            async with self.app.state.db.begin() as session:
                await config.count(session, self.me.sub, used)
            assert msg is not None
            await self._append(msg)
            history.append(msg)
            if not msg.get("tool_calls"):
                break
            if msg.get("content"):
                yield {"type": "interim"}             # said before the tools: thinking aloud, not the answer
            for tc in msg["tool_calls"]:
                name = tc["function"]["name"]
                ctx.events = []
                result, error, data = await tools.run(ctx, name, tc["function"].get("arguments") or "")
                yield {"type": "tool", "name": name, **({"error": result[:300]} if error else {})}
                entry = {"role": "tool", "tool_call_id": tc["id"], "name": name, "content": result, "shown": {}}
                events = list(ctx.events)
                if not error and isinstance(data, dict) and isinstance(data.get("proposal"), dict):
                    events.append({"type": "proposal", "proposal": data["proposal"]})
                for ev in events:
                    yield ev
                if events:
                    entry["shown"] = {"events": events}
                await self._append(entry)
                history.append(entry)
        else:
            stop = "Остановился: слишком много шагов на один вопрос. Уточните, что сделать дальше."
            await self._append({"role": "assistant", "content": stop})
            yield {"type": "text", "text": f"\n\n{stop}"}
        yield {"type": "done"}

    async def failed(self, message: str) -> None:
        """Keep the failure in the chat, so the panel shows it after a reload too."""
        try:
            await self._append({"role": "assistant", "content": None, "shown": {"error": message}})
        except Exception:
            log.exception("copilot: could not record the error")


def new_chat_id() -> UUID:
    return uuid.uuid4()
