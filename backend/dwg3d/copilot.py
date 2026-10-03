"""The built-in copilot: a chat in the viewer with a language model that works
with the project through its tools (agent_tools.py).

The model is external, behind an OpenAI-compatible endpoint (POST
{base_url}/chat/completions with function calling: Ollama, vLLM, LM Studio,
OpenRouter, cloud providers); its address, key, model and limits are set by
an admin in the UI and kept in app_settings (the key is never sent back to
browsers, only its last characters).

The copilot acts for the signed-in user (agent_tools.acting_as), as an agent
named «Копилот»: no more than the user's role in the project, capped like a
token's mode — "propose" for editors and owners (changes go as proposals the
user applies in one click), "read" for viewers. Its changes and proposals are
in the audit log as "<login> · Копилот".

A conversation is kept per user and project (copilot_chats) in the endpoint's
message format; each request sends a fixed system prompt, the history (the
last MAX_HISTORY messages) and, with the user's message, what their window
shows. A user has a daily limit of model requests (copilot_usage).
"""
from __future__ import annotations

import dataclasses
import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime, timezone
from urllib.parse import urlparse

import httpx
from fastapi.concurrency import run_in_threadpool
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from . import access, agent_tools, auth, db, uicontext
from .models import AppSetting, CopilotChat, CopilotUsage

log = logging.getLogger("dwg3d.copilot")
SETTINGS_KEY = "copilot"
DEFAULTS = {"enabled": False, "base_url": "", "api_key": "", "model": "", "daily_limit": 200,
            "temperature": None, "max_steps": 12}
NAME = "Копилот"
MAX_HISTORY = 80                    # messages sent back to the model
MAX_RESULT = 20000                  # characters of a tool result

SYSTEM = """\
Ты — Копилот, встроенный помощник программы «Поэтажные планы → 3D». Программа строит
3D-модели зданий из DWG-чертежей; в проекте — чертежи (корпуса) с этажами и помещениями
и слои проектных данных: мебель и оборудование, видеонаблюдение, пожарная сигнализация,
СКУД, Wi-Fi, СКС, маршруты людей, зоны. Ты работаешь с проектом пользователя через
инструменты, с его правами.

Как работать:
- Отвечай по-русски, коротко и по делу. Не выдумывай: данные проекта узнавай
  инструментами (project_overview, list_rooms, query_objects, report и др.).
- В каждом сообщении пользователя есть блок «Сейчас у пользователя открыто» — «это»,
  «здесь», «на этом этаже», «выделенный» относятся к нему.
- Координаты — метры в плане этажа; этаж — id внутри чертежа (c0, c1…), помещение —
  числовой id. Не считай координаты сам: для расстановки есть place_in_room и
  place_row, для обзора камер — camera_coverage.
- Изменения ты только предлагаешь: propose_changes, или place_in_room / place_row с
  then="propose" и понятным summary. Пользователь увидит предложение на плане и
  применит его сам — не говори, что изменения уже внесены.
- Слои и варианты тоже меняются предложениями (create_layer, copy_layer, update_layer,
  delete_layer в propose_changes). «Сделай вариант и …» — copy_layer и правки копий в
  одном предложении; сравнить варианты — compare_variants.
- Чтобы показать пользователю место или объекты, вызывай show_in_viewer.
- Если инструмент вернул ошибку — прочитай её и исправь вызов, а не повторяй тот же.
"""


class CopilotError(Exception):
    """The copilot cannot answer (not set up, limit reached, the endpoint failed)."""


# --------------------------------------------------------------- settings ---
def load_settings(s: Session) -> dict:
    row = s.get(AppSetting, SETTINGS_KEY)
    return {**DEFAULTS, **(row.value if row else {})}


def settings_json(cfg: dict) -> dict:
    """For the admin's form: everything but the key (only whether it is set and its tail)."""
    key = cfg.get("api_key") or ""
    return {**{k: v for k, v in cfg.items() if k != "api_key"},
            "api_key_set": bool(key), "api_key_hint": f"…{key[-4:]}" if len(key) >= 8 else ("задан" if key else "")}


