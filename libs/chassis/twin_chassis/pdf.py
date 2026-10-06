"""PDF documents the services write: a font with Cyrillic, QR codes, pages.

    from twin_chassis import pdf
    c = pdf.canvas(buffer, pagesize=(w, h))      # a canvas with the font registered
    pdf.qr(c, "https://…", x, y, size)           # a QR code drawn with the page's units
    c.setFont(pdf.FONT, 9) / pdf.BOLD

Needs the extra `twin-chassis[pdf]` (reportlab, segno).
"""
from __future__ import annotations

from pathlib import Path

import segno
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as _canvas

FONT, BOLD = "DejaVu", "DejaVu-Bold"
FONTS = Path(__file__).parent / "fonts"
_registered = False


def register_fonts() -> None:
    global _registered
    if not _registered:
        pdfmetrics.registerFont(TTFont(FONT, FONTS / "DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont(BOLD, FONTS / "DejaVuSans-Bold.ttf"))
        pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=BOLD, italic=FONT, boldItalic=BOLD)
        _registered = True


def canvas(target, **kw) -> _canvas.Canvas:
    register_fonts()
    return _canvas.Canvas(target, **kw)


def qr(c: _canvas.Canvas, text: str, x: float, y: float, size: float, *, quiet: int = 2) -> None:
    """A QR code (error level M) in the square at (x, y) of `size`, including the quiet zone of `quiet` modules."""
    code = segno.make(text, error="m")
    matrix = [list(row) for row in code.matrix]
    n = len(matrix) + 2 * quiet
    module = size / n
    c.saveState()
    c.setFillColorRGB(0, 0, 0)
    for r, row in enumerate(matrix):
        for k, dark in enumerate(row):
            if dark:
                c.rect(x + (k + quiet) * module, y + size - (r + quiet + 1) * module, module, module, stroke=0, fill=1)
    c.restoreState()


def fit(text: str, font: str, size: float, width: float, *, smallest: float = 4) -> float:
    """The largest font size (≤ `size`) at which the text is one line within `width`."""
    while size > smallest and pdfmetrics.stringWidth(text, font, size) > width:
        size -= 0.5
    return size


def lines(text: str, font: str, size: float, width: float) -> list[str]:
    return simpleSplit(text, font, size, width)
