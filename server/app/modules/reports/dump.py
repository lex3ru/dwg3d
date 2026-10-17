"""Полная выгрузка здания (7.4): архив с таблицами Excel (помещения, расстановка, имущество,
остатки, документы, история) и всеми файлами (чертежи, подложки, фото и документы имущества,
3D-модели каталога) — чтобы данные учреждения можно было хранить отдельно и прочитать без
системы. Длительная операция (6.6): фоновая задача с ходом выполнения; по окончании —
сообщение со ссылкой на архив."""

import re
import uuid
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core import report, tasks
from app.core.actor import Actor
from app.core.config import config
from app.core.errors import Forbidden, NotFound
from app.modules.access import api as access
from app.modules.building import api as building
from app.modules.catalog import api as catalog
from app.modules.files import api as files
from app.modules.inventory import api as inventory
from app.modules.journal import api as journal
from app.modules.planning import api as planning

README = """Полная выгрузка: {name}
Сформирована: {at:%d.%m.%Y %H:%M}

Таблицы Excel:
  Помещения.xlsx  — этажи и помещения (номер, название, назначение, площадь)
  Расстановка.xlsx — предметы на плане: этаж, помещение, тип, модель, координаты (мм),
                     поворот, высота, инвентарный номер
  Имущество.xlsx  — инвентарные единицы: номер, наименование, модель, место, состояние,
                     ответственный, стоимость
  Характеристики.xlsx — значения характеристик у каждой вещи (номер, характеристика, значение)
  Остатки.xlsx    — количественный учёт по местам
  Документы.xlsx  — строки документов: что, откуда, куда, когда
  История.xlsx    — журнал изменений: кто, когда, что было и что стало
  Каталог.xlsx    — каталог целиком: слои, наборы характеристик, типы, модели со значениями
                     характеристик, назначения помещений (загружается обратно в систему)
Файлы:
  файлы/чертежи, файлы/подложки, файлы/имущество, файлы/документы, файлы/3D-модели
Описание столбцов — docs/EXPORT.md в составе системы.
"""


def _safe(name: str) -> str:
    return re.sub(r'[\\\\/:*?"<>|]+', "_", name).strip()[:120] or "файл"


def exports_dir() -> Path:
    path = config().data_dir / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def start(session: Session, actor: Actor, building_id: uuid.UUID | None) -> uuid.UUID:
    if not actor.is_admin:
        raise Forbidden()
    if building_id is not None:
        building.get_building(session, actor, building_id)
    return tasks.enqueue(
        session,
        "reports.full_export",
        {"building_id": str(building_id) if building_id else None, "user_id": str(actor.user_id)},
        actor,
    )


def _floor_tables(session: Session, actor: Actor, b: Any) -> tuple[report.Report, report.Report]:
    rooms_rows, items_rows = [], []
    purposes = catalog.purpose_map(session)
    for f in building.floors(session, b.id):
        titles = {}
        for r in building.live_rooms(session, f.id):
            titles[r.id] = building.room_title(r)
            p = purposes.get(r.purpose_id or "")
            rooms_rows.append([f.name, r.number, r.name, p.name if p else "", r.area])
        items = planning.floor_items_raw(session, f.id)
        types = catalog.types_by_id(session, [i.type_id for i in items])
        models = catalog.models_by_id(session, [i.model_id for i in items if i.model_id])
        units = inventory.units_by_id(session, [i.unit_id for i in items if i.unit_id])
        for i in items:
            m = models.get(i.model_id) if i.model_id else None
            u = units.get(i.unit_id) if i.unit_id else None
            items_rows.append(
                [
                    f.name,
                    titles.get(i.room_id, "вне помещений") if i.room_id else "вне помещений",
                    types[i.type_id].name,
                    f"{m.manufacturer} {m.name}".strip() if m else "",
                    round(i.x, 1) if i.x is not None else "",
                    round(i.y, 1) if i.y is not None else "",
                    round(i.angle, 1),
                    round(i.z, 1),
                    i.label,
                    u.number if u else "",
                ]
            )
    rooms = report.Report(
        title=f"{b.name} — помещения",
        sections=[
            report.Section(
                "Помещения", ["Этаж", "Номер", "Название", "Назначение", "Площадь, м²"], rooms_rows
            )
        ],
    )
    layout = report.Report(
        title=f"{b.name} — расстановка",
        sections=[
            report.Section(
                "Расстановка",
                [
                    "Этаж",
                    "Помещение",
                    "Тип",
                    "Модель",
                    "X, мм",
                    "Y, мм",
                    "Поворот, °",
                    "Высота, мм",
                    "Подпись",
                    "Инв. №",
                ],
                items_rows,
            )
        ],
    )
    return rooms, layout