def save_settings(s: Session, v: dict) -> dict:
    """Change the settings given (api_key: a new key; "" removes it; absent or null keeps it)."""
    if not isinstance(v, dict):
        raise ValueError("ожидается объект")
    cfg = load_settings(s)
    if "enabled" in v:
        if not isinstance(v["enabled"], bool):
            raise ValueError("enabled: true или false")
        cfg["enabled"] = v["enabled"]
    if "base_url" in v:
        url = (v["base_url"] or "").strip().rstrip("/")
        if url:
            u = urlparse(url)
            if u.scheme not in ("http", "https") or not u.netloc:
                raise ValueError("base_url: адрес вида https://host/v1 (до /chat/completions)")
            url = url.removesuffix("/chat/completions")
        cfg["base_url"] = url
    if v.get("api_key") is not None:
        if not isinstance(v["api_key"], str) or len(v["api_key"]) > 4000:
            raise ValueError("api_key: строка")
        cfg["api_key"] = v["api_key"].strip()
    if "model" in v:
        if not isinstance(v["model"], str) or len(v["model"]) > 200:
            raise ValueError("model: имя модели у провайдера")
        cfg["model"] = v["model"].strip()
    if "daily_limit" in v:
        n = v["daily_limit"]
        if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= 100000:
            raise ValueError("daily_limit: запросов к модели на пользователя в день, 0–100000")
        cfg["daily_limit"] = n
    if "max_steps" in v:
        n = v["max_steps"]
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 50:
            raise ValueError("max_steps: шагов с инструментами на один вопрос, 1–50")
        cfg["max_steps"] = n
    if "temperature" in v:
        t = v["temperature"]
        if t is not None and (isinstance(t, bool) or not isinstance(t, (int, float)) or not 0 <= t <= 2):
            raise ValueError("temperature: от 0 до 2 или пусто (по умолчанию модели)")
        cfg["temperature"] = t
    if cfg["enabled"] and not (cfg["base_url"] and cfg["model"]):
        raise ValueError("чтобы включить копилот, задайте адрес и модель")
    me = auth.current.get()
    stmt = insert(AppSetting).values(key=SETTINGS_KEY, value=cfg, updated_by=me.id if me else None)
    s.execute(stmt.on_conflict_do_update(index_elements=[AppSetting.key],
                                         set_={"value": cfg, "updated_by": me.id if me else None,
                                               "updated_at": datetime.now(timezone.utc)}))
    return cfg


def ready(cfg: dict) -> bool:
    return bool(cfg["enabled"] and cfg["base_url"] and cfg["model"])


def _client(timeout: float = 300) -> httpx.AsyncClient:
    """The HTTP client for the endpoint (replaced in tests)."""
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15))


def _headers(cfg: dict) -> dict:
    return {"Authorization": f"Bearer {cfg['api_key']}"} if cfg.get("api_key") else {}


async def check(cfg: dict) -> dict:
    """Try the endpoint: its models (GET /models), then a one-word answer from the model."""
    if not cfg["base_url"] or not cfg["model"]:
        raise CopilotError("задайте адрес и модель")
    out: dict = {"prompt_tokens": await prompt_size()}
    async with _client(60) as c:
        try:
            r = await c.get(f"{cfg['base_url']}/models", headers=_headers(cfg))
            if r.status_code == 200:
                out["models"] = [m.get("id") for m in (r.json().get("data") or []) if isinstance(m, dict)][:200]
        except (httpx.HTTPError, ValueError):
            pass
        try:
            r = await c.post(f"{cfg['base_url']}/chat/completions", headers=_headers(cfg), json={
                "model": cfg["model"], "max_tokens": 16,
                "messages": [{"role": "user", "content": "Ответь одним словом: готов?"}]})
        except httpx.HTTPError as ex:
            raise CopilotError(f"не удалось соединиться: {ex.__class__.__name__}: {ex}") from ex
    if r.status_code != 200:
        raise CopilotError(f"модель ответила {r.status_code}: {r.text[:500]}")
    try:
        out["answer"] = (r.json()["choices"][0]["message"].get("content") or "").strip()[:200]
    except (ValueError, KeyError, IndexError, TypeError) as ex:
        raise CopilotError(f"ответ не в формате OpenAI: {r.text[:300]}") from ex
    return out


# ---------------------------------------------------------------- identity ---
def identity(me: auth.Me, role: str | None, pid: str) -> auth.Me:
    """The user, as the agent «Копилот» in this project: proposes if they may edit, else reads."""
    mode = "propose" if access.rank(role) >= access.rank("editor") else "read"
    return dataclasses.replace(me, agent={"id": f"copilot-{me.id if me.id is not None else '-'}", "name": NAME,
                                          "project_id": pid, "mode": mode, "copilot": True})


