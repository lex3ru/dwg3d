"""Перевод чертежа в план (5.1.3, С1)."""

import io
import os
import uuid
from pathlib import Path

import ezdxf
import pytest

from app.core import tasks
from app.modules.building.drawing import convert, parts, read

ROOT = Path(__file__).resolve().parents[2]
# конвертер DWG на машине разработчика (в образе — свой, deploy/Dockerfile)
if (ROOT / "legacy/.tools/libredwg/bin/dwg2dxf").exists():
    os.environ.setdefault("APP_DWG2DXF", str(ROOT / "legacy/.tools/libredwg/bin/dwg2dxf"))


def sample_dxf() -> bytes:
    """Два этажа рядом на одном листе: коробка 9 × 6 м двойными линиями стен (300 мм),
    перегородка (120 мм) с дверным проёмом, окно в наружной стене, подписи помещений."""
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
        # перегородка x = 5000 с дверью 900 мм (просвет y 2000…2900)
        poly([(5000, 300), (5120, 300), (5120, 2000), (5000, 2000)], "Перегородки")
        poly([(5000, 2900), (5120, 2900), (5120, 5700), (5000, 5700)], "Перегородки")
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
