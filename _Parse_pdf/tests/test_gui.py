import tkinter as tk

import ezdxf
import pytest

from pdf2dxf.convert import convert_pdf
from pdf2dxf.gui import App, build_options, dxf_shapes

from test_convert import make_vector_pdf

FORM = dict(scale="1:100", mode="auto", fills=True, text=True, lineweights=True,
            tol="0,02", dpi="300", min_len="1", simplify="0.4")


def test_build_options():
    o = build_options(**FORM)
    assert o.scale == 100 and o.tol == 0.02 and o.dpi == 300


@pytest.mark.parametrize("field,value", [("scale", "abc"), ("scale", "0"), ("tol", "x"), ("dpi", "10")])
def test_build_options_errors(field, value):
    with pytest.raises(ValueError):
        build_options(**{**FORM, field: value})


def test_dxf_shapes(tmp_path):
    pdf = make_vector_pdf(tmp_path / "a.pdf")
    convert_pdf(pdf, tmp_path / "a.dxf")
    shapes, bbox = dxf_shapes(ezdxf.readfile(tmp_path / "a.dxf"))
    kinds = {s[0] for s in shapes}
    assert kinds == {"line", "fill", "text"}
    assert bbox[0] < bbox[2] and bbox[1] < bbox[3]


def test_app_end_to_end(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    try:
        app = App(root)
        pdf = make_vector_pdf(tmp_path / "a.pdf")
        app.load_pdf(pdf)
        assert app.v["out"].get().endswith("a.dxf")
        app.run()
        for _ in range(100):
            root.update()
            if not app.busy:
                break
            root.after(50)
        assert (tmp_path / "a.dxf").exists()
        assert app.results and app.result.shapes
    finally:
        root.destroy()


def test_build_options_twin():
    o = build_options(**FORM, twin=True, wall_layer=" A-WALL ", fill_layer="Штриховка")
    assert o.drop_frame and o.stroke_layer == "A-WALL" and o.fill_layer == "Штриховка"
    o = build_options(**FORM, twin=False, wall_layer="X")
    assert not o.drop_frame and o.stroke_layer is None
    with pytest.raises(ValueError):
        build_options(**FORM, twin=True, wall_layer=" ")
