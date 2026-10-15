"""Room types, label placement, entrances, points of interest."""
import pytest
from shapely.geometry import box

from app.dwg.config import ConfigError, load_config, validate_config
from app.dwg.geometry import room_labels
from app.dwg.extract import Text
from app.dwg.pipeline import run
from app.dwg.semantics import classify_name, label_frame, legend, room_type_rules

from .make_sample import make

RULES = room_type_rules(load_config())


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    return make(tmp_path_factory.mktemp("dxf") / "sample.dxf")


@pytest.mark.parametrize("name,expected", [
    ("Лестничная клетка ЛК-1", "stair"), ("ЛК-2", "stair"), ("Лифтовой холл", "lift"), ("Лифт", "lift"),
    ("Санузел", "wc"), ("С/у", "wc"), ("Туалет для МГН", "wc"), ("Душевая", "wc"),
    ("Коридор", "corridor"), ("Холл", "corridor"), ("Вестибюль", "corridor"),
    ("Кабинет врача терапевта-консультанта", "doctor"), ("Процедурная", "procedure"),
    ("Помещение АПС", "technical"), ("Венткамера", "technical"),
    ("Служебное помещение", "service"), ("Охрана", "service"), ("Помещение хранения каталок", "service"),
    ("Зона ожидания", "waiting"), ("Кабинет", "office"), ("Лабораторный зал", "procedure"),
    ("Второй свет", None), ("", None),
])
def test_room_type_by_name(name, expected):
    assert classify_name(name, RULES) == expected


def test_room_type_rules_follow_config_order():
    cfg = load_config({"room_types": {"stair": {"names": ["*холл*"]}}})
    # user patterns replace the default ones of that type, order is kept
    assert classify_name("Лифтовой холл", room_type_rules(cfg)) == "stair"


def test_legend_has_fallback_and_colors():
    lg = legend(load_config())
    assert lg[-1]["type"] == "other"
    assert all(x["color"].startswith("#") and len(x["color"]) == 7 for x in lg)


def test_door_marks_are_not_room_names():
    texts = [Text(t, 0, 0, 0.3, "T") for t in ("ДГФ24-9", "ОК-1.1", "ДГМ20-7 EI60", "Д-3", "Душевая", "Охрана")]
    names = [t.text for t in room_labels(texts, load_config()["geometry"]["room_label_ignore"])]
    assert names == ["Душевая", "Охрана"]


def test_hall_with_open_stair_is_not_a_stair_well():
    from types import SimpleNamespace
    from app.dwg.semantics import classify_room
    flight = SimpleNamespace(poly=box(0, 0, 1.2, 3))
    plan = SimpleNamespace(stairs=[flight])
    well = SimpleNamespace(name="", poly=box(-0.5, -0.5, 3, 6))
    hall = SimpleNamespace(name="", poly=box(-10, -10, 20, 20))
    assert classify_room(well, plan, RULES) == "stair"
    assert classify_room(hall, plan, RULES) == "other"


def test_label_frame_follows_long_side():
    corridor = box(0, 0, 2, 20)                     # long along plan Y
    lf = label_frame(corridor)
    assert abs(abs(lf["angle"]) - 1.5708) < 1e-3
    assert lf["w"] == pytest.approx(17, abs=0.1) and lf["d"] == pytest.approx(1.6, abs=0.1)
    square = label_frame(box(0, 0, 6, 5))
    assert square["angle"] == 0 and square["w"] == pytest.approx(0.85 * 6, abs=0.05)


def test_validate_room_types_and_entrances():
    validate_config(load_config({"room_types": {"pool": {"label": "Бассейн", "color": "#3399ff", "names": ["*бассейн*"]}},
                                 "building": {"entrances": [{"at": [1, 2], "main": True, "name": "Вход"}]}}))
    for bad in ({"room_types": {"x": {"color": "red"}}}, {"room_types": {"x": {"names": "a"}}},
                {"building": {"entrances": [{"at": "1,2"}]}}, {"geometry": {"room_label_ignore": ["("]}}):
        with pytest.raises(ConfigError):
            validate_config(load_config(bad))


def test_types_entrances_and_pois_in_metadata(sample, tmp_path):
    fid = run(sample, tmp_path, debug_png=False)["floors"][0]["id"]
    # exterior door in the south wall of floor 1
    cfg = {"edits": {fid: {"add_openings": [{"a": [3.0, 0.15], "b": [4.2, 0.15], "kind": "door"}]}}}
    meta = run(sample, tmp_path, cfg, debug_png=False)
    f1 = meta["floors"][0]
    types = {r["name"]: r["type"] for r in f1["rooms"]}
    assert types["Кабинет"] == "office"
    assert types[""] == "stair"                            # unnamed room with the stair flight
    assert all({"label_angle", "label_w", "label_d"} <= set(r) for r in f1["rooms"])
    ent = meta["entrances"]
    assert len(ent) == 1 and ent[0]["main"] and ent[0]["label"] == "A" and ent[0]["floor"] == f1["id"]
    x, y, z = ent[0]["pos"]
    cx, cy = meta["center"]
    assert (x + cx, -z + cy) == pytest.approx((3.6, 0.15), abs=0.05)
    assert ent[0]["dir"] == pytest.approx([0, 1], abs=1e-3)      # outward = plan -Y = glTF +Z
    assert {p["kind"] for p in meta["pois"]} == {"stair"} and len(meta["pois"]) == 2
    assert {t["type"] for t in meta["room_types"]} >= {"stair", "office", "other"}


def test_manual_entrance_overrides_auto(sample, tmp_path):
    cfg = {"building": {"entrances": [{"at": [12.0, 4.0], "name": "Служебный", "main": True}]}}
    meta = run(sample, tmp_path, cfg, debug_png=False)
    (e,) = meta["entrances"]
    assert e["name"] == "Служебный" and e["dir"] == pytest.approx([1, 0], abs=1e-3)
