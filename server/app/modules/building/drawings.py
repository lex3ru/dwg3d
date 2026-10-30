"""Загрузка и перевод чертежей (5.1.3, С1, 6.6): файл хранится, разбор и перевод идут
фоновыми задачами с ходом выполнения."""

import json
import math
import uuid
from datetime import timedelta
from typing import Any, BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import tasks
from app.core.actor import Actor
from app.core.errors import AppError, Forbidden, NotFound
from app.modules.access import api as access
from app.modules.building import api
from app.modules.building.models import Drawing, Floor, Room
from app.modules.building.plan import Plan
from app.modules.files import api as files
from app.modules.journal import api as journal

MIN_FLOOR = 5000.0  # мм: часть меньше — подпись, штамп, таблица; по умолчанию не этаж
MAX_SCALE = 10_000.0  # 1:10 000 — мельче планов здания не чертят


def _plain(value: Any) -> Any:
    """В JSON базы — только простые типы (числа numpy от геометрии — в обычные)."""
    return json.loads(json.dumps(value, default=lambda o: o.item() if hasattr(o, "item")
                                 else str(o)))


def view(d: Drawing, full: bool = False) -> dict[str, Any]:
    parts = d.parts or []
    out: dict[str, Any] = {
        "id": d.id,
        "building_id": d.building_id,
        "name": d.name,
        "status": d.status,
        "error": d.error,
        "job_id": d.job_id,
        "created_at": d.created_at,
        "parts": len(parts),
        "results": d.results or {},
        "scale": d.scale,
        "sheet": d.sheet or {},
        "file_url": f"/api/files/{d.file_id}",
    }
    if full:
        out["parts"] = parts
    return out


def upload(
    session: Session, actor: Actor, building_id: uuid.UUID, stream: BinaryIO, name: str,
    limit: int = files.MAX_SIZE,
) -> Drawing:
    if not actor.is_admin:
        raise Forbidden()
    building = api.get_building(session, actor, building_id)
    record = files.store(session, actor, stream, name, {"dwg", "dxf"}, limit)
    drawing = Drawing(
        id=uuid.uuid4(),
        building_id=building.id,
        file_id=record.id,
        name=name[:300],
        status="analyzing",
        parts=[],
        results={},
        sheet={},
        created_by=actor.user_id,
    )
    session.add(drawing)
    session.flush()
    drawing.job_id = tasks.enqueue(
        session, "building.analyze_drawing", {"drawing_id": str(drawing.id)}, actor
    )
    journal.record(
        session,
        actor,
        "drawing.upload",
        f"Загружен чертёж «{drawing.name}» здания «{building.name}»",
        entity=f"drawing:{drawing.id}",
        refs=[f"building:{building.id}"],
    )
    return drawing


def is_drawing_file(session: Session, actor: Actor, file_id: uuid.UUID) -> bool:
    """Исходный чертёж видит тот, кому видно здание; гостю по ссылке — только план (5.7.2)."""
    if actor.is_guest:
        return False
    q = select(Drawing.building_id).where(Drawing.file_id == file_id)
    return any(actor.can_see_building(b) for b in session.scalars(q))


def drawings(session: Session, actor: Actor, building_id: uuid.UUID) -> list[Drawing]:
    api.get_building(session, actor, building_id)
    return list(
        session.scalars(
            select(Drawing)
            .where(Drawing.building_id == building_id)
            .order_by(Drawing.created_at.desc())
        )
    )


def get(session: Session, actor: Actor, drawing_id: uuid.UUID) -> Drawing:
    drawing = session.get(Drawing, drawing_id)
    if drawing is None:
        raise NotFound("Чертёж не найден.")
    api.get_building(session, actor, drawing.building_id)
    return drawing