_specs: list[dict] | None = None


async def tool_specs(mode: str) -> list[dict]:
    """The tools as OpenAI functions (no proposing for users who may only read)."""
    global _specs
    if _specs is None:
        _specs = [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                                                    "parameters": t.input_schema}}
                  for t in await agent_tools.mcp.list_tools()]
    hidden = {"propose_changes", "place_in_room", "place_row"} if mode == "read" else set()
    return [x for x in _specs if x["function"]["name"] not in hidden]


async def prompt_size() -> int:
    """About how many tokens the instructions and tool descriptions take in every request."""
    text = SYSTEM + json.dumps(await tool_specs("propose"), ensure_ascii=False)
    return round(len(text) / 2.8 / 100) * 100          # Cyrillic and JSON: ~2.8 characters a token


async def call_tool(me: auth.Me, name: str, args: dict) -> tuple[str, bool, dict | None]:
    """Run a tool as the copilot: (result text, is error, structured result)."""
    token = agent_tools.acting_as.set(me)
    try:
        res = await agent_tools.mcp.call_tool(name, args)
    except ToolError as ex:
        return str(ex), True, None
    except Exception as ex:                       # a tool crashed: the model is told, the log has the rest
        log.exception("copilot tool %s failed", name)
        return f"Ошибка инструмента {name}: {ex.__class__.__name__}", True, None
    finally:
        agent_tools.acting_as.reset(token)
    data = getattr(res, "structured_content", None)
    if data is not None:
        text = json.dumps(data, ensure_ascii=False, default=str)
    else:
        text = "\n".join(getattr(b, "text", "") for b in getattr(res, "content", []) or [])
    if len(text) > MAX_RESULT:
        text = text[:MAX_RESULT] + "… (обрезано: уточните запрос фильтрами)"
    return text, bool(getattr(res, "is_error", False)), data


# ------------------------------------------------------------------- usage ---
def _user_key(me: auth.Me) -> str:
    return str(me.id) if me.id is not None else "-"


def requests_today(s: Session, me: auth.Me) -> int:
    row = s.get(CopilotUsage, (_user_key(me), date.today()))
    return row.requests if row else 0


def count(me: auth.Me, usage: dict | None):
    """One request to the model, with the tokens it reports."""
    usage = usage or {}
    vals = {"requests": 1, "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0)}
    with db.session() as s:
        stmt = insert(CopilotUsage).values(user_key=_user_key(me), day=date.today(), **vals)
        s.execute(stmt.on_conflict_do_update(index_elements=[CopilotUsage.user_key, CopilotUsage.day], set_={
            k: getattr(CopilotUsage, k) + getattr(stmt.excluded, k) for k in vals}))


# ------------------------------------------------------------------- chats ---
def chats(s: Session, pid: str, me: auth.Me, limit: int = 30) -> list[dict]:
    q = (select(CopilotChat).where(CopilotChat.project_id == pid).order_by(CopilotChat.updated_at.desc()).limit(limit))
    q = q.where(CopilotChat.user_id.is_(None) if me.id is None else CopilotChat.user_id == me.id)
    return [{"id": c.id, "title": c.title, "updated": c.updated_at.timestamp()} for c in s.scalars(q)]


def own_chat(s: Session, cid: str, me: auth.Me) -> CopilotChat:
    c = s.get(CopilotChat, cid)
    if c is None or c.user_id != me.id:
        raise LookupError(cid)
    return c


def display(messages: list[dict]) -> list[dict]:
    """A conversation for the chat panel: the user's words, answers, tools used, proposals made."""
    out = []
    for m in messages:
        if m.get("role") == "user":
            out.append({"type": "user", "text": m.get("_text") or m.get("content") or ""})
        elif m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                out.append({"type": "tool", "name": tc["function"]["name"]})
            if m.get("content"):
                out.append({"type": "assistant", "text": m["content"]})
        elif m.get("role") == "tool" and m.get("_proposal"):
            out.append({"type": "proposal", "proposal": m["_proposal"]})
    return out


def _wire(messages: list[dict]) -> list[dict]:
    """Messages as the endpoint takes them: without our own keys (_text, _proposal)."""
    return [{k: v for k, v in m.items() if not k.startswith("_")} for m in messages]


def _trimmed(messages: list[dict]) -> list[dict]:
    """The last MAX_HISTORY messages, starting at a user message (tool calls keep their results)."""
    if len(messages) <= MAX_HISTORY:
        return messages
    tail = messages[-MAX_HISTORY:]
    first = next((i for i, m in enumerate(tail) if m.get("role") == "user"), len(tail))
    return tail[first:]


def _proposal_of(name: str, data: dict | None) -> dict | None:
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("proposal"), dict):
        return data["proposal"]
    if name == "propose_changes" and data.get("status") == "open" and data.get("id"):
        return {k: data.get(k) for k in ("id", "summary", "status", "counts", "drawing_id", "agent")}
    return None


