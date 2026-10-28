"""Каталог (5.2; С4, С5): слои, наборы, типы, модели, значения, назначения, Excel, 3D."""

import io
import json
import struct

import pytest

from app.core.db import transaction
from app.modules.catalog.module import seed
from tests.conftest import login, make_client
from tests.test_inventory import document, kinds, post


def seeded(admin) -> dict:  # type: ignore[no-untyped-def]
    with transaction() as s:
        assert seed(s)
    with transaction() as s:
        assert seed(s) is None  # второй раз — ничего: правки администратора не трогаются
    return admin.get("/api/catalog").json()


def test_base_catalog_is_loaded_once(admin) -> None:
    tree = seeded(admin)
    assert [x["name"] for x in tree["layers"]] == [
        "Мебель",
        "Оборудование",
        "Видеонаблюдение",
        "Освещение",
    ]
    assert len(tree["sets"]) == 6 and len(tree["types"]) == 109 and len(tree["purposes"]) == 23
    camera = next(t for t in tree["types"] if t["name"] == "Камера купольная")
    full = admin.get(f"/api/catalog/types/{camera['id']}").json()
    assert full["mount"] == "ceiling" and len(full["models"]) == 2
    chars = {c["id"]: c["name"] for c in full["characteristics"]}
    values = {chars[k]: v for k, v in full["models"][0]["values"].items() if v is not None}
    assert values["Разрешение по горизонтали"] == 2688
    assert values["Угол обзора по горизонтали, макс."] == 103


def test_c4_new_type_with_characteristics_and_model(admin) -> None:
    tree = seeded(admin)
    equipment = next(x for x in tree["layers"] if x["name"] == "Оборудование")
    medical = next(x for x in tree["sets"] if x["name"] == "Медицинское изделие")
    r = admin.post(
        "/api/catalog/types",
        json={
            "name": "Аппарат УЗИ портативный",
            "layer_id": equipment["id"],
            "set_ids": [medical["id"]],
            "width": 400,
            "depth": 300,
            "height": 150,
            "mount": "floor",
            "accounting": "piece",
            "life_months": 84,
            "price": 950000,
        },
    )
    assert r.status_code == 201, r.text
    t = r.json()
    ru = admin.post(
        "/api/catalog/characteristics",
        json={
            "type_id": t["id"],
            "name": "Класс риска",
            "kind": "choice",
            "choices": ["1", "2а", "2б", "3"],
            "level": "type",
        },
    ).json()
    admin.post(
        "/api/catalog/characteristics",
        json={
            "type_id": t["id"],
            "name": "Дата калибровки датчика",
            "kind": "date",
            "level": "item",
        },
    )
    r = admin.put(f"/api/catalog/types/{t['id']}/values", json={"values": {ru["id"]: "2б"}})
    assert r.status_code == 200, r.text
    assert r.json()["values"][ru["id"]] == "2б"
    r = admin.put(f"/api/catalog/types/{t['id']}/values", json={"values": {ru["id"]: "4"}})
    assert r.status_code == 400 and "нет в списке" in r.json()["error"]["message"]
    t = admin.post(
        f"/api/catalog/types/{t['id']}/models",
        json={"manufacturer": "Mindray", "name": "M7", "price": 1250000},
    ).json()
    model = t["models"][0]
    reg = next(c for c in t["characteristics"] if c["name"] == "Регистрационное удостоверение")
    r = admin.put(
        f"/api/catalog/models/{model['id']}/values", json={"values": {reg["id"]: "РЗН 2020/1234"}}
    )
    assert r.json()["models"][0]["values"][reg["id"]] == "РЗН 2020/1234"
    # уровень «вещь» задаётся у инвентарной единицы, не у типа
    item = next(c for c in t["characteristics"] if c["name"] == "Дата калибровки датчика")
    r = admin.put(
        f"/api/catalog/types/{t['id']}/values", json={"values": {item["id"]: "01.01.2026"}}
    )
    assert r.status_code == 400


