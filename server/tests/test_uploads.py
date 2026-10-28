"""Загрузки (7.3 п. 4, ADR-0012): тело без прав не читается (R-014), у каждого вида файла —
свой лимит из настроек, и он проверяется до приёма (R-040)."""

import asyncio
import io
import json
import uuid
from collections.abc import Iterator

import pytest

MB = 1024 * 1024
BOUNDARY = "upload-boundary-7f3a"
FORM = {"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"}

DXF = b"0\r\nSECTION\r\n2\r\nHEADER\r\n"
PDF = b"%PDF-1.4\n"
JPEG = b"\xff\xd8\xff\xe0"
XLSX = b"PK\x03\x04"
GLB = b"glTF\x02\x00\x00\x00"


def multipart(head: bytes, megabytes: int, pulled: list[int],
              fields: dict[str, str] | None = None) -> Iterator[bytes]:
    """Тело формы с полем `file` по мегабайту; pulled — сколько мегабайт сервер забрал."""
    for name, value in (fields or {}).items():
        yield (f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
               f"{value}\r\n").encode()
    yield (f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"file\"; "
           "filename=\"upload.bin\"\r\nContent-Type: application/octet-stream\r\n\r\n"
           ).encode() + head
    for _ in range(megabytes):
        pulled.append(1)
        yield b"\0" * MB
    yield f"\r\n--{BOUNDARY}--\r\n".encode()


ANY = str(uuid.uuid4())
UPLOADS = [
    "/api/files",
    f"/api/buildings/{ANY}/drawings",
    f"/api/catalog/types/{ANY}/model3d",
    "/api/catalog/import",
    f"/api/inventory/units/{ANY}/files",
    f"/api/inventory/documents/{ANY}/files",
    "/api/inventory/import",
    "/api/transfer/check",
]


@pytest.mark.parametrize("path", UPLOADS, ids=[p.replace(ANY, "id") for p in UPLOADS])
def test_r014_upload_without_login_is_refused_unread(client, path: str) -> None:
    """R-014: без входа сервер отвечает 401, не забрав тело: 20 МБ не ложатся на диск."""
    pulled: list[int] = []
    r = client.post(path, content=multipart(DXF, 20, pulled, {"building_id": ANY}), headers=FORM)
    assert r.status_code == 401, r.text
    assert len(pulled) <= 1, f"сервер забрал {len(pulled)} МБ тела до проверки входа"


def settings(admin, **values: int) -> None:  # type: ignore[no-untyped-def]
    version = admin.get("/api/system/settings").json()["version"]
    r = admin.patch("/api/system/settings", json={"version": version, "values": values})
    assert r.status_code == 200, r.text


def test_r040_size_limits_of_all_kinds_are_settings_with_tz_defaults(admin) -> None:
    """7.3 п. 4: чертёж — 100 МБ, подложка — 50, Excel — 10, 3D — 20, фото — 15, документ — 25;
    меняются в настройках. Пакет переноса здания в 7.3 нет — 2 ГБ."""
    items = {i["key"]: i["value"] for i in admin.get("/api/system/settings").json()["items"]}
    assert {k: items.get(k) for k in (
        "drawing_max_mb", "underlay_max_mb", "excel_max_mb", "model3d_max_mb", "photo_max_mb",
        "document_max_mb", "transfer_max_mb")} == {
        "drawing_max_mb": 100, "underlay_max_mb": 50, "excel_max_mb": 10, "model3d_max_mb": 20,
        "photo_max_mb": 15, "document_max_mb": 25, "transfer_max_mb": 2048}
    settings(admin, drawing_max_mb=300)
    version = admin.get("/api/system/settings").json()["version"]
    r = admin.patch("/api/system/settings",
                    json={"version": version, "values": {"drawing_max_mb": 301}})
    assert r.status_code == 400 and r.json()["error"]["field"] == "drawing_max_mb"


def _building(admin) -> str:  # type: ignore[no-untyped-def]
    return admin.post("/api/buildings", json={"name": "Корпус"}).json()["id"]