def set_scale(
    session: Session, actor: Actor, drawing_id: uuid.UUID, scale: float | None
) -> Drawing:
    """Масштаб листа задан администратором (None — снова по чертежу): чертёж разбирается
    заново; части теперь другие, итоги прежнего перевода к ним не относятся (ADR-0025)."""
    if not actor.is_admin:
        raise Forbidden()
    drawing = get(session, actor, drawing_id)
    if drawing.status in ("analyzing", "converting"):
        raise AppError("Чертёж ещё обрабатывается — дождитесь окончания.", code="busy")
    if scale is not None and not 0 < scale <= MAX_SCALE:
        raise AppError(f"Масштаб — от 1:1 до 1:{MAX_SCALE:.0f}.", field="scale")
    drawing.scale = scale
    drawing.status, drawing.error = "analyzing", None
    drawing.parts, drawing.results, drawing.sheet = [], {}, {}
    drawing.job_id = tasks.enqueue(
        session, "building.analyze_drawing", {"drawing_id": str(drawing.id)}, actor
    )
    journal.record(
        session,
        actor,
        "drawing.scale",
        f"Чертёж «{drawing.name}»: масштаб "
        + (f"1:{scale:g}" if scale is not None else "— по чертежу")
        + ", разбирается заново",
        entity=f"drawing:{drawing.id}",
        refs=[f"building:{drawing.building_id}"],
    )
    return drawing


def start_convert(
    session: Session, actor: Actor, drawing_id: uuid.UUID, mapping: list[dict[str, Any]]
) -> uuid.UUID:
    """mapping: [{key, floor_id} | {key, new_floor: {name, elevation?, height?}}]."""
    if not actor.is_admin:
        raise Forbidden()
    drawing = get(session, actor, drawing_id)
    if drawing.status in ("analyzing", "converting"):
        raise AppError("Чертёж ещё обрабатывается — дождитесь окончания.", code="busy")
    keys = {p["key"] for p in drawing.parts}
    chosen = [
        m for m in mapping if m.get("key") in keys and (m.get("floor_id") or m.get("new_floor"))
    ]
    if not chosen:
        raise AppError("Выберите хотя бы одну часть чертежа и этаж для неё.", code="nothing")
    floors = {str(f.id) for f in api.floors(session, drawing.building_id)}
    for m in chosen:
        if m.get("floor_id") and str(m["floor_id"]) not in floors:
            raise AppError("Этаж не из этого здания — обновите страницу.", field="floor_id")
        if m.get("new_floor") and not str(m["new_floor"].get("name", "")).strip():
            raise AppError("Укажите название нового этажа.", field="name")
    drawing.status = "converting"
    drawing.error = None
    drawing.job_id = tasks.enqueue(
        session,
        "building.convert_drawing",
        {"drawing_id": str(drawing.id), "mapping": chosen, "actor_id": str(actor.user_id)},
        actor,
    )
    # кто и когда запустил перевод — и если он не завершится (9.2 п. 3, R-011)
    journal.record(
        session,
        actor,
        "drawing.convert_start",
        f"Чертёж «{drawing.name}»: начат перевод в планы, частей {len(chosen)}",
        entity=f"drawing:{drawing.id}",
        refs=[f"building:{drawing.building_id}"],
    )
    return drawing.job_id


# ---------------------------------------------------------------- фоновые задачи


def _load(session: Session, drawing: Drawing):  # type: ignore[no-untyped-def]
    from app.modules.building.drawing import read

    record = files.get(session, drawing.file_id)
    return read.load(files.path_of(record.sha256), drawing.scale)


def _not_done(session: Session, payload: dict[str, Any], error: str) -> None:
    """Задача чертежа не выполнена (ошибка, таймаут, отмена, сбой — ADR-0011): её
    транзакция откачена, а статус «разбирается» или «переводится» записан ещё при постановке
    в очередь. Не разобранный чертёж — с ошибкой; не переведённый — снова готов к переводу,
    с причиной: иначе он навсегда «переводится», и повторить перевод нельзя."""
    drawing = session.get(Drawing, uuid.UUID(payload["drawing_id"]), with_for_update=True)
    if drawing is None:
        return
    if drawing.status == "analyzing":
        drawing.status, drawing.error = "failed", error
    elif drawing.status == "converting":
        drawing.status, drawing.error = "ready", error


