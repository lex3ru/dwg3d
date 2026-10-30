"""Перевод чертежа в план (5.1.3, С1)."""

import io
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import ezdxf
import pytest

from app.core import tasks
from app.modules.building.drawing import convert, layers, parts, read
from tests.test_inventory import document, kinds, post
from tests.test_planning import changes

ROOT = Path(__file__).resolve().parents[2]
# конвертер DWG — из APP_DWG2DXF или PATH: в образе он есть (deploy/Dockerfile), на машине
# разработчика обычно нет, и тесты DWG пропускаются (R-060, docs/INSTALL.md)


def sample_dxf(partition: float | None = 5000, *, sheet: float = 1, walls: str = "Стены",
               partitions: str = "Перегородки", zones: str | None = None,
               stray: str | None = None) -> bytes:
    """Два этажа рядом на одном листе: коробка 9 × 6 м двойными линиями стен (300 мм),
    перегородка (120 мм) с дверным проёмом, окно в наружной стене, подписи помещений.
    partition — x перегородки; None — перегородку снесли, обе подписи в одном помещении.
    sheet — чертёж в масштабе листа 1:sheet (мм бумаги), без размеров: масштаба в нём нет.
    walls, partitions — слои стен и перегородок; zones — слой функциональных зон: штриховки
    и значки зон в помещениях; stray — слой, на котором под планом лежит обрывок стены."""
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for name in {walls, partitions, "Окна", "Текст", zones or "0", stray or "0"} - {"0"}:
        doc.layers.add(name)

    def floor(ox: float, title: str, n1: str, n2: str) -> None:
        def at(x: float, y: float) -> tuple[float, float]:
            return ((ox + x) / sheet, y / sheet)

        def poly(points, layer):  # type: ignore[no-untyped-def]
            msp.add_lwpolyline([at(x, y) for x, y in points], close=True,
                               dxfattribs={"layer": layer})

        def text(value: str, height: float, x: float, y: float, layer: str = "0") -> None:
            msp.add_text(value, height=height / sheet,
                         dxfattribs={"layer": layer, "insert": at(x, y)})
        # наружные стены: внешний и внутренний контур, в нижней стене — проём под окно
        poly([(0, 0), (3000, 0), (3000, 300), (300, 300), (300, 5700), (8700, 5700),
              (8700, 300), (4500, 300), (4500, 0), (9000, 0), (9000, 6000), (0, 6000)], walls)
        for x0, x1 in ((3000, 4500),):
            msp.add_line(at(x0, 100), at(x1, 100), dxfattribs={"layer": "Окна"})
            msp.add_line(at(x0, 200), at(x1, 200), dxfattribs={"layer": "Окна"})
        # перегородка (по умолчанию x = 5000) с дверью 900 мм (просвет y 2000…2900)
        if partition is not None:
            a, b = partition, partition + 120
            poly([(a, 300), (b, 300), (b, 2000), (a, 2000)], partitions)
            poly([(a, 2900), (b, 2900), (b, 5700), (a, 5700)], partitions)
        if zones is not None:
            # зона помещения — штриховка, в ней значок зоны: крестик 10 × 10 см
            for x0, x1 in ((300, 5000), (5120, 8700)):
                hatch = msp.add_hatch(dxfattribs={"layer": zones})
                hatch.paths.add_polyline_path([at(x0, 300), at(x1, 300), at(x1, 5700),
                                               at(x0, 5700)])
                fx, fy = x0 + 600, 4800
                msp.add_line(at(fx, fy), at(fx + 100, fy + 100), dxfattribs={"layer": zones})
                msp.add_line(at(fx, fy + 100), at(fx + 100, fy), dxfattribs={"layer": zones})
        if stray is not None:
            # под планом — обрывок стены 1 м: слой стен на листе есть, но почти пуст
            poly([(0, -1500), (1000, -1500), (1000, -1200), (0, -1200)], stray)
        text(n1, 300, 2500, 3000)
        text("Регистратура", 250, 1500, 2500)
        text(n2, 300, 7000, 3000)
        text(title, 500, 2000, 6800, "Текст")

    floor(0, "План 1-го этажа", "101", "102")
    floor(20000, "План 2-го этажа", "201", "202")
    out = io.StringIO()
    doc.write(out)
    return out.getvalue().encode()


