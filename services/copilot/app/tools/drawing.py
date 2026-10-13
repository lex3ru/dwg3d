# ruff: noqa: E501
"""A plan drawn from a description: the import service makes it from a template, the copilot proposes it as a new
drawn plan of the building; the user applies and opens it in the editor."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .. import proposals
from . import Ctx, ToolError, tool
from .reading import _building


class DrawPlan(BaseModel):
    template: Literal["corridor", "rooms_row", "open_space"] = Field(description="corridor — коридор с помещениями по сторонам; rooms_row — ряд помещений; open_space — зал с переговорными вдоль стороны")
    params: dict = Field(default_factory=dict, description="""corridor: corridor_width (м), room_depth, room_width, rooms_top (число или список ширин), rooms_bottom (число или список; 0 — односторонний), windows (bool), entrance (bool), door_width, room_name, room_type, number_from, height, floor_name.
rooms_row: rooms (число или список ширин), room_depth, room_width, windows, room_name, room_type, number_from, height.
open_space: length, width, meeting_rooms (число или список ширин), meeting_width, meeting_depth, windows, hall_name, height.""")
    name: str | None = Field(None, max_length=200, description="название нового чертежа (плана)")
    then: Literal["return", "propose"] = Field("propose", description="return — только показать, что получилось; propose — предложить как новый план здания")


@tool("draw_plan", """Нарисовать план по описанию (геометрию строит код по шаблону): коридор с помещениями по обе стороны,
ряд помещений, открытое пространство с переговорными. Размеры — метры; чего нет в описании — по умолчанию (кабинет 4×5,
коридор 2 м, высота 3 м). Результат — предложение нового нарисованного плана здания; пользователь применит и доработает в редакторе.""", kind="propose")
async def draw_plan(ctx: Ctx, args: DrawPlan) -> dict:
    b = _building(ctx, None)
    got = await ctx.call("POST", "import", "/sketch-templates", json={"template": args.template, "params": args.params})
    summary = got.get("summary", {})
    floors = summary.get("floors") or []
    rooms = [{"name": r.get("name"), "number": r.get("number"), "area": r.get("area")} for f in floors for r in f.get("rooms", [])]
    out = {"made": got.get("made"), "rooms": rooms[:60], "errors": got.get("errors"), "warnings": got.get("warnings"),
           "issues": [i.get("message") for i in got.get("issues", [])][:20]}
    if args.then == "return":
        return out
    if not ctx.chat_id:
        raise ToolError("Предложение можно сделать только в беседе")
    name = (args.name or f"План: {args.template} ({len(rooms)} помещений)")[:200]
    action = {"label": f"Новый нарисованный план «{name}»: {len(rooms)} помещений", "kind": "sketch_new",
              "building_id": b, "name": name, "sketch": got["sketch"]}
    try:
        async with ctx.db.begin() as session:
            p = await proposals.create(session, chat_id=ctx.chat_id, me=ctx.me, building_id=b,
                                       summary=f"Нарисовать план «{name}»: {len(rooms)} помещений, {got.get('made', {}).get('length', '?')} × {got.get('made', {}).get('depth') or got.get('made', {}).get('width', '?')} м", actions=[action])
    except ValueError as ex:
        raise ToolError(str(ex)) from ex
    return {**out, "proposal": p, "next": "Предложение показано; применив его, пользователь получит новый план в разделе «Чертежи» и откроет его в редакторе."}