# -------------------------------------------------------------------- turn ---
async def _complete(c: httpx.AsyncClient, cfg: dict, messages: list[dict], tools: list[dict]) -> AsyncIterator[dict]:
    """One request to the endpoint, streamed: {"text": delta} and {"thinking": characters so far}
    events (reasoning models: delta.reasoning / reasoning_content, not kept), then {"message", "usage"}.
    A server that answers without streaming is read whole."""
    body = {"model": cfg["model"], "messages": messages, "tools": tools, "stream": True}
    if cfg.get("temperature") is not None:
        body["temperature"] = cfg["temperature"]
    content, calls, usage, thought, told = [], {}, None, 0, 0
    async with c.stream("POST", f"{cfg['base_url']}/chat/completions", json=body, headers=_headers(cfg)) as r:
        if r.status_code != 200:
            raise CopilotError(f"модель ответила {r.status_code}: {(await r.aread()).decode(errors='replace')[:500]}")
        if "text/event-stream" not in r.headers.get("content-type", ""):
            data = json.loads(await r.aread())
            msg = data["choices"][0]["message"]
            if msg.get("content"):
                yield {"text": msg["content"]}
            yield {"message": {"role": "assistant", "content": msg.get("content"),
                               **({"tool_calls": msg["tool_calls"]} if msg.get("tool_calls") else {})},
                   "usage": data.get("usage")}
            return
        async for line in r.aiter_lines():
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if chunk == "[DONE]":
                break
            try:
                data = json.loads(chunk)
            except ValueError:
                continue
            if data.get("usage"):
                usage = data["usage"]
            for ch in data.get("choices") or []:
                delta = ch.get("delta") or {}
                if reasoning := delta.get("reasoning") or delta.get("reasoning_content"):
                    thought += len(reasoning)
                    if thought - told >= 200:
                        told = thought
                        yield {"thinking": thought}
                if delta.get("content"):
                    content.append(delta["content"])
                    yield {"text": delta["content"]}
                for tc in delta.get("tool_calls") or []:
                    cur = calls.setdefault(tc.get("index", len(calls)), {"id": "", "name": "", "arguments": ""})
                    cur["id"] = tc.get("id") or cur["id"]
                    fn = tc.get("function") or {}
                    cur["name"] += fn.get("name") or ""
                    cur["arguments"] += fn.get("arguments") or ""
    msg: dict = {"role": "assistant", "content": "".join(content) or None}
    if calls:
        msg["tool_calls"] = [{"id": v["id"] or f"call_{uuid.uuid4().hex[:12]}", "type": "function",
                              "function": {"name": v["name"], "arguments": v["arguments"] or "{}"}}
                             for _, v in sorted(calls.items())]
    yield {"message": msg, "usage": usage}


