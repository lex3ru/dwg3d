"""Безопасность (8.4 п. 3, 10.3): «просмотр» не получает стоимость, инвентарные номера и
проекты ни на экране, ни в ответах сервера, ни в выгрузках. Обходятся все адреса GET;
ответы (и таблицы Excel внутри) проверяются на номера и цены, которые завёл администратор."""

import io
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app import main
from app.core.config import config
from app.core.db import transaction
from app.modules.access import api as access
from tests.conftest import login, make_client
from tests.test_building import building_with_floor, save, two_rooms
from tests.test_catalog import glb
from tests.test_drawings import sample_dxf, upload
from tests.test_events import viewer
from tests.test_inventory import document, post, setup
from tests.test_journal import PDF
from tests.test_transfer import PNG

NUMBERS = ["ТАЙНА-0001", "ТАЙНА-0002"]
PRICES = ["14537", "14 537", "14 537", "523.5", "523,5", "777331"]


def text_of(content: bytes) -> str:
    """Тело ответа как текст; у xlsx — все листы и строки."""
    if content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            return "\n".join(
                z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith(".xml")
            )
    return content.decode("utf-8", "replace")


def test_viewer_gets_no_cost_numbers_or_projects_anywhere(pdf, admin, app) -> None:
    building, rooms, wh, k = setup(admin)
    t = k["монитор"]
    assert (
        admin.patch(
            f"/api/catalog/types/{t['id']}", json={"version": t["version"], "price": 777331}
        ).status_code
        == 200
    )
    got = document(
        admin,
        "receipt",
        {"to_place": rooms["214"]},
        [{"type_id": t["id"], "qty": 1, "price": 14537, "number": n} for n in NUMBERS]
        + [{"type_id": k["перчатки"]["id"], "qty": 10, "price": 523.5}],
    )
    assert post(admin, got).status_code == 200, post(admin, got).text
    units = [
        u["id"]
        for line in admin.get(f"/api/inventory/documents/{got['id']}").json()["lines"]
        for u in line["created_units"]
    ]
    unit = admin.get(f"/api/inventory/units/{units[0]}").json()
    assert unit["number"] == NUMBERS[0]
    floor = unit["place"]["floor_id"]
    project = admin.post(
        "/api/projects", json={"building_id": building["id"], "name": "Тайный проект"}
    ).json()
    count = admin.post("/api/inventory/counts", json={"floor_id": floor}).json()

    with transaction() as s:
        access.create(
            s,
            None,
            login_name="zav",
            full_name="Заведующий З. З.",
            role="viewer",
            building_ids=[building["id"]],
            password="Viewer-pass-123",
        )
    with make_client(app) as viewer:
        login(viewer, "zav", "Viewer-pass-123")
        viewer.post(
            "/api/auth/password", json={"current": "Viewer-pass-123", "new": "Viewer-pass-456"}
        )
        b, f, u = building["id"], floor, units[0]
        reachable = [
            "/api/buildings",
            f"/api/buildings/{b}",
            f"/api/floors/{f}/plan",
            f"/api/floors/{f}/items",
            "/api/catalog",
            f"/api/catalog/types/{t['id']}",
            "/api/inventory/places",
            f"/api/inventory/place?key={rooms['214']}",
            "/api/inventory/units",
            "/api/inventory/units/export.xlsx",
            f"/api/inventory/units/{u}",
            f"/api/inventory/units/{units[-1]}",
            f"/api/inventory/balances?place={rooms['214']}",
            f"/api/link/floors/{f}",
            f"/api/link/units/{u}",
            f"/api/q/{unit['label_code']}",
            "/api/search?q=Монитор",
            "/api/search?q=ТАЙНА",
            f"/api/floors/{f}/export.pdf",
        ]
        closed = [
            "/api/inventory/cost",
            "/api/inventory/cost.xlsx",
            "/api/inventory/documents",
            f"/api/inventory/documents/{got['id']}",
            f"/api/inventory/documents/{got['id']}/print.pdf",
            "/api/inventory/balances/history",
            "/api/inventory/counts",
            f"/api/inventory/counts/{count['id']}",
            f"/api/inventory/counts/{count['id']}/act.pdf",
            "/api/catalog/export.xlsx",
            "/api/projects",
            f"/api/projects/{project['id']}",
            f"/api/projects/{project['id']}/specification",
            f"/api/projects/{project['id']}/export.xlsx",
            "/api/reports",
            "/api/reports/registry.xlsx",
            "/api/reports/cost.xlsx",
            f"/api/home?building_id={b}",
            f"/api/home/plan?building_id={b}",
            "/api/journal",
            "/api/users",
            "/api/share-links",
            "/api/system/settings",
        ]
        leaks = []
        for url in reachable:
            r = viewer.get(url)
            assert r.status_code == 200, f"{url}: {r.status_code} {r.text[:200]}"
            body = text_of(r.content)
            leaks += [f"{url}: «{s}»" for s in [*NUMBERS, *PRICES] if s in body]
        assert not leaks, "просмотру видно:\n" + "\n".join(leaks)
        for url in closed:
            assert viewer.get(url).status_code in (403, 404), url
        # поиск по номеру ничего не находит — номера просмотру не известны
        assert not viewer.get("/api/search", params={"q": NUMBERS[0]}).json().get("items")


