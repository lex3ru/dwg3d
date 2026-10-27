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
from app.modules.building.drawing import convert, parts, read
from tests.test_inventory import document, kinds, post
from tests.test_planning import changes

ROOT = Path(__file__).resolve().parents[2]
# конвертер DWG на машине разработчика (в образе — свой, deploy/Dockerfile)
if (ROOT / "legacy/.tools/libredwg/bin/dwg2dxf").exists():
    os.environ.setdefault("APP_DWG2DXF", str(ROOT / "legacy/.tools/libredwg/bin/dwg2dxf"))


def sample_dxf(partition: float | None = 5000) -> bytes:
    """Два этажа рядом на одном листе: коробка 9 × 6 м двойными линиями стен (300 мм),
    перегородка (120 мм) с дверным проёмом, окно в наружной стене, подписи помещений.
    partition — x перегородки; None — перегородку снесли, обе подписи в одном помещении."""
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for name in ("Стены", "Перегородки", "Окна", "Текст"):
        doc.layers.add(name)

    def floor(ox: float, title: str, n1: str, n2: str) -> None:
        def poly(points, layer):  # type: ignore[no-untyped-def]
            msp.add_lwpolyline([(ox + x, y) for x, y in points], close=True,
                               dxfattribs={"layer": layer})
        # наружные стены: внешний и внутренний контур, в нижней стене — проём под окно
        poly([(0, 0), (3000, 0), (3000, 300), (300, 300), (300, 5700), (8700, 5700),
              (8700, 300), (4500, 300), (4500, 0), (9000, 0), (9000, 6000), (0, 6000)], "Стены")
        for x0, x1 in ((3000, 4500),):
            msp.add_line((ox + x0, 100), (ox + x1, 100), dxfattribs={"layer": "Окна"})
            msp.add_line((ox + x0, 200), (ox + x1, 200), dxfattribs={"layer": "Окна"})
        # перегородка (по умолчанию x = 5000) с дверью 900 мм (просвет y 2000…2900)
        if partition is not None:
            a, b = partition, partition + 120
            poly([(a, 300), (b, 300), (b, 2000), (a, 2000)], "Перегородки")
            poly([(a, 2900), (b, 2900), (b, 5700), (a, 5700)], "Перегородки")
        msp.add_text(n1, height=300, dxfattribs={"layer": "0", "insert": (ox + 2500, 3000)})
        msp.add_text("Регистратура", height=250,
                     dxfattribs={"layer": "0", "insert": (ox + 1500, 2500)})
        msp.add_text(n2, height=300, dxfattribs={"layer": "0", "insert": (ox + 7000, 3000)})
        msp.add_text(title, height=500, dxfattribs={"layer": "Текст",
                                                    "insert": (ox + 2000, 6800)})

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