async def run(pid: str, me: auth.Me, role: str | None, chat_id: str | None, text: str, ui: dict | None) -> AsyncIterator[dict]:
    """Answer a message: events for the chat panel —
    {"type": "chat", "id"}, {"type": "text", "text"} (deltas), {"type": "thinking", "chars"} (a reasoning
    model at work), {"type": "tool", "name", "error"?},
    {"type": "proposal", "proposal"}, {"type": "error", "message"}, {"type": "done"}.
    The conversation is saved when the answer is complete."""
    text = (text or "").strip()
    if not text or len(text) > 8000:
        raise CopilotError("сообщение: от 1 до 8000 символов")

    def prepare():
        with db.session() as s:
            cfg = load_settings(s)
            if not ready(cfg):
                raise CopilotError("Копилот не настроен: администратор задаёт модель в настройках")
            if cfg["daily_limit"] and requests_today(s, me) >= cfg["daily_limit"]:
                raise CopilotError(f"Дневной лимит копилота исчерпан ({cfg['daily_limit']} запросов к модели)")
            chat = own_chat(s, chat_id, me) if chat_id else None
            if chat is not None and chat.project_id != pid:
                raise LookupError(chat_id)
            return cfg, (chat.id if chat else None), list(chat.messages if chat else [])

    cfg, cid, history = await run_in_threadpool(prepare)
    agent = identity(me, role, pid)
    tools = await tool_specs(agent.agent["mode"])
    note = await run_in_threadpool(_ui_note, pid, ui)
    history.append({"role": "user", "content": f"{note}\n\n{text}", "_text": text})
    cid = cid or uuid.uuid4().hex[:12]
    yield {"type": "chat", "id": cid}
    system = {"role": "system", "content": SYSTEM + (
        "" if agent.agent["mode"] == "propose" else
        "\nУ пользователя права только на просмотр: предлагать изменения ты не можешь, только отвечать и показывать.")}
    async with _client() as c:
        for _ in range(cfg["max_steps"]):
            msg = usage = None
            try:
                async for ev in _complete(c, cfg, [system, *_wire(_trimmed(history))], tools):
                    if "text" in ev:
                        yield {"type": "text", "text": ev["text"]}
                    elif "thinking" in ev:
                        yield {"type": "thinking", "chars": ev["thinking"]}
                    else:
                        msg, usage = ev["message"], ev["usage"]
            except httpx.HTTPError as ex:
                raise CopilotError(f"нет связи с моделью: {ex.__class__.__name__}") from ex
            except (ValueError, KeyError, IndexError, TypeError) as ex:
                raise CopilotError("ответ модели не в формате OpenAI") from ex
            await run_in_threadpool(count, me, usage)
            history.append(msg)
            if not msg.get("tool_calls"):
                break
            for tc in msg["tool_calls"]:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                    if not isinstance(args, dict):
                        raise ValueError
                except ValueError:
                    result, error, data = "Аргументы — не JSON-объект: повторите вызов с корректным JSON", True, None
                else:
                    result, error, data = await call_tool(agent, name, args)
                yield {"type": "tool", "name": name, **({"error": result[:300]} if error else {})}
                entry = {"role": "tool", "tool_call_id": tc["id"], "content": result}
                if not error and (prop := _proposal_of(name, data)) is not None:
                    entry["_proposal"] = prop
                    yield {"type": "proposal", "proposal": prop}
                history.append(entry)
        else:
            note_ = "Остановился: слишком много шагов на один вопрос. Уточните, что сделать дальше."
            history.append({"role": "assistant", "content": note_})
            yield {"type": "text", "text": f"\n\n{note_}"}

    def save():
        with db.session() as s:
            chat = s.get(CopilotChat, cid)
            if chat is None:
                chat = CopilotChat(id=cid, project_id=pid, user_id=me.id, title=text[:80])
                s.add(chat)
            chat.messages = history
            chat.updated_at = datetime.now(timezone.utc)

    await run_in_threadpool(save)
    yield {"type": "done"}


def _ui_note(pid: str, ui: dict | None) -> str:
    """«Сейчас у пользователя открыто: …» for the model."""
    if not isinstance(ui, dict):
        return "[Сейчас у пользователя открыто: неизвестно]"
    with db.session() as s:
        d = uicontext.describe(s, pid, uicontext.clean(ui))
    parts = []
    if d.get("drawing"):
        parts.append(f"чертёж «{d['drawing']['name']}» (id {d['drawing']['id']})")
    if d.get("floor"):
        parts.append(f"этаж {d['floor']['id']} «{d['floor']['name']}»")
    if d.get("view"):
        parts.append("план (2D)" if d["view"] == "2d" else "модель (3D)")
    if d.get("room"):
        parts.append(f"выбрано помещение {d['room']['id']} «{d['room']['name']}», {d['room']['area']} м²")
    if d.get("selected"):
        parts.append("выделены: " + ", ".join(f"{x['id']} ({x['name'] or x['item']})" for x in d["selected"]))
    if d.get("proposal"):
        parts.append(f"просматривает предложение {d['proposal']}")
    return f"[Сейчас у пользователя открыто: {'; '.join(parts) or 'список проекта'}]"
