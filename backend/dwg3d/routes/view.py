"""Per-drawing viewer state that needs no rebuild, and the drawing's rooms.

Map binding, detail-model alignment and the name are drawing columns (PUT
/view); placed furniture, shapes, markers and comments are rows (viewdata.py),
edited one by one through /api/drawings/{id}/objects and /pins.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import access, auth, db, rooms, store, viewdata
from ..models import Drawing
from . import common

router = APIRouter()
_f, _s = viewdata.num, viewdata.string

# viewer data changed row by row, not through PUT /view
FLOOR_BOUND = ("furniture", "furniture_unplaced", "shapes", "markers", "comments")


def validate_settings(v: dict, old: dict) -> dict:
    """name / site / detail from a PUT /view body: the columns to set."""
    out = {}
    if "name" in v:
        out["name"] = _s(v["name"], "name", 120)
    if "site" in v:
        out["site"] = _site(v["site"])
    if "detail" in v:
        out["detail"] = _detail(v["detail"] or {}, old.get("detail") or {})
    return out


def _site(st) -> dict | None:
    if st is None:
        return None
    if not isinstance(st, dict):
        raise viewdata.Invalid("view.site: ожидается объект")
    out = {"lat": _f(st.get("lat"), -85, 85, "site.lat"), "lon": _f(st.get("lon"), -180, 180, "site.lon"),
           "azimuth": _f(st.get("azimuth", 0), -360, 360, "site.azimuth"),
           "scale": _f(st.get("scale", 1), 0.01, 100, "site.scale")}
    if st.get("tiles"):
        t = _s(st["tiles"], "site.tiles", 300)
        if not t.startswith("https://") or not all(k in t for k in ("{z}", "{x}", "{y}")):
            raise viewdata.Invalid("view.site.tiles: шаблон https://…/{z}/{x}/{y}.png")
        out["tiles"] = t
        out["attribution"] = _s(st.get("attribution", ""), "site.attribution", 200)
    return out


def _detail(dt, old: dict) -> dict:
    """The detail model's alignment: the keys given replace the stored ones."""
    if not isinstance(dt, dict):
        raise viewdata.Invalid("view.detail: ожидается объект")
    cur = dict(old)
    if "offset" in dt:
        if not isinstance(dt["offset"], list) or len(dt["offset"]) != 3:
            raise viewdata.Invalid("view.detail.offset: ожидается [x, y, z]")
        cur["offset"] = [_f(c, -1e4, 1e4, "detail.offset") for c in dt["offset"]]
    if "rotation" in dt:
        cur["rotation"] = _f(dt["rotation"], -360, 360, "detail.rotation")
    if "scale" in dt:
        cur["scale"] = _f(dt["scale"], 1e-4, 1e4, "detail.scale")
    return cur


@router.get("/api/drawings/{did}/view")
def get_view(did: str):
    with db.session() as s:
        return store.view_of(s, common.drawing(s, did))


@router.put("/api/drawings/{did}/view")
def put_view(did: str, v: dict):
    """Merge viewer settings (name, site, detail): the keys given replace the
    stored ones. Objects and pins change row by row (/objects, /pins)."""
    if any(k in v for k in FLOOR_BOUND):
        raise HTTPException(400, "Расстановка и метки меняются построчно: /objects и /pins")
    with db.session() as s:
        d = common.drawing(s, did, lock=True)
        cols = validate_settings(v, store.view_of(s, d))
        if cols:
            _audit_settings(s, d, cols)
            store.set_settings(d, cols)
        s.flush()
        return store.view_of(s, d)


def _audit_settings(s, d: Drawing, cols: dict):
    before = {k: getattr(d, k) for k in cols}
    if before != cols:
        viewdata.audit_entry(s, d.project_id, "drawing", d.id, "update", before, cols, d.id)


# ------------------------------------------- objects and pins, row by row ---
# Floors are the candidate ids of the build given in `build` (409 if the model
# was rebuilt since); updates and deletes carry the row `version` they were
# made against (409 with the current rows if someone changed them meanwhile).
ROW_KINDS = {"objects": "object", "pins": "pin"}


def _body(v) -> dict:
    if not isinstance(v, dict):
        raise viewdata.Invalid("Ожидается объект")
    return v


def _one(res: dict):
    return res["items"][0] if res["items"] else None


def _row_routes(kind: str):
    entity = ROW_KINDS[kind]

    def list_rows(did: str, floor: str | None = None, layer: str | None = None):
        with db.session() as s:
            d = common.drawing(s, did)
            data = viewdata.view_data(s, did, access.visible_layers(auth.current.get()))
        pick = lambda k: [it for it in data.get(k) or []  # noqa: E731
                          if (floor is None or it["floor"] == floor) and (layer is None or it.get("layer") == layer)]
        if kind == "objects":
            return {"build": d.current_build, "items": pick("furniture") + pick("shapes"),
                    "unplaced": [it for it in data.get("furniture_unplaced") or [] if layer is None or it["layer"] == layer]}
        return {"build": d.current_build, "markers": pick("markers"), "comments": pick("comments")}

    def batch_rows(did: str, v: dict):
        """{build, ops: [{op, id, version, ...}]}: all applied or none (Ряд…, копии, отмена)."""
        v = _body(v)
        with db.session() as s:
            return viewdata.apply(s, did, entity, v.get("ops"), build=v.get("build"))

    def create_row(did: str, v: dict):
        v = _body(v)
        with db.session() as s:
            return _one(viewdata.apply(s, did, entity, [{**v, "op": "create"}], build=v.get("build")))

    def update_row(did: str, rid: str, v: dict):
        v = _body(v)
        with db.session() as s:
            return _one(viewdata.apply(s, did, entity, [{**v, "op": "update", "id": rid}], build=v.get("build")))

    def delete_row(did: str, rid: str, version: int | None = None, build: int | None = None):
        with db.session() as s:
            viewdata.apply(s, did, entity, [{"op": "delete", "id": rid, "version": version}], build=build)

    base = f"/api/drawings/{{did}}/{kind}"
    router.add_api_route(base, list_rows, methods=["GET"])
    router.add_api_route(base + ":batch", batch_rows, methods=["POST"])
    router.add_api_route(base, create_row, methods=["POST"], status_code=201)
    router.add_api_route(base + "/{rid}", update_row, methods=["PATCH"])
    router.add_api_route(base + "/{rid}", delete_row, methods=["DELETE"], status_code=204)


for _kind in ROW_KINDS:
    _row_routes(_kind)


@router.get("/api/drawings/{did}/rooms")
def list_rooms(did: str):
    with db.session() as s:
        common.drawing(s, did)
        return rooms.rooms_json(s, did)
