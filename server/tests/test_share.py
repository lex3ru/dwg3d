"""Ссылки на просмотр (5.7.2, С21): гость без учётной записи видит план и расстановку здания
до срока ссылки — без учёта, проектов, расчётов, поиска; отзыв досрочно; открытия — в журнале."""

from datetime import UTC, date, datetime, timedelta

from app.core.db import transaction
from app.modules.access.models import ShareLink
from tests.conftest import make_client
from tests.test_building import building_with_floor, save, two_rooms
from tests.test_planning import changes


def test_c21_share_link_shows_plan_only_until_revoked(admin, app) -> None:
    b, f = building_with_floor(admin)
    save(admin, f["id"], two_rooms(), 1)
    other, _ = building_with_floor(admin)
    layer = admin.post("/api/catalog/layers", json={"name": "Видеонаблюдение"}).json()
    cam = admin.post("/api/catalog/types", json={"name": "Камера", "layer_id": layer["id"]}).json()
    assert (
        changes(admin, f["id"], create=[{"type_id": cam["id"], "x": 1000, "y": 2000}]).status_code
        == 200
    )

    r = admin.post(
        "/api/share-links",
        json={
            "building_id": b["id"],
            "until": str(date.today() + timedelta(days=14)),
            "note": "ЧОП «Щит»",
        },
    )
    assert r.status_code == 201, r.text
    link = r.json()
    assert link["status"] == "active" and link["building"] == b["name"]
    token = link["token"]
    assert "token" not in admin.get("/api/share-links").json()["items"][0]

    with make_client(app) as guest:
        assert guest.get("/api/auth/me").status_code == 401
        opened = guest.post(f"/api/share/{token}")
        assert opened.status_code == 200, opened.text
        me = guest.get("/api/auth/me").json()
        assert me["role"] == "guest" and me["building_ids"] == [b["id"]]
        # план и расстановка здания
        assert guest.get(f"/api/buildings/{b['id']}").status_code == 200
        assert guest.get(f"/api/floors/{f['id']}/plan").status_code == 200
        assert len(guest.get(f"/api/floors/{f['id']}/items").json()["items"]) == 1
        assert guest.get("/api/catalog").status_code == 200
        # чужое здание и всё остальное — нет
        assert guest.get(f"/api/buildings/{other['id']}").status_code in (403, 404)
        for url in (
            "/api/inventory/units",
            "/api/inventory/places",
            f"/api/link/floors/{f['id']}",
            "/api/projects",
            "/api/calc",
            "/api/search?q=каб",
            "/api/journal",
            "/api/users",
        ):
            assert guest.get(url).status_code == 403, url
        assert guest.post(f"/api/floors/{f['id']}/items/changes", json={}).status_code == 403

        # отозвали — ссылка больше не пускает
        assert admin.post(f"/api/share-links/{link['id']}/revoke").json()["status"] == "revoked"
        assert guest.get(f"/api/floors/{f['id']}/plan").status_code == 401
        assert guest.post(f"/api/share/{token}").status_code == 410

    # истёкшая — тоже
    r = admin.post("/api/share-links", json={"building_id": b["id"], "until": str(date.today())})
    with transaction() as s:
        row = s.get(ShareLink, r.json()["id"])
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    with make_client(app) as late:
        assert late.post(f"/api/share/{r.json()['token']}").status_code == 410

    feed = admin.get("/api/journal", params={"ref": f"building:{b['id']}"}).json()["items"]
    actions = [e["action"] for e in feed]
    assert "access.share_open" in actions and "access.share_revoke" in actions
    opened_by = next(e for e in feed if e["action"] == "access.share_open")["actor_name"]
    assert opened_by == "Гость по ссылке (ЧОП «Щит»)"
