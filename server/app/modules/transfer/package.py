"""Перенос здания на другую установку: пакет — архив ZIP, который выгружается на одной
установке и загружается на другой. Внутри:

  manifest.json   вид и версия пакета, откуда и когда, здание, сколько чего, файлы
  catalog.json    часть каталога, которой пользуются предметы и единицы здания
  building.json   этажи с планами и лифты
  items.json      предметы расстановки
  inventory.json  склады здания, метки дверей, инвентарные единицы, остатки
  files/<ключ>    подложки, 3D-модели, фото и файлы единиц

Ключи внутри — id на исходной установке; на новой всё получает свои id. Загрузка — сначала
проверка (что заведётся, что совпало, какие номера заняты), затем фоновой задачей одной
транзакцией: всё или ничего."""

import json
import time
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO, Any

from sqlalchemy.orm import Session

from app.core import tasks
from app.core.actor import Actor
from app.core.config import config
from app.core.errors import AppError, Forbidden
from app.modules.access import api as access
from app.modules.building import api as building
from app.modules.catalog import api as catalog
from app.modules.files import api as files
from app.modules.inventory import api as inventory
from app.modules.journal import api as journal
from app.modules.planning import api as planning

FORMAT = "planuchet-building"
VERSION = 1
PARTS = ("catalog", "building", "items", "inventory")


def _admin(actor: Actor) -> None:
    if not actor.is_admin:
        raise Forbidden()


def build(session: Session, actor: Actor, building_id: uuid.UUID, target: IO[bytes]) -> str:
    """Записать пакет здания в target; возвращает имя файла."""
    _admin(actor)
    b = building.get_building(session, actor, building_id)
    structure, floor_files, purposes = building.transfer_export(session, actor, b.id)
    items = planning.transfer_export(session, actor, b.id)
    stock, unit_files, type_ids, model_ids = inventory.transfer_export(session, actor, b.id)
    type_ids |= {uuid.UUID(i["type"]) for i in items}
    model_ids |= {uuid.UUID(i["model"]) for i in items if i["model"]}
    cat, model_files = catalog.transfer_export(session, type_ids, model_ids, purposes)
    wanted = list(dict.fromkeys([*floor_files, *unit_files, *model_files]))
    listed: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for file_id in wanted:
            try:
                rec = files.get(session, file_id)
            except Exception:  # файла нет на диске — пакет без него
                continue
            z.write(files.path_of(rec.sha256), f"files/{file_id}")
            listed[str(file_id)] = {
                "name": rec.name,
                "content_type": rec.content_type,
                "size": rec.size,
            }
        parts = {"catalog": cat, "building": structure, "items": items, "inventory": stock}
        for name, data in parts.items():
            z.writestr(f"{name}.json", json.dumps(data, ensure_ascii=False, default=str))
        z.writestr(
            "manifest.json",
            json.dumps(
                {
                    "format": FORMAT,
                    "version": VERSION,
                    "exported_at": datetime.now(UTC).isoformat(),
                    "exported_by": actor.full_name,
                    "building": {"name": b.name, "address": b.address},
                    "counts": {
                        "floors": len(structure["floors"]),
                        "items": len(items),
                        "units": len(stock["units"]),
                        "stock": len(stock["stock"]),
                        "types": len(cat["types"]),
                        "files": len(listed),
                    },
                    "files": listed,
                },
                ensure_ascii=False,
                indent=1,
            ),
        )
    journal.record(
        session,
        actor,
        "transfer.export",
        f"Выгружено здание «{b.name}» для переноса: этажей "
        f"{len(structure['floors'])}, предметов {len(items)}, единиц "
        f"{len(stock['units'])}",
        entity=f"building:{b.id}",
    )
    stamp = datetime.now().strftime("%Y-%m-%d")
    return f"Перенос — {b.name} — {stamp}.zip"


class Package:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.zip = zipfile.ZipFile(path)
            self.manifest = json.loads(self.zip.read("manifest.json"))
        except (zipfile.BadZipFile, KeyError, ValueError):
            raise AppError(
                "Это не пакет переноса здания: нужен архив, выгруженный кнопкой "
                "«Выгрузить для переноса».",
                code="bad_package",
            ) from None
        if self.manifest.get("format") != FORMAT:
            raise AppError("Это не пакет переноса здания.", code="bad_package")
        if int(self.manifest.get("version", 0)) > VERSION:
            raise AppError(
                "Пакет сделан более новой версией системы — обновите эту установку.",
                code="bad_package",
            )
        self.parts = {p: json.loads(self.zip.read(f"{p}.json")) for p in PARTS}

    def store_files(self, session: Session, actor: Actor) -> dict[str, uuid.UUID]:
        out: dict[str, uuid.UUID] = {}
        for key, meta in self.manifest.get("files", {}).items():
            try:
                with self.zip.open(f"files/{key}") as stream:
                    rec = files.store(
                        session, actor, stream, meta.get("name") or key, set(files.KINDS)
                    )
            except (KeyError, AppError):
                continue
            out[key] = rec.id
        return out


