# ruff: noqa: E501
"""The drawn plan (2D editor): what is drawn, what is wrong with it, and the repair as a proposal."""
from __future__ import annotations

from pydantic import BaseModel, Field

from .. import proposals
from . import Ctx, ToolError, tool
from .reading import BuildingArg, _building


def _drawing(ctx: Ctx, given: str | None) -> str:
    d = ctx.ui.get("drawing")
    did = given or (d.get("id") if isinstance(d, dict) else None)
    if not did:
        raise ToolError("Не задан чертёж: укажите drawing_id (список — drawings) или откройте план в редакторе")
    return did


@tool("drawings", "Чертежи здания: загруженные файлы и нарисованные планы (kind: file | sketch), их состояние сборки.")
async def drawings(ctx: Ctx, args: BuildingArg) -> dict:
    b = _building(ctx, args.building_id)
    got = await ctx.get("import", "/drawings", building_id=b)
    return {"drawings": [{k: d.get(k) for k in ("id", "name", "kind", "status", "current_build_id", "updated_at")}
                         for d in got.get("items", [])]}


class DrawingArg(BaseModel):
    drawing_id: str | None = Field(None, description="id нарисованного плана; по умолчанию — открытый в редакторе")


@tool("plan_summary", "Нарисованный план в числах: этажи, стены, проёмы, колонны, лестницы, помещения с названиями и площадями, сколько без названия.")
async def plan_summary(ctx: Ctx, args: DrawingArg) -> dict:
    did = _drawing(ctx, args.drawing_id)
    got = await ctx.get("import", f"/drawings/{did}/sketch/check")
    return {"drawing_id": did, "version": got.get("version"), **got.get("summary", {}),
            "errors": got.get("errors"), "warnings": got.get("warnings")}


class CheckArg(DrawingArg):
    limit: int = Field(100, ge=1, le=500, description="сколько проблем перечислить")


@tool("check_plan", """Проблемы нарисованного плана (считает код): ошибки — стены короче 5 мм, двойные стены, пересечения не в узле,
проёмы за стеной и налезающие друг на друга; предупреждения — проём выше стены, свободный конец стены рядом с другой,
помещения без названия, названия вне помещений, повторяющиеся номера, двери уже 80 см, несущие стены не на несущих ниже.
`fixable` — что чинится автоматически (propose_plan_fixes).""")
async def check_plan(ctx: Ctx, args: CheckArg) -> dict:
    did = _drawing(ctx, args.drawing_id)
    got = await ctx.get("import", f"/drawings/{did}/sketch/check")
    issues = got.get("issues", [])
    by: dict[str, int] = {}
    for i in issues:
        by[i["code"]] = by.get(i["code"], 0) + 1
    return {"drawing_id": did, "version": got.get("version"), "errors": got.get("errors"), "warnings": got.get("warnings"),
            "by_code": by, "fixable": got.get("fixable"), "issues": issues[: args.limit], "total": len(issues)}


class FixArg(DrawingArg):
    codes: list[str] | None = Field(None, description="какие проблемы чинить (коды из check_plan); пусто — все исправимые")
    floor_id: str | None = Field(None, description="только этот этаж плана")
    summary: str | None = Field(None, max_length=2000)


@tool("propose_plan_fixes", """Предложить починку нарисованного плана: убрать короткие и двойные стены, примкнуть свободные концы,
вдвинуть и развести проёмы, понизить проёмы выше стены, убрать названия вне помещений. Пользователь применит в редакторе
(с отменой) или кнопкой. Пересечения стен, названия и номера помещений автоматически не чинятся — предлагай словами.""", kind="propose")
async def propose_plan_fixes(ctx: Ctx, args: FixArg) -> dict:
    did = _drawing(ctx, args.drawing_id)
    got = await ctx.call("POST", "import", f"/drawings/{did}/sketch/repair", json={"codes": args.codes, "floor_id": args.floor_id})
    fixed = got.get("fixed", [])
    if not fixed:
        raise ToolError("Чинить нечего: исправимых проблем в плане нет (остальное — см. check_plan)")
    if not ctx.chat_id:
        raise ToolError("Предложение можно сделать только в беседе")
    lines = [f"{x['what']}" for x in fixed[:50]]
    summary = args.summary or f"Исправить план: {len(fixed)} правок"
    action = proposals.sketch_action(f"План: {len(fixed)} правок — " + "; ".join(lines[:5]) + ("…" if len(lines) > 5 else ""),
                                     did, int(got["version"]), got["sketch"])
    try:
        async with ctx.db.begin() as session:
            p = await proposals.create(session, chat_id=ctx.chat_id, me=ctx.me, building_id=ctx.building_id, summary=summary, actions=[action])
    except ValueError as ex:
        raise ToolError(str(ex)) from ex
    p["fixes"] = lines
    return {"proposal": p, "fixed": fixed, "left": got.get("left", [])[:50], "left_counts": {"errors": got.get("errors"), "warnings": got.get("warnings")},
            "next": "Предложение показано пользователю; применит он сам (в редакторе — с отменой). Не говори, что план уже исправлен."}