def test_r015_viewer_cannot_learn_cost_from_order(admin, app) -> None:
    """Порядок реестра не раскрывает «просмотру» стоимость (2.2 — «в любом виде»): по цене
    он сортирует так же, как по наименованию, а при равных наименованиях — не по
    инвентарному номеру, которого тоже не видит (R-015). То же — в выгрузке реестра."""
    building, rooms, _, k = setup(admin)
    lines = [{"type_id": k["монитор"]["id"], "qty": 1, "price": p}
             for p in (300, 100, 800, 500, 200, 700, 400, 600)]
    lines.insert(3, {"type_id": k["экг"]["id"], "qty": 1, "price": 1000})
    lines.append({"type_id": k["экг"]["id"], "qty": 1, "price": 1})
    got = document(admin, "receipt", {"to_place": rooms["214"]}, lines)
    assert post(admin, got).status_code == 200
    with viewer(admin, app, building["id"]) as (v, _):

        def order(sort: str) -> list[tuple[str, str]]:
            r = v.get("/api/inventory/units", params={"sort": sort})
            return [(u["type_name"], u["id"]) for u in r.json()["items"]]

        def rows(sort: str) -> list[tuple]:  # type: ignore[type-arg]
            r = v.get("/api/inventory/units/export.xlsx", params={"sort": sort})
            return list(load_workbook(io.BytesIO(r.content)).active.iter_rows(values_only=True))

        assert len(order("title")) == 10
        assert order("price") == order("title")
        assert order("-price") == order("-title")
        # при равных наименованиях — по ключу записи: номер «просмотр» тоже не видит
        assert order("title") == sorted(order("title"))
        assert rows("-price") == rows("-title")


def test_r018_api_schema_is_for_admin_only(admin, app, client) -> None:
    """Схема API (120 адресов) и Swagger — только администратору (R-018 п. 2)."""
    for url in ("/api/docs", "/api/openapi.json"):
        assert client.get(url).status_code == 401, url
        assert admin.get(url).status_code == 200, url
    with viewer(admin, app) as (v, _):
        for url in ("/api/docs", "/api/openapi.json"):
            assert v.get(url).status_code == 403, url
    # Swagger грузит скрипты с CDN — у страницы своя политика, у интерфейса её нет
    assert "cdn.jsdelivr.net" in admin.get("/api/docs").headers["content-security-policy"]
    assert "/api/docs" not in admin.get("/api/openapi.json").json()["paths"]


