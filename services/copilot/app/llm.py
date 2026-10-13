"""One request to an OpenAI-compatible endpoint (/chat/completions with tools), streamed."""
from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

import httpx

from .config import ModelError, headers


async def complete(http: httpx.AsyncClient, cfg: dict, messages: list[dict], tools: list[dict]) -> AsyncIterator[dict]:
    """Events: {"text": delta}, {"thinking": characters so far} (reasoning models — counted, not kept),
    then {"message": assistant message, "usage": usage}. A server answering without a stream is read whole."""
    body: dict = {"model": cfg["model"], "messages": messages, "stream": True,
                  "stream_options": {"include_usage": True}}
    if tools:
        body["tools"] = tools
    if cfg.get("temperature") is not None:
        body["temperature"] = cfg["temperature"]
    content, calls, usage, thought, told = [], {}, None, 0, 0
    async with http.stream("POST", f"{cfg['base_url']}/chat/completions", json=body, headers=headers(cfg)) as r:
        if r.status_code != 200:
            raise ModelError(f"модель ответила {r.status_code}: {(await r.aread()).decode(errors='replace')[:500]}")
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