def test_c5_new_layer_with_types(admin) -> None:
    layer = admin.post("/api/catalog/layers", json={"name": "СКУД", "color": "#7B1FA2"}).json()
    for name in ("Считыватель", "Электрозамок"):
        r = admin.post(
            "/api/catalog/types",
            json={"name": name, "layer_id": layer["id"], "mount": "wall", "mount_height": 1200},
        )
        assert r.status_code == 201
    tree = admin.get("/api/catalog").json()
    assert tree["layers"][-1]["name"] == "СКУД" and tree["layers"][-1]["types"] == 2
    r = admin.delete(f"/api/catalog/layers/{layer['id']}")
    assert r.status_code == 409 and "скрыть" in r.json()["error"]["message"]
    assert (
        admin.patch(f"/api/catalog/layers/{layer['id']}", json={"visible": False}).json()["visible"]
        is False
    )
    r = admin.post("/api/catalog/layers", json={"name": "скуд"})
    assert r.status_code == 409


def test_viewer_sees_no_prices_and_changes_nothing(admin, app) -> None:
    seeded(admin)
    admin.post(
        "/api/users",
        json={"login": "viewer1", "full_name": "В", "role": "viewer", "password": "Temporary-1"},
    )
    with make_client(app) as viewer:
        login(viewer, "viewer1", "Temporary-1")
        viewer.post("/api/auth/password", json={"current": "Temporary-1", "new": "Viewer-pass-1"})
        tree = viewer.get("/api/catalog").json()
        assert all("price" not in t for t in tree["types"])
        full = viewer.get(f"/api/catalog/types/{tree['types'][0]['id']}").json()
        assert "price" not in full and all("price" not in m for m in full["models"])
        assert viewer.post("/api/catalog/layers", json={"name": "Х"}).status_code == 403
        assert viewer.get("/api/catalog/export.xlsx").status_code == 403


def test_excel_round_trip_and_all_or_nothing(admin) -> None:
    seeded(admin)
    data = admin.get("/api/catalog/export.xlsx").content
    r = admin.post("/api/catalog/import", files={"file": ("каталог.xlsx", io.BytesIO(data))})
    assert r.json() == {"created": {}, "updated": {}, "errors": [], "ok": True, "applied": False}

    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data))
    wb["Типы"].append(["Стойка капельничная", "Мебель", None, 500, 500, 1800, "на пол"])
    wb["Типы"].append(["Тумба", "Нет такого слоя"])
    out = io.BytesIO()
    wb.save(out)
    r = admin.post(
        "/api/catalog/import",
        params={"apply": True},
        files={"file": ("каталог.xlsx", io.BytesIO(out.getvalue()))},
    ).json()
    assert r["applied"] is False and r["errors"][0]["sheet"] == "Типы"
    assert "Нет такого слоя" in r["errors"][0]["message"]
    names = {t["name"] for t in admin.get("/api/catalog").json()["types"]}
    assert "Стойка капельничная" not in names  # ошибка в одной строке — не загружено ничего

    wb["Типы"].delete_rows(wb["Типы"].max_row)
    out = io.BytesIO()
    wb.save(out)
    r = admin.post(
        "/api/catalog/import",
        params={"apply": True},
        files={"file": ("каталог.xlsx", io.BytesIO(out.getvalue()))},
    ).json()
    assert r["applied"] is True and r["created"] == {"Типы": ["Стойка капельничная"]}


def glb(size=(1.2, 0.8, 0.6)) -> bytes:  # type: ignore[no-untyped-def]
    doc = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "scale": [1, 1, 1], "translation": [5, 0, 0]}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "accessors": [
            {"componentType": 5126, "count": 2, "type": "VEC3", "min": [0, 0, 0], "max": list(size)}
        ],
    }
    text = json.dumps(doc).encode()
    text += b" " * ((4 - len(text) % 4) % 4)
    body = struct.pack("<I4s", len(text), b"JSON") + text
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