def test_parts_and_conversion_of_a_sample(tmp_path) -> None:
    path = tmp_path / "sample.dxf"
    path.write_bytes(sample_dxf())
    drawing = read.load(path)
    found = parts.split(drawing)
    assert [(p.name, p.level) for p in found] == [("План 1-го этажа", 1), ("План 2-го этажа", 2)]
    result = convert.convert(drawing, found[0].bbox)
    assert result.stats["issues"] == 0
    rooms = {(r.number, r.name) for r in result.plan.rooms}
    assert rooms == {("101", "Регистратура"), ("102", "")}
    kinds = sorted(o.kind for o in result.plan.openings)
    assert kinds == ["door", "window"]
    thick = sorted({w.thickness for w in result.plan.walls})
    assert thick == [120, 300]


def test_upload_analyze_and_convert(admin) -> None:
    b = admin.post("/api/buildings", json={"name": "Бастион"}).json()
    r = admin.post(f"/api/buildings/{b['id']}/drawings",
                   files={"file": ("планы.dxf", io.BytesIO(sample_dxf()))})
    assert r.status_code == 201, r.text
    drawing = r.json()
    assert drawing["status"] == "analyzing"
    while tasks.run_one():
        pass
    full = admin.get(f"/api/drawings/{drawing['id']}").json()
    assert full["status"] == "ready" and len(full["parts"]) == 2
    assert full["parts"][0]["preview"].startswith("M")
    keys = [p["key"] for p in full["parts"]]
    job = admin.post(f"/api/drawings/{drawing['id']}/convert", json={"parts": [
        {"key": keys[0], "new_floor": {"name": "1 этаж"}},
        {"key": keys[1], "new_floor": {"name": "2 этаж"}}]}).json()["job_id"]
    while tasks.run_one():
        pass
    status = admin.get(f"/api/system/tasks/{job}").json()
    assert status["status"] == "done", status
    floors = admin.get(f"/api/buildings/{b['id']}").json()["floors"]
    assert [f["name"] for f in floors] == ["1 этаж", "2 этаж"]
    plan = admin.get(f"/api/floors/{floors[1]['id']}/plan").json()
    assert sorted(r["number"] for r in plan["rooms"]) == ["201", "202"]
    first = {r["number"]: r["id"] for r in plan["rooms"]}

    # перевод заново поверх плана: помещения узнаются по номерам и остаются теми же
    job = admin.post(f"/api/drawings/{drawing['id']}/convert", json={"parts": [
        {"key": keys[1], "floor_id": floors[1]["id"]}]}).json()["job_id"]
    while tasks.run_one():
        pass
    again = admin.get(f"/api/floors/{floors[1]['id']}/plan").json()
    assert {r["number"]: r["id"] for r in again["rooms"]} == first


