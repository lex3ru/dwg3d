#!/usr/bin/env python3
"""A stand-in for the model: an OpenAI-compatible /v1/chat/completions that needs no GPU.

    tools/fake-model.py --port 18089

It calls the copilot's tools by keywords of the question and answers from their results, so the whole path —
panel → gateway → copilot → services → model — can be tried and tested (e2e) without a real model. From a
container the host is http://host.docker.internal:18089/v1.
"""
from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def plan(messages: list[dict], tools: list[dict]) -> dict:
    """What to answer: {"text": ...} or {"calls": [(name, args)]}."""
    names = {t["function"]["name"] for t in tools}
    last = messages[-1]
    user = next((m for m in reversed(messages) if m["role"] == "user"), None)
    text = (user or {}).get("content") or ""
    asked = text.split("\n\n", 1)[-1]
    question = asked.lower()
    rename = re.search(r"переимен\w*\s+(?:помещение\s+)?(.+?)\s+в\s+«([^»]+)»", asked, re.I)
    if last["role"] == "tool":
        try:
            data = json.loads(last.get("content") or "{}")
        except ValueError:
            data = {}
        if isinstance(data, dict) and isinstance(data.get("proposal"), dict):
            p = data["proposal"]
            fixes = "; ".join(p.get("fixes") or [])
            return {"text": f"Предложил: {p.get('summary') or p.get('name')}." + (f" Правки: {fixes}." if fixes else "") + " Примените, если согласны."}
        if isinstance(data, dict) and "by_code" in data and "issues" in data:
            if data.get("fixable") and "propose_plan_fixes" in names and any(w in question for w in ("исправ", "почин")):
                return {"calls": [("propose_plan_fixes", {"drawing_id": data["drawing_id"]})]}
            parts = [f"{i['message']} ({', '.join(i['ids']) or 'этаж ' + str(i['floor_id'])})" for i in data["issues"][:10]]
            return {"text": f"Ошибок: {data['errors']}, предупреждений: {data['warnings']}. " + "; ".join(parts) + "."}
        if isinstance(data, dict) and "rooms_total" in data:
            b = data["building"]
            return {"text": f"**{b.get('name')}**{', ' + b['address'] if b.get('address') else ''}: этажей {len(data['floors'])}, помещений {data['rooms_total']} "
                            f"общей площадью {data['area_total']} м². Объектов учёта: {data['assets_total']}" + (f", без ответственного: {data['without_responsible']}" if data.get("without_responsible") else "") + "."}
        if isinstance(data, dict) and "became_faulty" in data:
            return {"text": f"За {data['days']} дн.: событий {data['events']}, стали неисправными {data['became_faulty']}, перемещений {data['moved']}, новых объектов {data['created']}."}
        if isinstance(data, dict) and "blocked" in data and "counts" in data:
            parts = [f"{b['name']}: {', '.join(b['problems'])}" for b in data["blocked"][:10]]
            empty = [e["name"] for e in data.get("empty", [])[:10]]
            return {"text": f"Мешают: {len(data['blocked'])}; пустых помещений: {len(data.get('empty', []))}. " + "; ".join(parts) + (" Пустые: " + ", ".join(empty) + "." if empty else "")}
        if isinstance(data, dict) and data.get("counts") and data.get("legend"):
            legend = data["legend"]
            parts = [f"{legend[k]}: {v}" for k, v in data["counts"].items() if v]
            return {"text": f"Проверил {data['scanned']} объектов. " + ("; ".join(parts) + "." if parts else "Замечаний нет.")}
        if isinstance(data, dict) and data.get("rooms"):
            rooms = data["rooms"]
            if len(rooms) == 1 and rename and "propose_rooms" in names:
                return {"calls": [("propose_rooms", {"summary": f"Переименовать помещение {rooms[0].get('number') or rooms[0].get('name') or ''} в «{rename.group(2)}»",
                                                     "changes": [{"room_id": rooms[0]["id"], "name": rename.group(2)}]})]}
            if len(rooms) == 1 and "room" in names and not any(m["role"] == "tool" and '"assets"' in (m.get("content") or "") for m in messages):
                return {"calls": [("room", {"room_id": rooms[0]["id"]})]}
            return {"text": "Нашёл помещения: " + ", ".join(
                f"[{' '.join(x for x in (r.get('number'), r.get('name')) if x)}](room:{r['id']})" for r in rooms[:10]) + "."}
        if isinstance(data, dict) and isinstance(data.get("assets"), list):
            room = data.get("room") or {}
            where = f" в [{room.get('number') or ''} {room.get('name') or ''}](room:{room['id']})".rstrip() if room.get("id") else ""
            if not data["assets"]:
                return {"text": f"Объектов{where} не нашёл."}
            lines = [f"- [{a.get('type_name')} {a.get('inventory_no')}](asset:{a['id']}) — {a.get('state')}"
                     + (f", отв. {a['responsible']}" if a.get("responsible") else "") for a in data["assets"][:20]]
            return {"text": f"Объекты{where} ({data.get('assets_total') or data.get('total') or len(data['assets'])}):\n" + "\n".join(lines)}
        if isinstance(data, dict) and data.get("buildings"):
            return {"text": "Здания: " + ", ".join(b["name"] for b in data["buildings"]) + "."}
        if "Не найдено" in (last.get("content") or "") or "нет права" in (last.get("content") or ""):
            return {"text": "Этого вам не видно: " + (last.get("content") or "")[:200]}
        return {"text": "Готово: " + (last.get("content") or "")[:300]}
    ui = text.split("\n\n", 1)[0]
    room_id = (re.search(r"помещение «[^»]*» \(id ([0-9a-f-]{36})\)", ui) or [None, None])[1]
    number = re.search(r"\b(\d{2,4})\b", question)
    if ("здани" in question and "какие" in question) and "buildings" in names:
        return {"calls": [("buildings", {})]}
    if room_id and "room" in names and any(w in question for w in ("здесь", "этом помещении", "тут", "в нём")):
        return {"calls": [("room", {"room_id": room_id})]}
    if rename and "find_rooms" in names:
        return {"calls": [("find_rooms", {"q": rename.group(1)[:40]})]}
    if number and "find_rooms" in names:
        return {"calls": [("find_rooms", {"q": number.group(1)})]}
    if any(w in question for w in ("паспорт", "опиши здание", "расскажи о здании")) and "building_passport" in names:
        return {"calls": [("building_passport", {})]}
    if any(w in question for w in ("что произошло", "дайджест", "сводка журнала", "за неделю")) and "journal_digest" in names:
        return {"calls": [("journal_digest", {"days": 7})]}
    if "нарисуй" in question and "draw_plan" in names:
        n = re.search(r"(\d+)\s*(кабинет|помещен|комнат)", question)
        count = int(n.group(1)) if n else 4
        return {"calls": [("draw_plan", {"template": "corridor", "params": {"rooms_top": (count + 1) // 2, "rooms_bottom": count // 2},
                                         "name": f"Коридор с {count} кабинетами"})]}
    if "извещател" in question and "place_detectors" in names:
        floor_id = (re.search(r"этаж «[^»]*» \(id ([0-9a-f-]{36})\)", ui) or [None, None])[1]
        return {"calls": [("place_detectors", {"floor_id": floor_id} if floor_id else {})]}
    if "расстанов" in question and "провер" in question and "check_placement" in names:
        return {"calls": [("check_placement", {})]}
    if "план" in question and any(w in question for w in ("провер", "ошибк", "исправ", "почин")) and "check_plan" in names:
        return {"calls": [("check_plan", {})]}
    if any(w in question for w in ("аудит", "проверь учёт", "проверь учет")) and "audit_assets" in names:
        return {"calls": [("audit_assets", {})]}
    if any(w in question for w in ("объект", "оборудован", "мебел", "принтер", "монитор")) and "find_assets" in names:
        args = {"limit": 20}
        if "неисправ" in question:
            args["state"] = "faulty"
        return {"calls": [("find_assets", args)]}
    if "помещен" in question and "find_rooms" in names:
        return {"calls": [("find_rooms", {"limit": 20})]}
    return {"text": "Я подставная модель для проверки: спросите о помещении по номеру, об объектах или о зданиях."}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            return self._json({"data": [{"id": "fake-model"}]})
        self.send_error(404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        step = plan(body.get("messages") or [], body.get("tools") or [])
        if not body.get("stream"):
            return self._json({"choices": [{"index": 0, "message": {"role": "assistant", "content": step.get("text", "")}}],
                               "usage": {"prompt_tokens": 100, "completion_tokens": 10}})
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        chunks = []
        for i, (name, args) in enumerate(step.get("calls", [])):
            chunks.append({"choices": [{"index": 0, "delta": {"tool_calls": [{"index": i, "id": f"call_{i}", "type": "function",
                                                                             "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}]}}]})
        for word in re.findall(r"\S+\s*", step.get("text", "")):
            chunks.append({"choices": [{"index": 0, "delta": {"content": word}}]})
        chunks.append({"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 10}})
        for c in chunks:
            self.wfile.write(f"data: {json.dumps(c, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")

    def _json(self, data):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18089)
    port = ap.parse_args().port
    print(f"fake model on http://0.0.0.0:{port}/v1", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