def test_3d_model_is_measured(admin) -> None:
    t = admin.post(
        "/api/catalog/types", json={"name": "Кушетка", "width": 1900, "depth": 650, "height": 700}
    ).json()
    r = admin.post(
        f"/api/catalog/types/{t['id']}/model3d",
        files={"file": ("кушетка.glb", io.BytesIO(glb((1.9, 0.7, 0.65))))},
    )
    assert r.status_code == 200, r.text
    assert r.json()["model_size"] == [1.9, 0.7, 0.65] and r.json()["model_url"]
    r = admin.post(
        f"/api/catalog/types/{t['id']}/model3d",
        files={"file": ("кушетка.glb", io.BytesIO(b"not a glb at all, no"))},
    )
    assert r.status_code == 400


def packed(text: bytes) -> bytes:
    """GLB с любым описанием сцены — и испорченным тоже."""
    text += b" " * ((4 - len(text) % 4) % 4)
    body = struct.pack("<I4s", len(text), b"JSON") + text
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


def scene(nodes: list[dict], **extra: object) -> bytes:  # type: ignore[type-arg]
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": nodes,
           "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
           "accessors": [{"componentType": 5126, "count": 2, "type": "VEC3",
                          "min": [0, 0, 0], "max": [1, 1, 1]}]}
    return packed(json.dumps({**doc, **extra}).encode())


BROKEN_GLB = {
    "bad-json": packed(b'{"nodes": [oops'),  # кривой JSON
    "node-index": scene([{"children": [7]}]),  # узел вне списка
    "mesh-index": scene([{"mesh": 5}]),  # сетка вне списка
    "accessor-index": scene([{"mesh": 0}], accessors=[]),  # координаты вне списка
    "cycle": scene([{"children": [1]}, {"children": [0], "mesh": 0}]),  # цикл в children
    # у узла glTF 2.0 один родитель; здесь каждый ссылается на следующий дважды — путей
    # обхода 2^12, а при 25 узлах — 2^24, и запрос не отвечает (artifacts/stage4-glb-fuzz.txt)
    "shared-child": scene([{"children": [i + 1, i + 1]} for i in range(12)] + [{"mesh": 0}]),
    "deep-chain": scene([{"children": [i + 1]} for i in range(2999)] + [{"mesh": 0}]),
}


@pytest.mark.parametrize("data", BROKEN_GLB.values(), ids=BROKEN_GLB.keys())
def test_r025_broken_glb_is_refused_with_a_reason(admin, data: bytes) -> None:
    """R-025: испорченная модель — «GLB повреждён», а не 500 и не зависание."""
    t = admin.post("/api/catalog/types", json={"name": "Кушетка"}).json()
    r = admin.post(f"/api/catalog/types/{t['id']}/model3d",
                   files={"file": ("кушетка.glb", io.BytesIO(data))})
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "bad_glb"


def test_purposes(admin) -> None:
    p = admin.post(
        "/api/catalog/purposes", json={"name": "Кабинет врача", "surface": 800, "norm": 500}
    ).json()
    assert admin.post("/api/catalog/purposes", json={"name": "кабинет врача"}).status_code == 409
    r = admin.patch(f"/api/catalog/purposes/{p['id']}", json={"version": p["version"], "norm": 400})
    assert r.json()["norm"] == 400
    admin.post(f"/api/catalog/purposes/{p['id']}/archive")
    assert admin.get("/api/catalog/purposes").json()["items"] == []


def test_base_catalog_comes_with_3d_models(admin) -> None:  # type: ignore[no-untyped-def]
    """5.2.6: типы базового каталога на плане получают 3D-модели из комплекта — один раз;
    модель, которую администратор убрал или заменил, не возвращается."""
    from app.modules.catalog.module import seed_models

    seeded(admin)
    with transaction() as s:
        assert seed_models(s) == "3D-модели каталога: 80"
    tree = admin.get("/api/catalog").json()
    placeable = [t for t in tree["types"] if t["layer_id"] and t["mount"] != "none"]
    assert all(t["model_url"] for t in placeable)
    couch = next(t for t in placeable if t["name"] == "Кушетка смотровая")
    assert couch["model_transform"]["fit"] is True
    assert "CC0" in couch["model_credit"]
    chair = next(t for t in placeable if t["name"] == "Кресло-коляска")
    assert "CC-BY 3.0" in chair["model_credit"] and "poly.pizza" in chair["model_credit"]

    assert admin.delete(f"/api/catalog/types/{couch['id']}/model3d").status_code == 200
    with transaction() as s:
        assert seed_models(s) is None
    assert admin.get(f"/api/catalog/types/{couch['id']}").json()["model_url"] is None