def run_in_worker(admin, job: str, log: Path, timeout: float = 120) -> dict:  # type: ignore[no-untyped-def]
    """Выполнить задачу командой `python -m app worker` — отдельным процессом, как в установке:
    модули в нём настраивает сама команда, а не create_app() тестов (R-009, R-033)."""
    with log.open("wb") as out:
        worker = subprocess.Popen([sys.executable, "-m", "app", "worker"], cwd=ROOT / "server",
                                  stdout=out, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + timeout
            while True:
                status = admin.get(f"/api/system/tasks/{job}").json()
                if (status["status"] in ("done", "failed") or worker.poll() is not None
                        or time.monotonic() > deadline):
                    break
                time.sleep(0.5)
        finally:
            worker.terminate()
            worker.wait(timeout=30)
    if status["status"] not in ("done", "failed"):
        pytest.fail(f"Обработчик не выполнил задачу: {status}\n"
                    + log.read_text(encoding="utf-8", errors="replace")[-3000:])
    return status


def upload(admin, building_id: str, data: bytes) -> dict:  # type: ignore[no-untyped-def]
    """Загрузить чертёж и дождаться разбора (в процессе тестов)."""
    r = admin.post(f"/api/buildings/{building_id}/drawings",
                   files={"file": ("планы.dxf", io.BytesIO(data))})
    assert r.status_code == 201, r.text
    while tasks.run_one():
        pass
    return admin.get(f"/api/drawings/{r.json()['id']}").json()


def convert_onto(admin, drawing: dict, floor_id: str) -> str:  # type: ignore[no-untyped-def]
    """Поставить в очередь перевод первого этажа чертежа поверх этажа; номер задачи."""
    return admin.post(f"/api/drawings/{drawing['id']}/convert", json={"parts": [
        {"key": drawing["parts"][0]["key"], "floor_id": floor_id}]}).json()["job_id"]


def first_floor(admin) -> tuple[str, str, dict]:  # type: ignore[no-untyped-def,type-arg]
    """Здание с «1 этаж» из чертежа: номер здания, этажа и помещения 101, 102 по номерам."""
    b = admin.post("/api/buildings", json={"name": "Бастион"}).json()
    v1 = upload(admin, b["id"], sample_dxf())
    admin.post(f"/api/drawings/{v1['id']}/convert", json={"parts": [
        {"key": v1["parts"][0]["key"], "new_floor": {"name": "1 этаж"}}]})
    while tasks.run_one():
        pass
    floor_id = admin.get(f"/api/buildings/{b['id']}").json()["floors"][0]["id"]
    rooms = {r["number"]: r for r in admin.get(f"/api/floors/{floor_id}/plan").json()["rooms"]}
    return b["id"], floor_id, rooms


def test_r009_reconversion_in_the_worker_moves_items_and_units(admin, tmp_path) -> None:
    """Перевод заново поверх этажа выполняет обработчик: перегородку сдвинули вправо, стол у
    прежней перегородки теперь в 101 — он и его единица переходят туда (5.1.3 п. 4, 5.5)."""
    building_id, floor_id, rooms = first_floor(admin)
    r101, r102 = rooms["101"], rooms["102"]

    # в 102 у самой перегородки стол — предмет, связанный с единицей
    k = kinds(admin)
    wh = admin.post("/api/inventory/warehouses", json={"name": "Основной"}).json()
    receipt = document(admin, "receipt", {"to_place": wh["key"]},
                       [{"type_id": k["монитор"]["id"], "qty": 1, "price": 14500}])
    assert post(admin, receipt).status_code == 200
    lines = admin.get(f"/api/inventory/documents/{receipt['id']}").json()["lines"]
    unit_id = lines[0]["created_units"][0]["id"]
    issue = document(admin, "transfer", {"from_place": wh["key"], "to_place": f"r:{r102['id']}"},
                     [{"unit_id": unit_id}])
    assert post(admin, issue).status_code == 200
    x = min(x for x, _ in r102["outline"]) + 500
    r = changes(admin, floor_id, create=[{"type_id": k["монитор"]["id"], "unit_id": unit_id,
                                          "x": x, "y": r102["y"]}])
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["room_id"] == r102["id"]

    job = convert_onto(admin, upload(admin, building_id, sample_dxf(partition=6500)), floor_id)
    status = run_in_worker(admin, job, tmp_path / "worker.log")
    assert status["status"] == "done", status

    live = {r["number"]: r["id"] for r in admin.get(f"/api/floors/{floor_id}/plan").json()["rooms"]}
    assert live == {"101": r101["id"], "102": r102["id"]}  # помещения те же
    assert admin.get(f"/api/items/{item['id']}").json()["room_id"] == r101["id"]
    assert admin.get(f"/api/inventory/units/{unit_id}").json()["place"]["key"] == f"r:{r101['id']}"
    docs = admin.get("/api/inventory/documents", params={"unit_id": unit_id}).json()["items"]
    assert any(d["basis"] == "Изменение плана" for d in docs)


def test_r023_reconversion_does_not_remove_a_room_with_property(admin) -> None:
    """Перевод заново сносит перегородку: подпись остаётся одна, и 102 убирается, а в нём
    числится имущество. Окна выбора места у фоновой задачи нет — она отказывает, назвав
    помещение, и ничего не меняет (5.1.3 п. 4, 5.1.6 п. 3, R-023)."""
    building_id, floor_id, rooms = first_floor(admin)
    room = f"r:{rooms['102']['id']}"
    k = kinds(admin)
    receipt = document(admin, "receipt", {"to_place": room},
                       [{"type_id": k["экг"]["id"], "qty": 1, "price": 85000},
                        {"type_id": k["перчатки"]["id"], "qty": 20, "price": 520}])
    assert post(admin, receipt).status_code == 200
    lines = admin.get(f"/api/inventory/documents/{receipt['id']}").json()["lines"]
    unit_id = lines[0]["created_units"][0]["id"]

    job = convert_onto(admin, upload(admin, building_id, sample_dxf(partition=None)), floor_id)
    while tasks.run_one():
        pass
    status = admin.get(f"/api/system/tasks/{job}").json()
    assert status["status"] == "failed", status
    assert "102" in status["error"]

    live = {r["number"]: r["id"] for r in admin.get(f"/api/floors/{floor_id}/plan").json()["rooms"]}
    assert live == {"101": rooms["101"]["id"], "102": rooms["102"]["id"]}
    assert admin.get(f"/api/inventory/units/{unit_id}").json()["place"]["key"] == room
    stock = admin.get("/api/inventory/balances", params={"place": room}).json()["items"]
    assert [(s["type_name"], s["qty"]) for s in stock] == [("Перчатки смотровые", 20)]


def test_not_a_drawing_is_refused(admin) -> None:
    b = admin.post("/api/buildings", json={"name": "Х"}).json()
    r = admin.post(f"/api/buildings/{b['id']}/drawings",
                   files={"file": ("план.dwg", io.BytesIO(b"%PDF-1.4 not a drawing"))})
    assert r.status_code == 400 and "не DWG" in r.json()["error"]["message"]
    assert admin.post(f"/api/drawings/{uuid.uuid4()}/convert",
                      json={"parts": []}).status_code == 404


BASTION = ROOT / "Поэтажные планы Бастион.dxf"


@pytest.mark.skipif(not BASTION.exists(), reason="нет чертежа «Бастиона» (данные заказчика)")
def test_bastion_converts_without_check_errors_and_with_room_numbers() -> None:
    drawing = read.load(BASTION)
    found = [p for p in parts.split(drawing) if min(p.bbox[2] - p.bbox[0],
                                                     p.bbox[3] - p.bbox[1]) > 5000]
    assert len(found) == 1
    result = convert.convert(drawing, found[0].bbox)
    assert result.stats["issues"] == 0
    numbers = sorted(int(r.number) for r in result.plan.rooms if r.number)
    assert numbers == [1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12]


EXTRA = [ROOT / "2022-06-02 - Поэтажные планы.dwg", ROOT / "mnogoprofilny_meditsinskiy_tsentr.dwg"]


@pytest.mark.skipif(not all(p.exists() for p in EXTRA) or not read.dwg2dxf(),
                    reason="нет дополнительных чертежей или LibreDWG")
@pytest.mark.parametrize("path", EXTRA, ids=["2022", "medcenter"])
def test_extra_drawings_convert_without_check_errors(path: Path) -> None:
    drawing = read.load(path)
    found = parts.split(drawing)
    if path.name.startswith("2022"):
        # 13 этажей: подвал, 1–11, технический; план кровли — не этаж
        floors = [p for p in found if min(p.bbox[2] - p.bbox[0], p.bbox[3] - p.bbox[1]) >= 5000
                  and not p.extra.get("roof")]
        assert len(floors) == 13, [p.name for p in floors]
    for part in found:
        if min(part.bbox[2] - part.bbox[0], part.bbox[3] - part.bbox[1]) < 5000:
            continue
        assert convert.convert(drawing, part.bbox).stats["issues"] == 0, part.name



def test_floors_of_one_sheet_stand_on_top_of_each_other(admin) -> None:
    b = admin.post("/api/buildings", json={"name": "Совмещение"}).json()
    d = admin.post(f"/api/buildings/{b['id']}/drawings",
                   files={"file": ("планы.dxf", io.BytesIO(sample_dxf()))}).json()
    while tasks.run_one():
        pass
    keys = [p["key"] for p in admin.get(f"/api/drawings/{d['id']}").json()["parts"]]
    admin.post(f"/api/drawings/{d['id']}/convert", json={"parts": [
        {"key": k, "new_floor": {"name": f"{i} этаж"}} for i, k in enumerate(keys, 1)]})
    while tasks.run_one():
        pass
    floors = admin.get(f"/api/buildings/{b['id']}").json()["floors"]
    assert [f["elevation"] for f in floors] == [0, 3300]
    boxes = []
    for f in floors:
        nodes = admin.get(f"/api/floors/{f['id']}/plan").json()["plan"]["nodes"].values()
        boxes.append((min(x for x, _ in nodes), min(y for _, y in nodes)))
    # второй этаж лежал на листе в 20 м правее — теперь над первым, здание у начала координат
    assert boxes[0] == boxes[1]
    assert abs(boxes[0][0]) < 200 and abs(boxes[0][1]) < 200


def test_failed_conversion_leaves_the_drawing_ready_to_convert_again(admin) -> None:
    """Перевод упал — чертёж не остаётся «переводится» навсегда: видно, почему не вышло, и
    перевод можно повторить. Так же — после отмены и таймаута (R-026, ADR-0011)."""
    from app.core.db import transaction
    from app.modules.files import api as files
    from app.modules.files.models import StoredFile

    b = admin.post("/api/buildings", json={"name": "Корпус"}).json()
    drawing = upload(admin, b["id"], sample_dxf())
    with transaction() as s:
        stored = files.path_of(s.get(StoredFile, uuid.UUID(drawing["file_url"].rsplit("/")[-1]))
                               .sha256)
    part = {"key": drawing["parts"][0]["key"], "new_floor": {"name": "1 этаж"}}
    hidden = stored.with_suffix(".hidden")
    stored.rename(hidden)  # файл чертежа пропал — задача перевода падает
    try:
        r = admin.post(f"/api/drawings/{drawing['id']}/convert", json={"parts": [part]})
        assert r.status_code == 200, r.text
        while tasks.run_one():
            pass
    finally:
        hidden.rename(stored)
    failed = admin.get(f"/api/system/tasks/{r.json()['job_id']}").json()
    assert failed["status"] == "failed", failed
    again = admin.get(f"/api/drawings/{drawing['id']}").json()
    assert (again["status"], again["error"]) == ("ready", failed["error"])

    r = admin.post(f"/api/drawings/{drawing['id']}/convert", json={"parts": [part]})
    assert r.status_code == 200, r.text
    while tasks.run_one():
        pass
    assert admin.get(f"/api/system/tasks/{r.json()['job_id']}").json()["status"] == "done"
    assert admin.get(f"/api/drawings/{drawing['id']}").json()["status"] == "done"


def tangle(lines: int = 12000) -> bytes:
    """Чертёж из случайных пересекающихся линий: разбор — секунды, перевод — минуты (R-026,
    artifacts/stage4-dxf-50k.txt: 50 000 линий — дольше 25 минут)."""
    import random

    rnd = random.Random(12)
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    doc.layers.add("Стены")
    for _ in range(lines):
        msp.add_line((rnd.uniform(0, 30000), rnd.uniform(0, 20000)),
                     (rnd.uniform(0, 30000), rnd.uniform(0, 20000)), dxfattribs={"layer": "Стены"})
    out = io.StringIO()
    doc.write(out)
    return out.getvalue().encode()


def test_r026_heavy_drawing_does_not_hold_the_queue_and_can_be_cancelled(admin, tmp_path) -> None:
    """Обработчик `python -m app worker`: пока переводится тяжёлый чертёж, другие задачи
    выполняются; перевод отменяют — этаж не заводится, чертёж снова готов к переводу."""
    from app.core.db import transaction

    b = admin.post("/api/buildings", json={"name": "Корпус"}).json()
    drawing = upload(admin, b["id"], tangle())
    assert drawing["status"] == "ready" and drawing["parts"], drawing
    r = admin.post(f"/api/drawings/{drawing['id']}/convert", json={"parts": [
        {"key": drawing["parts"][0]["key"], "new_floor": {"name": "1 этаж"}}]})
    heavy = r.json()["job_id"]
    with transaction() as s:
        light = tasks.enqueue(s, "system.purge_journal")
    log = tmp_path / "worker.log"
    # «путаница» после ~40 с перевода ест память без предела (до 12 ГБ за минуту): отмена
    # приходит за секунды, а предел не даст медленному раннеру задохнуться
    env = {**os.environ, "APP_TASK_MEMORY_MB": "1024"}
    with log.open("wb") as out:
        worker = subprocess.Popen([sys.executable, "-m", "app", "worker"], cwd=ROOT / "server",
                                  stdout=out, stderr=subprocess.STDOUT, env=env)
        try:
            deadline = time.monotonic() + 60
            while (admin.get(f"/api/system/tasks/{light}").json()["status"] != "done"
                   and time.monotonic() < deadline and worker.poll() is None):
                time.sleep(0.5)
            state = {j: admin.get(f"/api/system/tasks/{j}").json()["status"]
                     for j in (heavy, light)}
            assert state == {heavy: "running", light: "done"}, (
                f"{state}\n" + log.read_text(encoding="utf-8", errors="replace")[-3000:])

            r = admin.post(f"/api/system/tasks/{heavy}/cancel")
            assert r.status_code == 200, r.text
            deadline = time.monotonic() + 20
            while (admin.get(f"/api/system/tasks/{heavy}").json()["status"] != "cancelled"
                   and time.monotonic() < deadline):
                time.sleep(0.5)
            assert admin.get(f"/api/system/tasks/{heavy}").json()["status"] == "cancelled"
        finally:
            worker.terminate()
            worker.wait(timeout=30)
    after = admin.get(f"/api/drawings/{drawing['id']}").json()
    assert after["status"] == "ready" and after["error"], after
    assert admin.get(f"/api/buildings/{b['id']}").json()["floors"] == []


def _dwg(tmp_path: Path) -> Path:
    dwg = tmp_path / "план.dwg"
    dwg.write_bytes(b"AC1032" + b"\0" * 128)
    return dwg


def test_r017_dwg2dxf_gets_no_secrets(monkeypatch, tmp_path) -> None:
    """R-017: LibreDWG разбирает чужие файлы — в его окружении нет пароля базы и прочих
    настроек приложения; в Linux его память и время ограничены."""
    seen: dict = {}  # type: ignore[type-arg]

    def run(args, **kwargs):  # type: ignore[no-untyped-def]
        seen.update(kwargs)
        Path(args[args.index("-o") + 1]).write_text("0\nEOF\n")
        return subprocess.CompletedProcess(args, 0, b"", b"")

    tool = tmp_path / "dwg2dxf"
    tool.write_text("")
    monkeypatch.setenv("APP_DWG2DXF", str(tool))
    monkeypatch.setenv("APP_SECRET_PROBE", "пароль-базы")
    monkeypatch.setattr(read.subprocess, "run", run)
    read.to_dxf(_dwg(tmp_path), tmp_path)
    env = seen["env"]
    assert not [k for k in env if k.startswith("APP_")], sorted(env)
    assert all("пароль-базы" not in v for v in env.values())
    if sys.platform != "win32":
        assert seen.get("preexec_fn") is not None


@pytest.mark.skipif(sys.platform == "win32", reason="ограничения процесса (setrlimit) — Linux")
def test_r017_dwg2dxf_is_limited_in_memory_and_time(monkeypatch, tmp_path) -> None:
    tool = tmp_path / "dwg2dxf"
    tool.write_text('#!/bin/sh\n# -y -o ВЫХОД ВХОД\n'
                    '{ ulimit -v; ulimit -t; env; } > "$3"\n')
    tool.chmod(0o755)
    monkeypatch.setenv("APP_DWG2DXF", str(tool))
    out = read.to_dxf(_dwg(tmp_path), tmp_path).read_text().splitlines()
    memory, cpu = out[0], out[1]
    assert memory != "unlimited" and cpu != "unlimited", out[:2]
    assert not [line for line in out[2:] if line.startswith("APP_")]


# ---------------------------------------------------------------- масштаб, слои, тяжёлые части


def sheet_dxf(dimlfac: float = 500, units: int = 4) -> bytes:
    """Лист 1:500 в миллиметрах бумаги: три плана 120 × 80 (60 × 40 м здания) в 20 (10 м)
    друг от друга, стены 0,6 (300 мм), перегородка 0,24 (120 мм). Размеры показывают метры
    здания — у всех, кроме двух (выноска узла), DIMLFAC = dimlfac. units — $INSUNITS."""
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = units
    msp = doc.modelspace()
    doc.layers.add("Стены")

    def box(x0: float, y0: float, x1: float, y1: float) -> None:
        msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True,
                           dxfattribs={"layer": "Стены"})

    for i in range(3):
        ox = i * 140
        box(ox, 0, ox + 120, 80)
        box(ox + 0.6, 0.6, ox + 60, 79.4)
        box(ox + 60.24, 0.6, ox + 119.4, 79.4)
        msp.add_linear_dim(base=(ox, -10), p1=(ox, 0), p2=(ox + 120, 0),
                           override={"dimlfac": dimlfac}).render()
        msp.add_linear_dim(base=(ox - 10, 0), p1=(ox, 0), p2=(ox, 80), angle=90,
                           override={"dimlfac": dimlfac}).render()
    for y in (90, 100):
        msp.add_linear_dim(base=(0, y), p1=(0, 80), p2=(10, 80)).render()
    out = io.StringIO()
    doc.write(out)
    return out.getvalue().encode()


