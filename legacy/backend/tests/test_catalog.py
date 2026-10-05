import pytest
import yaml

from dwg3d import catalog


def _write(tmp_path, cats):
    p = tmp_path / "cat.yaml"
    p.write_text(yaml.safe_dump({"categories": cats}, allow_unicode=True), encoding="utf-8")
    return p


def test_seed_loads_and_is_idempotent(pg):
    first = catalog.load()
    again = catalog.load()
    assert first["items"] == again["items"] >= 70 and again["added"] == again["deactivated"] == 0
    data = catalog.as_json()
    by_id = {i["id"]: i for i in data["items"]}
    assert {c["id"] for c in data["categories"]} >= {i["cat"] for i in data["items"]}
    assert by_id["sec.dome"]["cam"] == {"fov": 100, "range": 12, "ident": 4}
    assert by_id["rec.sofa"]["model"].endswith(".glb") and by_id["rec.sofa"]["wall"] is True
    assert "active" not in by_id["diag.mri"] and "modelRot" not in by_id["diag.mri"]


def test_removed_items_are_deactivated_not_deleted(pg, tmp_path):
    catalog.load()
    p = _write(tmp_path, [{"id": "x", "name": "X", "items": [
        {"id": "diag.mri", "name": "МРТ 3 Тл", "w": 2.3, "d": 4.6, "h": 2.3, "kind": "mri",
         "article": "MR-3T", "price": 1234567.891}]}])
    assert catalog.load(p)["deactivated"] == 0             # a plain import keeps the rest
    r = catalog.load(p, prune=True)
    assert r["deactivated"] >= 70
    by_id = {i["id"]: i for i in catalog.as_json()["items"]}
    assert by_id["diag.mri"]["cat"] == "x" and by_id["diag.mri"]["price"] == 1234567.89
    assert by_id["diag.mri"]["currency"] == "RUB" and "active" not in by_id["diag.mri"]
    assert by_id["sec.dome"]["active"] is False            # still resolvable for placed items
    catalog.load()                                        # back in the file -> active again
    assert all("active" not in i for i in catalog.as_json()["items"])


@pytest.mark.parametrize("item, msg", [
    ({"name": "A", "w": 1, "d": 1, "h": 1, "kind": "k"}, "нужен id"),
    ({"id": "a", "name": "A", "w": 0, "d": 1, "h": 1, "kind": "k"}, "w —"),
    ({"id": "a", "name": "A", "w": 1, "d": 1, "h": 1, "kind": "k", "color": "red"}, "color"),
    ({"id": "a", "name": "A", "w": 1, "d": 1, "h": 1, "kind": "k", "model": "../../etc/x.glb"}, "model"),
    ({"id": "a", "name": "A", "w": 1, "d": 1, "h": 1, "kind": "k", "currency": "rub"}, "currency"),
    ({"id": "a", "name": "A", "w": 1, "d": 1, "h": 1, "kind": "k", "size": 3}, "неизвестные поля"),
    ({"id": "a", "name": "A", "w": 1, "d": 1, "h": 1, "kind": "k", "cam": {"fov": 1}}, "cam"),
])
def test_invalid_yaml_is_rejected(tmp_path, item, msg):
    with pytest.raises(catalog.CatalogError, match=msg):
        catalog._parse(_write(tmp_path, [{"id": "c", "name": "C", "items": [item]}]))


def test_duplicate_ids_rejected(tmp_path):
    it = {"id": "a", "name": "A", "w": 1, "d": 1, "h": 1, "kind": "k"}
    with pytest.raises(catalog.CatalogError, match="повторяется"):
        catalog._parse(_write(tmp_path, [{"id": "c", "name": "C", "items": [it]},
                                         {"id": "e", "name": "E", "items": [it]}]))