def uploads_dir() -> Path:
    path = config().data_dir / "transfers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def receive(stream: IO[bytes]) -> uuid.UUID:
    """Сохранить загруженный пакет до загрузки (проверка, затем задача)."""
    # проверенные, но не загруженные пакеты — старше суток убираются
    for old in uploads_dir().glob("*.zip"):
        if old.stat().st_mtime < time.time() - 86400:
            old.unlink(missing_ok=True)
    upload = uuid.uuid4()
    with open(uploads_dir() / f"{upload}.zip", "wb") as out:
        while chunk := stream.read(1024 * 1024):
            out.write(chunk)
    return upload


def _path(upload: uuid.UUID) -> Path:
    path = uploads_dir() / f"{upload}.zip"
    if not path.exists():
        raise AppError("Загруженный пакет не найден — загрузите файл ещё раз.", code="gone")
    return path


def check(session: Session, actor: Actor, upload: uuid.UUID) -> dict[str, Any]:
    """Что будет при загрузке: что заведётся в каталоге, что совпало, какие номера заняты."""
    _admin(actor)
    pkg = Package(_path(upload))
    cat = catalog.transfer_load(session, actor, pkg.parts["catalog"], {}, apply=False)
    inv = inventory.transfer_check(session, pkg.parts["inventory"])
    b = pkg.parts["building"]
    name = b["name"]
    names = {x["name"] for x in building.list_buildings(session, actor)}
    suggested = name
    n = 2
    while suggested in names:
        suggested = f"{name} ({n})"
        n += 1
    return {
        "upload_id": upload,
        "exported_at": pkg.manifest.get("exported_at"),
        "exported_by": pkg.manifest.get("exported_by"),
        "building": {
            "name": name,
            "address": b.get("address", ""),
            "suggested": suggested,
            "exists": name in names,
        },
        "floors": len(b["floors"]),
        "rooms": sum(len(f["plan"].get("rooms", [])) for f in b["floors"]),
        "items": len(pkg.parts["items"]),
        **inv,
        "files": len(pkg.manifest.get("files", {})),
        "catalog": cat["report"],
    }


def start(
    session: Session, actor: Actor, upload: uuid.UUID, name: str, renumber: bool
) -> uuid.UUID:
    _admin(actor)
    _path(upload)
    if not name.strip():
        raise AppError("Укажите название здания.", field="name")
    return tasks.enqueue(
        session,
        "transfer.import",
        {
            "upload": str(upload),
            "name": name.strip(),
            "renumber": renumber,
            "user_id": str(actor.user_id),
        },
        actor,
    )


@tasks.task("transfer.import", "Загрузка здания", timeout=timedelta(minutes=60))
def run(session: Session, payload: dict[str, Any], progress: tasks.Progress) -> dict[str, Any]:
    actor = access.actor_of(access.get(session, uuid.UUID(payload["user_id"])))
    path = _path(uuid.UUID(payload["upload"]))
    pkg = Package(path)
    progress(0, 5, "файлы")
    stored = pkg.store_files(session, actor)
    progress(1, 5, "каталог")
    cat = catalog.transfer_load(session, actor, pkg.parts["catalog"], stored, apply=True)
    maps = cat["maps"]
    progress(2, 5, "этажи и планы")
    made = building.transfer_load(
        session, actor, pkg.parts["building"], payload["name"], maps["purposes"], stored
    )
    progress(3, 5, "учёт")
    inv = inventory.transfer_load(
        session,
        actor,
        pkg.parts["inventory"],
        made["building_id"],
        made["rooms"],
        maps["types"],
        maps["models"],
        maps["item_chars"],
        stored,
        bool(payload.get("renumber")),
    )
    progress(4, 5, "расстановка")
    placed = planning.transfer_load(
        session,
        actor,
        pkg.parts["items"],
        made["floors"],
        maps["types"],
        maps["models"],
        inv["units"],
    )
    journal.record(
        session,
        actor,
        "transfer.import",
        f"Загружено здание «{payload['name']}» с другой установки: этажей "
        f"{len(made['floors'])}, предметов {placed}, единиц {len(inv['units'])}"
        + (f", новые номера у {inv['renumbered']}" if inv["renumbered"] else ""),
        entity=f"building:{made['building_id']}",
        refs=[f"building:{made['building_id']}"],
    )
    progress(5, 5, "Готово")
    pkg.zip.close()
    path.unlink(missing_ok=True)
    return {
        "building_id": str(made["building_id"]),
        "floors": len(made["floors"]),
        "items": placed,
        "units": len(inv["units"]),
        "renumbered": inv["renumbered"],
        "skipped": inv["skipped"],
        "document_id": str(inv["document_id"] or ""),
        "href": f"/buildings?b={made['building_id']}",
    }