def test_r057_the_sheet_scale_comes_from_the_dimensions(tmp_path) -> None:
    """Лист 1:500 в миллиметрах бумаги: масштаб — по DIMLFAC большинства размеров, части —
    в метрах здания, каждый план отдельно; до исправления — одна часть меньше метра (R-057)."""
    path = tmp_path / "лист.dxf"
    path.write_bytes(sheet_dxf())
    drawing = read.load(path)
    assert (drawing.scale, drawing.scale_by) == (500, "dimensions")
    found = parts.split(drawing)
    sizes = [(round(p.bbox[2] - p.bbox[0]), round(p.bbox[3] - p.bbox[1])) for p in found]
    assert sizes == [(60000, 40000)] * 3
    result = convert.convert(drawing, found[0].bbox)
    assert sorted({w.thickness for w in result.plan.walls}) == [120, 300]
    assert result.stats["rooms"] == 2


def test_r057_dimensions_in_other_units_do_not_scale_the_drawing(tmp_path) -> None:
    """Чертёж в метрах, размеры показывают миллиметры (DIMLFAC = 1000): это единицы
    подписи, а не масштаб листа — здание остаётся 60 × 40 м."""
    path = tmp_path / "метры.dxf"
    path.write_bytes(sheet_dxf(dimlfac=1000, units=6))
    drawing = read.load(path)
    assert (drawing.scale, drawing.scale_by) == (1, "units")
    assert round(parts.split(drawing)[0].bbox[2]) == 120_000