@tasks.task("reports.full_export", "Полная выгрузка")
def run(session: Session, payload: dict[str, Any], progress: tasks.Progress) -> dict[str, Any]:
    account = access.get(session, uuid.UUID(payload["user_id"]))
    actor = access.actor_of(account)
    wanted = payload.get("building_id")
    buildings = (
        [building.get_building(session, actor, uuid.UUID(wanted))]
        if wanted
        else [
            building.get_building(session, actor, x["id"])
            for x in building.list_buildings(session, actor)
        ]
    )
    if not buildings:
        raise NotFound("Зданий нет.")
    name = buildings[0].name if wanted else "все здания"
    target = exports_dir() / f"{progress.job_id}.zip"
    total = len(buildings) * 7 + 1
    step = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", README.format(name=name, at=datetime.now()))
        seen: set[uuid.UUID] = set()

        def put_file(folder: str, file_id: uuid.UUID, label: str) -> None:
            if file_id in seen:
                return
            seen.add(file_id)
            try:
                rec = files.get(session, file_id)
            except NotFound:
                return
            path = files.path_of(rec.sha256)
            if path.exists():
                z.write(path, f"{root}файлы/{folder}/{_safe(label)} — {_safe(rec.name)}")

        for b in buildings:
            root = f"{_safe(b.name)}/" if not wanted else ""
            progress(step, total, f"{b.name}: помещения и расстановка")
            rooms, layout = _floor_tables(session, actor, b)
            z.writestr(f"{root}Помещения.xlsx", report.xlsx(rooms))
            z.writestr(f"{root}Расстановка.xlsx", report.xlsx(layout))
            step += 1
            progress(step, total, f"{b.name}: имущество")
            z.writestr(
                f"{root}Имущество.xlsx",
                inventory.registry_xlsx(session, actor, building_id=b.id, written_off=True),
            )
            z.writestr(
                f"{root}Характеристики.xlsx",
                report.xlsx(
                    report.Report(
                        title=f"{b.name} — характеристики имущества",
                        sections=[
                            report.Section(
                                "Характеристики",
                                ["Инв. №", "Наименование", "Характеристика", "Значение"],
                                inventory.unit_values_rows(session, b.id),
                            )
                        ],
                    )
                ),
            )
            step += 1
            stock = inventory.balance_rows(session, actor, building_id=b.id)
            z.writestr(
                f"{root}Остатки.xlsx",
                report.xlsx(
                    report.Report(
                        title=f"{b.name} — остатки",
                        sections=[
                            report.Section(
                                "Остатки",
                                ["Место", "Тип", "Модель", "Ед.", "Количество", "Сумма"],
                                [
                                    [
                                        s["place_title"],
                                        s["type_name"],
                                        s["model_name"],
                                        s["unit"],
                                        s["qty"],
                                        s.get("amount", 0.0),
                                    ]
                                    for s in stock
                                ],
                            )
                        ],
                    )
                ),
            )
            step += 1
            progress(step, total, f"{b.name}: документы")
            moves = inventory.movement_rows(session, actor, date(2000, 1, 1), date.today(), b.id)
            z.writestr(
                f"{root}Документы.xlsx",
                report.xlsx(
                    report.Report(
                        title=f"{b.name} — документы",
                        sections=[
                            report.Section(
                                "Строки документов",
                                [
                                    "Дата",
                                    "Документ",
                                    "Что",
                                    "Кол-во",
                                    "Ед.",
                                    "Откуда",
                                    "Куда",
                                    "Сумма",
                                    "Примечание",
                                ],
                                [
                                    [
                                        m["date"],
                                        m["document"]
                                        + (f" ({m['status']})" if m["status"] else ""),
                                        m["what"],
                                        m["qty"],
                                        m["unit"],
                                        m["from"],
                                        m["to"],
                                        m["amount"],
                                        m["note"],
                                    ]
                                    for m in moves
                                ],
                            )
                        ],
                    )
                ),
            )
            step += 1
            progress(step, total, f"{b.name}: история")
            refs = [f"building:{b.id}"]
            for f in building.floors(session, b.id):
                refs.append(f"floor:{f.id}")
                refs += [f"room:{r.id}" for r in building.live_rooms(session, f.id)]
            entries = journal.entries_for(session, refs)
            z.writestr(
                f"{root}История.xlsx",
                report.xlsx(
                    report.Report(
                        title=f"{b.name} — история",
                        sections=[
                            report.Section(
                                "Журнал",
                                ["Когда", "Кто", "Что", "Было", "Стало"],
                                [
                                    [
                                        e.at.strftime("%d.%m.%Y %H:%M"),
                                        e.actor_name,
                                        e.summary,
                                        str(e.before or "")[:3000],
                                        str(e.after or "")[:3000],
                                    ]
                                    for e in entries
                                ],
                            )
                        ],
                    )
                ),
            )
            step += 1
            progress(step, total, f"{b.name}: файлы")
            for folder, file_id, label in building.building_files(session, actor, b.id):
                put_file(folder, file_id, label)
            for folder, file_id, label in inventory.unit_files(session, b.id):
                put_file(folder, file_id, label)
            step += 2
        root = ""
        z.writestr("Каталог.xlsx", catalog.export_xlsx(session))
        for t in catalog.all_types(session):
            if t.model_file_id:
                put_file("3D-модели", t.model_file_id, t.name)
    progress(total, total, "Готово")
    size = target.stat().st_size
    stamp = f"{date.today():%Y-%m-%d}"
    return {
        "file": f"Выгрузка — {_safe(name)} — {stamp}.zip",
        "size": size,
        "href": f"/api/reports/exports/{progress.job_id}",
    }


def export_file(session: Session, actor: Actor, job_id: uuid.UUID) -> tuple[Path, str]:
    if not actor.is_admin:
        raise Forbidden()
    job = session.get(tasks.Job, job_id)
    path = exports_dir() / f"{job_id}.zip"
    if job is None or job.kind != "reports.full_export" or not path.exists():
        raise NotFound("Выгрузка не найдена — возможно, её уже удалили.")
    return path, str((job.result or {}).get("file") or "Выгрузка.zip")