def with_records(admin):  # type: ignore[no-untyped-def]
    """Типы учёта; по монитору (поштучно) — две единицы, по перчаткам (количеством) — остаток."""
    k = kinds(admin)
    wh = admin.post("/api/inventory/warehouses", json={"name": "Основной"}).json()
    receipt = document(
        admin,
        "receipt",
        {"to_place": wh["key"]},
        [
            {"type_id": k["монитор"]["id"], "qty": 2, "price": 14500},
            {"type_id": k["перчатки"]["id"], "qty": 5, "price": 520},
        ],
    )
    assert post(admin, receipt).status_code == 200
    return k


def accounting_of(admin, t) -> str:  # type: ignore[no-untyped-def]
    return admin.get(f"/api/catalog/types/{t['id']}").json()["accounting"]


def test_r024_accounting_kind_stays_while_the_type_has_records(admin) -> None:
    """Вид учёта типа, по которому есть единицы или движения остатков, не меняется: поштучные
    единицы остались бы у количественного типа, а остаток — у поштучного (5.2.2, R-024)."""
    k = with_records(admin)

    def change(t, **values):  # type: ignore[no-untyped-def]
        version = admin.get(f"/api/catalog/types/{t['id']}").json()["version"]
        return admin.patch(f"/api/catalog/types/{t['id']}", json={**values, "version": version})

    for t, other in ((k["монитор"], "quantity"), (k["перчатки"], "piece")):
        r = change(t, accounting=other)
        assert r.status_code == 409 and r.json()["error"]["code"] == "accounting_in_use", r.text
        assert accounting_of(admin, t) == t["accounting"]
    # тот же вид учёта вместе с другой правкой — сохраняется
    r = change(k["монитор"], accounting="piece", life_months=72)
    assert r.status_code == 200 and r.json()["life_months"] == 72, r.text
    # по типу учёта нет — вид учёта меняется
    r = change(k["экг"], accounting="quantity")
    assert r.status_code == 200 and r.json()["accounting"] == "quantity", r.text


def test_r024_catalog_import_keeps_accounting_kind(admin) -> None:
    """Загрузка каталога тоже не меняет вид учёта типа, по которому есть учёт; пустой «Вид
    учёта» у существующего типа — «не менять», а не «поштучно» (R-024)."""
    from openpyxl import load_workbook

    k = with_records(admin)
    data = admin.get("/api/catalog/export.xlsx").content

    def load(accounting: dict[str, str | None]) -> dict:  # type: ignore[type-arg]
        wb = load_workbook(io.BytesIO(data))
        ws = wb["Типы"]
        col = [c.value for c in ws[1]].index("Вид учёта") + 1
        for row in range(2, ws.max_row + 1):
            if ws.cell(row, 1).value in accounting:
                ws.cell(row, col).value = accounting[ws.cell(row, 1).value]
        out = io.BytesIO()
        wb.save(out)
        return admin.post(
            "/api/catalog/import",
            params={"apply": True},
            files={"file": ("каталог.xlsx", io.BytesIO(out.getvalue()))},
        ).json()

    r = load({k["монитор"]["name"]: "количеством"})
    assert r["applied"] is False and r["errors"][0]["sheet"] == "Типы", r
    assert "вид учёта" in r["errors"][0]["message"].lower(), r
    assert accounting_of(admin, k["монитор"]) == "piece"

    r = load({k["перчатки"]["name"]: None})
    assert r["applied"] is True and r["errors"] == [], r
    assert accounting_of(admin, k["перчатки"]) == "quantity"