def test_r057_the_admin_sets_the_scale_and_the_drawing_is_analyzed_again(admin) -> None:
    """Масштаба на листе нет (1:100 без размеров): всё сливается в одну часть меньше метра, и
    система предупреждает. Администратор задаёт 1:100 — чертёж разбирается заново, части — в
    метрах здания, перевод даёт план (R-057)."""
    b = admin.post("/api/buildings", json={"name": "Корпус"}).json()
    d = upload(admin, b["id"], sample_dxf(sheet=100))
    assert d["scale"] is None
    assert (d["sheet"]["scale"], d["sheet"]["by"], d["sheet"]["small"]) == (1, "units", True)

    r = admin.post(f"/api/drawings/{d['id']}/scale", json={"scale": 100})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "analyzing"
    while tasks.run_one():
        pass
    full = admin.get(f"/api/drawings/{d['id']}").json()
    assert full["scale"] == 100
    assert (full["sheet"]["scale"], full["sheet"]["by"], full["sheet"]["small"]) == (
        100, "admin", False)
    assert [(p["name"], p["width"], p["floor_like"]) for p in full["parts"]] == [
        ("План 1-го этажа", 9000, True), ("План 2-го этажа", 9000, True)]

    job = admin.post(f"/api/drawings/{d['id']}/convert", json={"parts": [
        {"key": full["parts"][0]["key"], "new_floor": {"name": "1 этаж"}}]}).json()["job_id"]
    while tasks.run_one():
        pass
    assert admin.get(f"/api/system/tasks/{job}").json()["status"] == "done"
    floor = admin.get(f"/api/buildings/{b['id']}").json()["floors"][0]
    plan = admin.get(f"/api/floors/{floor['id']}/plan").json()
    assert sorted(r["number"] for r in plan["rooms"]) == ["101", "102"]

    # «по чертежу» — снова сам: масштаба на листе нет, 1:1
    r = admin.post(f"/api/drawings/{d['id']}/scale", json={"scale": None})
    assert r.status_code == 200, r.text
    while tasks.run_one():
        pass
    again = admin.get(f"/api/drawings/{d['id']}").json()
    assert (again["scale"], again["sheet"]["by"], again["results"]) == (None, "units", {})