# чертежи — в своей полосе очереди: тяжёлый не держит выгрузки и отчёты (R-026)
@tasks.task("building.analyze_drawing", "Разбор чертежа на этажи", lane="drawings",
            timeout=timedelta(minutes=15), on_fail=_not_done)
def analyze_drawing(
    session: Session, payload: dict[str, Any], progress: tasks.Progress
) -> dict[str, Any]:
    from app.modules.building.drawing import parts as parts_mod

    drawing = session.get(Drawing, uuid.UUID(payload["drawing_id"]))
    if drawing is None:
        raise AppError("Чертёж удалён.")
    progress(0, 2, "Чтение чертежа")
    try:
        loaded = _load(session, drawing)
    except AppError as e:
        drawing.status, drawing.error = "failed", e.message
        return {"error": e.message}
    progress(1, 2, "Поиск этажей на листе")
    found = parts_mod.split(loaded)
    drawing.parts = _plain([
        {
            "key": p.key,
            "bbox": [round(v, 1) for v in p.bbox],
            "name": p.name,
            "level": p.level,
            "segments": p.segs,
            "preview": p.preview,
            "width": round(p.bbox[2] - p.bbox[0]),
            "height": round(p.bbox[3] - p.bbox[1]),
            "roof": bool(p.extra.get("roof")),
            "floor_like": min(p.bbox[2] - p.bbox[0], p.bbox[3] - p.bbox[1]) >= MIN_FLOOR
            and not p.extra.get("roof"),
        }
        for p in found
    ])
    largest = float(max((max(p.bbox[2] - p.bbox[0], p.bbox[3] - p.bbox[1]) for p in found),
                        default=0))
    # ни одной части размером с этаж — похоже, чертёж в масштабе листа (R-057, ADR-0025)
    drawing.sheet = {
        "scale": loaded.scale,
        "by": loaded.scale_by,
        "largest": round(largest),
        "small": largest < MIN_FLOOR,
    }
    drawing.status = "ready" if found else "failed"
    if not found:
        drawing.error = "На чертеже не нашлось ни одного плана: нет линий стен."
    progress(2, 2, "Готово")
    return {"parts": len(found)}


@tasks.task("building.convert_drawing", "Перевод чертежа в план", lane="drawings",
            timeout=timedelta(minutes=60), on_fail=_not_done)
def convert_drawing(
    session: Session, payload: dict[str, Any], progress: tasks.Progress
) -> dict[str, Any]:
    from app.modules.building.drawing import convert

    drawing = session.get(Drawing, uuid.UUID(payload["drawing_id"]))
    if drawing is None:
        raise AppError("Чертёж удалён.")
    account = access.get(session, uuid.UUID(payload["actor_id"]))
    actor = access.actor_of(account)
    mapping = payload["mapping"]
    # ход — по этапам каждой части: тяжёлая часть не стоит на одном делении (R-059)
    stages = len(convert.STAGES)
    total = len(mapping) * stages + 1
    progress(0, total, "Чтение чертежа")
    loaded = _load(session, drawing)
    parts = {p["key"]: p for p in drawing.parts}
    results: dict[str, Any] = dict(drawing.results or {})
    converted = []
    for i, m in enumerate(mapping):
        part = parts[m["key"]]
        title = part.get("name") or m["key"]

        def step(k: int, what: str, i: int = i, title: str = title) -> None:
            progress(1 + i * stages + k, total, f"Перевод: {title} — {what}")

        converted.append(convert.convert(loaded, tuple(part["bbox"]), step))  # type: ignore[arg-type]
    how = _align(session, drawing.building_id, mapping, [r.plan for r in converted])
    for m, result, placed in zip(mapping, converted, how, strict=True):
        if placed:
            result.notes.append(f"Совмещён с другими этажами: {placed}")
        if m.get("floor_id"):
            floor = api.get_floor(session, actor, uuid.UUID(str(m["floor_id"])))
        else:
            new = m["new_floor"]
            height = new.get("height") or 3300
            elevation = new.get("elevation")
            level = parts[m["key"]].get("level")
            if elevation is None and level is not None:
                # «План 3-го этажа» — на отметке двух этажей над первым; подвал — под ним
                elevation = (level - 1) * height if level > 0 else level * height
            floor = api.add_floor(
                session, actor, drawing.building_id, new["name"], elevation, height
            )
        plan = _keep_rooms(session, floor, result.plan)
        try:
            api.save_plan(
                session, actor, floor.id, plan, floor.plan_version, confirm=True, auto_merge=True
            )
        except AppError as e:
            if e.code != "needs_place" or not e.details:
                raise
            # окна выбора места у фоновой задачи нет — помещение с имуществом перевод не
            # убирает, а отказывает целиком (R-023)
            held = ", ".join(r["title"] for r in e.details["removed"] if r["property"])
            raise AppError(
                f"Перевод на этаж «{floor.name}» уберёт помещения, где числится имущество: "
                f"{held}. Перенесите имущество документом или сохраните план в редакторе, "
                "выбрав, куда оно перейдёт, — и повторите перевод."
            ) from e
        floor = session.get(Floor, floor.id)
        assert floor is not None
        floor.source_drawing_id = drawing.id
        floor.source_part = m["key"]
        results[m["key"]] = {
            "floor_id": str(floor.id),
            "floor": floor.name,
            **result.stats,
            "notes": result.notes,
        }
    drawing.results = _plain(results)
    drawing.status = "done"
    progress(total, total, "Готово")
    journal.record(
        session,
        actor,
        "drawing.convert",
        f"Чертёж «{drawing.name}» переведён в планы: "
        + ", ".join(
            f"{r['floor']} (помещений {r['rooms']})" for r in (results[m["key"]] for m in mapping)
        ),
        entity=f"drawing:{drawing.id}",
        refs=[f"building:{drawing.building_id}"],
    )
    return {"floors": [results[m["key"]]["floor_id"] for m in mapping]}


