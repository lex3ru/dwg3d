import ezdxf
import pymupdf
import pytest

from pdf2dxf.cli import main
from pdf2dxf.convert import Options, convert_pdf, parse_pages

K = 25.4 / 72


def make_vector_pdf(path, rotation=0):
    doc = pymupdf.open()
    page = doc.new_page(width=842, height=595)  # A4 landscape
    page.draw_rect(pymupdf.Rect(0, 0, 842, 595), color=None, fill=(1, 1, 1))  # white background
    page.draw_line((100, 500), (400, 500), color=(0, 0, 0), width=1)
    page.draw_rect(pymupdf.Rect(100, 100, 300, 200), color=(1, 0, 0), width=0.5)
    page.draw_circle((500, 300), 50, color=(0, 0, 1), width=0.5)
    page.draw_line((100, 450), (400, 450), color=(0, 0.5, 0), dashes="[6 3] 0")
    page.draw_rect(pymupdf.Rect(600, 100, 700, 150), color=None, fill=(0.8, 0.2, 0.2))
    page.insert_text((120, 250), "Комната 12", fontsize=14, fontname="dejavu", fontfile="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    # an open polyline
    shape = page.new_shape()
    shape.draw_polyline([(600, 400), (650, 450), (700, 400)])
    shape.finish(color=(0, 0, 0), closePath=False)
    shape.commit()
    if rotation:
        page.set_rotation(rotation)
    doc.save(path)
    return path


def kinds(dxf):
    d = ezdxf.readfile(dxf)
    out = {}
    for e in d.modelspace():
        out.setdefault(e.dxftype(), []).append(e)
    return d, out


def test_vector_entities(tmp_path):
    pdf = make_vector_pdf(tmp_path / "a.pdf")
    dst = tmp_path / "a.dxf"
    (_, rep), = convert_pdf(pdf, dst)
    assert rep.mode == "vector"
    d, ents = kinds(dst)
    assert len(ents["CIRCLE"]) == 1
    c = ents["CIRCLE"][0]
    assert c.dxf.radius == pytest.approx(50 * K, rel=1e-2)
    # y axis is flipped: page height 595
    assert c.dxf.center.x == pytest.approx(500 * K, abs=0.05)
    assert c.dxf.center.y == pytest.approx((595 - 300) * K, abs=0.05)
    assert len(ents["TEXT"]) == 1 and ents["TEXT"][0].dxf.text == "Комната 12"
    assert len(ents["HATCH"]) == 1  # white background fill skipped
    assert any(e.dxf.linetype.startswith("PDF_DASH") for e in ents["LINE"])
    assert len(ents["LWPOLYLINE"]) >= 2  # rectangle + open polyline


def test_scale(tmp_path):
    pdf = make_vector_pdf(tmp_path / "a.pdf")
    dst = tmp_path / "a.dxf"
    convert_pdf(pdf, dst, opts=Options(scale=100))
    _, ents = kinds(dst)
    assert ents["CIRCLE"][0].dxf.radius == pytest.approx(50 * K * 100, rel=1e-2)


def test_rotated_page_matches_view(tmp_path):
    pdf = make_vector_pdf(tmp_path / "r.pdf", rotation=90)
    dst = tmp_path / "r.dxf"
    convert_pdf(pdf, dst)
    _, ents = kinds(dst)
    c = ents["CIRCLE"][0]
    # rotated 90 deg clockwise: displayed width = 595, height = 842
    assert c.dxf.center.x == pytest.approx((595 - 300) * K, abs=0.05)
    assert c.dxf.center.y == pytest.approx((842 - 500) * K, abs=0.05)


def test_raster_mode(tmp_path):
    src = make_vector_pdf(tmp_path / "v.pdf")
    with pymupdf.open(src) as d:
        png = d[0].get_pixmap(dpi=150).tobytes("png")
    scan = pymupdf.open()
    page = scan.new_page(width=842, height=595)
    page.insert_image(page.rect, stream=png)
    scan.save(tmp_path / "scan.pdf")
    dst = tmp_path / "scan.dxf"
    (_, rep), = convert_pdf(tmp_path / "scan.pdf", dst)
    assert rep.mode == "raster"
    _, ents = kinds(dst)
    assert ents.get("LINE") or ents.get("LWPOLYLINE")
    # the long horizontal line (300 pt) must survive as ~one segment of the right length
    longest = max(
        (abs(e.dxf.end.x - e.dxf.start.x) for e in ents.get("LINE", [])), default=0
    )
    assert longest == pytest.approx(300 * K, rel=0.05)


def test_pages_spec():
    assert parse_pages("1,3-4", 5) == [0, 2, 3]
    assert parse_pages("all", 2) == [0, 1]
    with pytest.raises(ValueError):
        parse_pages("7", 3)


def test_cli(tmp_path, capsys):
    pdf = make_vector_pdf(tmp_path / "a.pdf")
    assert main([str(pdf), "-s", "1:50"]) == 0
    assert (tmp_path / "a.dxf").exists()
    assert main([str(tmp_path / "nope.pdf")]) == 2


def test_raster_closed_shapes_and_solids(tmp_path):
    src = pymupdf.open()
    pg = src.new_page(width=300, height=200)
    pg.draw_rect(pymupdf.Rect(50, 50, 250, 150), color=(0, 0, 0), width=1)
    pg.draw_rect(pymupdf.Rect(100, 160, 150, 190), color=None, fill=(0.2, 0.2, 0.2))
    src.save(tmp_path / "p.pdf")
    convert_pdf(tmp_path / "p.pdf", tmp_path / "p.dxf", opts=Options(mode="raster"))
    _, ents = kinds(tmp_path / "p.dxf")
    rect = [e for e in ents["LWPOLYLINE"] if e.closed]
    assert len(rect) == 1 and len(rect[0]) == 4
    xs = [p[0] for p in rect[0].get_points("xy")]
    assert max(xs) - min(xs) == pytest.approx(200 * K, rel=0.03)
    assert len(ents["HATCH"]) == 1


def test_touching_paths_are_joined(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    # an L-shaped wall drawn as three separate one-segment paths, plus a duplicated line
    page.draw_line((50, 50), (150, 50))
    page.draw_line((150, 50), (150, 120))
    page.draw_line((150, 120), (250, 120))
    page.draw_line((50, 50), (150, 50))
    # a T junction must stay unjoined
    page.draw_line((50, 180), (250, 180))
    page.draw_line((150, 180), (150, 150))
    doc.save(tmp_path / "j.pdf")
    convert_pdf(tmp_path / "j.pdf", tmp_path / "j.dxf")
    _, ents = kinds(tmp_path / "j.dxf")
    assert len(ents["LWPOLYLINE"]) == 1 and len(ents["LWPOLYLINE"][0]) == 4
    assert len(ents["LINE"]) == 2


def test_twin_layers_and_frame(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=842, height=1191)
    for a, b in [((33, 50), (33, 1149)), ((33, 50), (796, 50)), ((796, 50), (796, 1149)), ((33, 1149), (796, 1149))]:
        page.draw_line(a, b, color=(0, 0, 0), width=0.12)  # sheet border
    page.draw_rect(pymupdf.Rect(0, 0, 842, 1191), color=(1, 1, 1), width=0.12)  # invisible white stroke
    page.draw_rect(pymupdf.Rect(200, 300, 400, 500), color=(0, 0, 0), width=0.24)
    page.draw_rect(pymupdf.Rect(500, 300, 520, 320), color=None, fill=(0, 0, 0))
    doc.save(tmp_path / "f.pdf")
    opts = Options(drop_frame=True, stroke_layer="A-WALL", fill_layer="Штриховка")
    convert_pdf(tmp_path / "f.pdf", tmp_path / "f.dxf", opts=opts)
    d, ents = kinds(tmp_path / "f.dxf")
    assert len(ents["LWPOLYLINE"]) == 1 and "LINE" not in ents
    assert ents["LWPOLYLINE"][0].dxf.layer == "A-WALL"
    assert ents["HATCH"][0].dxf.layer == "Штриховка"
    # without the option the border stays
    convert_pdf(tmp_path / "f.pdf", tmp_path / "g.dxf")
    _, ents = kinds(tmp_path / "g.dxf")
    assert len(ents["LWPOLYLINE"]) + len(ents.get("LINE", [])) > 1