@pytest.mark.parametrize(("layer", "expected"), [
    ("Блоки", "other"),  # функциональные блоки — зоны, не стены
    ("Функциональные блоки", "other"),
    ("Настенные светильники", "other"),  # «стен» — не начало слова
    ("Cтены", "wall"),  # латинская C
    ("Стены", "wall"),
    ("Стены наружные", "wall"),
    ("A-WALL", "wall"),
    ("Wände", "wall"),
    ("Газобетон", "wall"),
    ("Газоблоки", "wall"),
    ("Achsen", "ignore"),
    ("Axes", "ignore"),
    ("Bemaßung", "ignore"),
    ("Окна", "window"),
    ("Двери", "door"),
])
def test_r058_layer_role_by_whole_words(layer: str, expected: str) -> None:
    assert layers.role(layer) == expected


@pytest.mark.parametrize("names", [
    {"walls": "0", "partitions": "0", "zones": "Функциональные блоки"},
    {"partitions": "Cтены"},
    {"walls": "0", "partitions": "0", "stray": "Стены"},
], ids=["zone-blocks", "latin-c", "stray-wall"])
def test_r058_walls_are_not_lost_to_the_layer_names(tmp_path, names: dict[str, str]) -> None:
    """Стены на слое «0», а слой с «блок» в названии — зоны со штриховками и значками;
    перегородки на «Cтены» с латинской C; на слое стен — только обрывок под планом. До
    исправления стен почти нет или теряются перегородки (R-058)."""
    path = tmp_path / "слои.dxf"
    path.write_bytes(sample_dxf(**names))  # type: ignore[arg-type]
    drawing = read.load(path)
    result = convert.convert(drawing, parts.split(drawing)[0].bbox)
    assert {r.number for r in result.plan.rooms} == {"101", "102"}
    assert sorted({w.thickness for w in result.plan.walls}) == [120, 300]
    assert sorted(o.kind for o in result.plan.openings) == ["door", "window"]