def _align(session: Session, building_id: uuid.UUID, mapping: list[dict[str, Any]],
           plans: list[Plan]) -> list[str]:
    """Этажи из частей листа ставятся друг над другом (align). Опора — этажи здания, которые
    этот перевод не заменяет; если их нет — первый из переводимых с наибольшим числом
    колонн, и тогда всё здание сдвигается к началу координат."""
    from app.modules.building.drawing import align

    replaced = {str(m["floor_id"]) for m in mapping if m.get("floor_id")}
    kept = [Plan.model_validate(f.plan) for f in api.floors(session, building_id)
            if str(f.id) not in replaced and (f.plan or {}).get("walls")]
    how = [""] * len(plans)
    if not plans:
        return how
    if kept:
        ref = align.merged(kept)
        start = 0
    else:
        best = max(range(len(plans)), key=lambda i: (len(plans[i].columns), len(plans[i].walls)))
        ref = plans[best]
        start = -1
    for i, plan in enumerate(plans):
        if plan is ref:
            continue
        (dx, dy), by = align.shift(ref, plan)
        align.translate(plan, dx, dy)
        how[i] = by
    if start == -1:
        # новое здание — к началу координат по опорному этажу
        box = align.bbox(ref)
        if box is not None:
            for plan in plans:
                align.translate(plan, -box[0], -box[1])
    return how


def _keep_rooms(session: Session, floor: Floor, plan: Plan) -> Plan:
    """Перевод заново поверх плана: помещение, которое узнаётся (номер или место), остаётся
    тем же помещением (5.1.3 п. 4)."""
    live = list(
        session.scalars(select(Room).where(Room.floor_id == floor.id, Room.archived_at.is_(None)))
    )
    if not live:
        return plan
    taken: set[uuid.UUID] = set()
    for label in plan.rooms:
        match = next(
            (r for r in live if r.id not in taken and label.number and r.number == label.number),
            None,
        )
        if match is None:
            match = next(
                (
                    r
                    for r in live
                    if r.id not in taken
                    and not label.number
                    and math.dist((r.x, r.y), (label.x, label.y)) < 1500
                ),
                None,
            )
        if match is not None:
            taken.add(match.id)
            label.id = str(match.id)
            label.name = label.name or match.name
            label.purpose_id = match.purpose_id
    return plan