def _type(admin) -> str:  # type: ignore[no-untyped-def]
    return admin.post("/api/catalog/types", json={"name": "Кушетка"}).json()["id"]


# настройка, адрес загрузки, начало файла нужного вида
KINDS = [
    ("drawing_max_mb", lambda a: f"/api/buildings/{_building(a)}/drawings", DXF),
    ("underlay_max_mb", lambda a: "/api/files?accept=pdf,png,jpeg,webp", PDF),
    ("photo_max_mb", lambda a: "/api/files?accept=jpeg,png,webp,heic", JPEG),
    ("excel_max_mb", lambda a: "/api/catalog/import", XLSX),
    ("excel_max_mb", lambda a: "/api/inventory/import", XLSX),
    ("model3d_max_mb", lambda a: f"/api/catalog/types/{_type(a)}/model3d", GLB),
    ("transfer_max_mb", lambda a: "/api/transfer/check", XLSX),
]


def stream_post(app, client, url: str, chunks: Iterator[bytes]) -> tuple[int, dict]:  # type: ignore[no-untyped-def,type-arg]
    """POST прямо в ASGI-приложение, тело — частями, как из сети, без Content-Length.
    TestClient так не умеет: первым же сообщением он отдаёт приложению тело целиком."""
    path, _, query = url.partition("?")
    cookie = "; ".join(f"{k}={v}" for k, v in client.cookies.items())
    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
             "http_version": "1.1", "method": "POST", "scheme": "http", "path": path,
             "raw_path": path.encode(), "query_string": query.encode(), "root_path": "",
             "client": ("127.0.0.1", 50000), "server": ("testserver", 80),
             "headers": [(b"content-type", FORM["Content-Type"].encode()),
                         (b"x-requested-with", b"app"), (b"cookie", cookie.encode())]}
    started: dict = {}  # type: ignore[type-arg]
    body: list[bytes] = []

    async def receive() -> dict:  # type: ignore[type-arg]
        chunk = next(chunks, None)
        return {"type": "http.request", "body": chunk or b"", "more_body": chunk is not None}

    async def send(message: dict) -> None:  # type: ignore[type-arg]
        if message["type"] == "http.response.start":
            started.update(message)
        elif message["type"] == "http.response.body":
            body.append(message.get("body", b""))

    asyncio.run(app(scope, receive, send))
    return started["status"], json.loads(b"".join(body))


@pytest.mark.parametrize(("key", "path", "head"), KINDS,
                         ids=[f"{k}-{i}" for i, (k, _, _) in enumerate(KINDS)])
def test_r040_each_kind_is_refused_over_its_limit_before_it_is_received(
        app, admin, key: str, path, head: bytes) -> None:  # type: ignore[no-untyped-def]
    """R-040: файл больше лимита своего вида отклоняется с 413. Без Content-Length сервер
    обрывает приём на лимите, а не дочитывает тело."""
    settings(admin, **{key: 1})
    url = path(admin)
    fields = {"building_id": _building(admin)} if url == "/api/inventory/import" else None
    pulled: list[int] = []
    status, answer = stream_post(app, admin, url, multipart(head, 5, pulled, fields))
    assert status == 413, answer
    assert answer["error"]["code"] == "too_large" and "1 МБ" in answer["error"]["message"]
    assert len(pulled) <= 2, f"сервер забрал {len(pulled)} МБ при лимите 1 МБ"


def test_r040_declared_length_over_the_limit_is_refused(admin) -> None:
    """Content-Length больше лимита — 413 сразу; ниже лимита тот же чертёж принимается."""
    settings(admin, drawing_max_mb=1)
    building = _building(admin)
    big = admin.post(f"/api/buildings/{building}/drawings",
                     files={"file": ("план.dxf", io.BytesIO(DXF + b" " * (2 * MB)))})
    assert big.status_code == 413, big.text
    dxf = DXF + b"0\r\nENDSEC\r\n0\r\nEOF\r\n"
    small = admin.post(f"/api/buildings/{building}/drawings",
                       files={"file": ("план.dxf", io.BytesIO(dxf))})
    assert small.status_code == 201, small.text