def test_r059_a_part_with_200k_short_lines_on_layer_0_converts_in_seconds(tmp_path) -> None:
    """Стены на своих слоях, а на «0» в помещении — 200 000 коротких штрихов (штриховки,
    текст линиями). До исправления все они — кандидаты в окна: перевод части — минуты и
    гигабайты; должно — секунды, и план тот же (R-059)."""
    import random

    path = tmp_path / "штрихи.dxf"
    path.write_bytes(sample_dxf())
    drawing = read.load(path)
    bbox = parts.split(drawing)[0].bbox
    rnd = random.Random(59)
    for i in range(200_000):
        x, y = rnd.uniform(600, 4600), rnd.uniform(600, 5400)
        drawing.segs.append(read.Seg("0", (x, y), (x + rnd.uniform(-40, 40), y + 40),
                                     10**6 + i))
    start = time.monotonic()
    result = convert.convert(drawing, bbox)
    elapsed = time.monotonic() - start
    assert elapsed < 30, elapsed
    assert {r.number for r in result.plan.rooms} == {"101", "102"}
    assert sorted(o.kind for o in result.plan.openings) == ["door", "window"]


def test_r059_the_progress_moves_inside_a_part(admin, monkeypatch) -> None:
    """Ход перевода меняется и внутри части — по этапам, а не стоит на одном делении (R-059)."""
    seen: list[tuple[int, int | None, str | None]] = []
    original = tasks.Progress.__call__

    def record(self, done, total=None, message=None):  # type: ignore[no-untyped-def]
        seen.append((done, total, message))
        original(self, done, total, message)

    b = admin.post("/api/buildings", json={"name": "Корпус"}).json()
    d = upload(admin, b["id"], sample_dxf())
    monkeypatch.setattr(tasks.Progress, "__call__", record)
    admin.post(f"/api/drawings/{d['id']}/convert", json={"parts": [
        {"key": d["parts"][0]["key"], "new_floor": {"name": "1 этаж"}}]})
    while tasks.run_one():
        pass
    inside = [(done, message) for done, _, message in seen
              if message and message.startswith("Перевод")]
    assert len({done for done, _ in inside}) >= 4, inside
    assert len({message for _, message in inside}) >= 4, inside


def test_r060_dwg2dxf_comes_from_the_environment_not_from_legacy(monkeypatch, tmp_path) -> None:
    """Стенд разработки не ссылается на несуществующий legacy/.tools: dwg2dxf — из
    APP_DWG2DXF или PATH (R-060)."""
    import json
    import shutil

    launch = json.loads((ROOT / ".claude/launch.json").read_text(encoding="utf-8"))
    for c in launch["configurations"]:
        if c["name"] in ("server", "worker"):
            assert "legacy/" not in " ".join(c.get("runtimeArgs", [])), c["name"]
    tool = tmp_path / ("dwg2dxf.exe" if sys.platform == "win32" else "dwg2dxf")
    tool.write_text("")
    tool.chmod(0o755)
    monkeypatch.delenv("APP_DWG2DXF", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    found = read.dwg2dxf()
    assert found is not None and found == shutil.which("dwg2dxf")
    assert Path(found).resolve() == tool.resolve()