def test_r018_viewer_gets_only_files_of_what_is_visible(admin, app) -> None:
    """Файл по ключу «просмотр» получает, только если видит то, к чему файл относится:
    подложку и чертёж своего здания, фото своей единицы, 3D-модель каталога. Файлы
    документов учёта и чужих зданий закрыты, даже если ключ известен (R-018 п. 3)."""
    building, floor = building_with_floor(admin)
    other, other_floor = building_with_floor(admin)

    def underlay(floor_id: str, data: bytes) -> str:
        f = admin.post("/api/files", files={"file": ("план.pdf", io.BytesIO(data))}).json()
        plan = {**two_rooms(), "underlay": {"file_id": str(f["id"])}}
        r = save(admin, floor_id, plan, 1)
        assert r.status_code == 200, r.text
        return f["url"]

    mine, foreign = underlay(floor["id"], PDF), underlay(other_floor["id"], PDF + b"2")
    rooms = {r["number"]: r["id"] for r in admin.get(f"/api/floors/{floor['id']}/plan")
             .json()["plan"]["rooms"]}
    kind = admin.post("/api/catalog/types", json={"name": "Кушетка", "life_months": 60}).json()
    model = admin.post(f"/api/catalog/types/{kind['id']}/model3d",
                       files={"file": ("кушетка.glb", io.BytesIO(glb()))}).json()["model_url"]
    got = document(admin, "receipt", {"to_place": f"r:{rooms['214']}"},
                   [{"type_id": kind["id"], "qty": 1, "price": 18000}])
    scan = admin.post(f"/api/inventory/documents/{got['id']}/files",
                      files={"file": ("счёт.pdf", io.BytesIO(PDF + b"3"))})
    assert scan.status_code == 201, scan.text
    assert post(admin, got).status_code == 200
    unit = admin.get(f"/api/inventory/documents/{got['id']}").json()["lines"][0]
    photo = admin.post(f"/api/inventory/units/{unit['created_units'][0]['id']}/files",
                       params={"kind": "photo"}, files={"file": ("кушетка.png", PNG)})
    assert photo.status_code == 201, photo.text
    drawing = upload(admin, building["id"], sample_dxf())["file_url"]
    foreign_drawing = upload(admin, other["id"], sample_dxf(4000))["file_url"]
    doc_file = admin.get(f"/api/inventory/documents/{got['id']}").json()["files"][0]["url"]
    open_ = [mine, model, drawing, photo.json()["photo_url"]]
    closed = [foreign, foreign_drawing, doc_file]
    for url in open_ + closed:
        assert admin.get(url).status_code == 200, url
    with viewer(admin, app, building["id"]) as (v, _):
        assert [v.get(u).status_code for u in open_] == [200] * len(open_)
        assert [v.get(u).status_code for u in closed] == [403] * len(closed)


def test_r018_interface_page_allows_only_own_scripts(tmp_path, monkeypatch) -> None:
    """Страница интерфейса несёт Content-Security-Policy: скрипты — только свои, без
    встроенных и eval; чужие сайты не встраивают её в рамку (R-018 п. 1)."""
    (tmp_path / "index.html").write_text("<!doctype html><title>Планировка</title>")
    monkeypatch.setattr(config(), "static_dir", tmp_path)
    bare = FastAPI()
    main._mount_web(bare)
    with TestClient(bare) as c:
        for path in ("/", "/inventory/units"):
            header = c.get(path).headers.get("content-security-policy", "")
            policy = {d.split()[0]: d.split()[1:] for d in header.split(";") if d.strip()}
            assert policy.get("default-src") == ["'self'"], (path, header)
            assert "'self'" in policy.get("script-src", []), header
            assert not {"'unsafe-inline'", "'unsafe-eval'"} & set(policy["script-src"]), header
            assert policy.get("object-src") == ["'none'"], header
            assert policy.get("frame-ancestors") == ["'none'"], header
