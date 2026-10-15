"""QR labels for printing: one sticker, or a sheet of them on A4 (docs/TZ.md, 4.4).

A label is a square of `size` mm: the QR code (the link to the object's card)
on top, the inventory number and the type below (for an object without a number:
the type, marked «не на учёте»). The link carries nothing but the code: whoever scans it signs in and sees the card only with a right to it.
"""
from __future__ import annotations

from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from twin_chassis import pdf

MIN_MM, MAX_MM = 20, 100


def link(public_url: str, code: str) -> str:
    return f"{public_url}/q/{code}"


def _sticker(c, x: float, y: float, size: float, url: str, a, *, cut: bool) -> None:
    pad = size * 0.04
    q = size * 0.62
    pdf.qr(c, url, x + (size - q) / 2, y + size - q - pad, q)
    # one not on the books has no number: the type takes its place, and the small line says so
    number, kind = (a.inventory_no, a.type_name) if a.inventory_no else (a.type_name, "не на учёте")
    big = pdf.fit(number, pdf.BOLD, size * 0.12, size - 2 * pad)
    c.setFont(pdf.BOLD, big)
    c.drawCentredString(x + size / 2, y + size * 0.19, number)
    small = pdf.fit(kind, pdf.FONT, size * 0.08, size - 2 * pad)
    c.setFont(pdf.FONT, small)
    c.drawCentredString(x + size / 2, y + size * 0.08, kind)
    if cut:
        c.saveState()
        c.setDash(2, 2)
        c.setLineWidth(0.3)
        c.setStrokeColorRGB(0.6, 0.6, 0.6)
        c.rect(x, y, size, size)
        c.restoreState()


def single(url: str, a, size_mm: float) -> bytes:
    """One label; the page is the sticker itself."""
    out = BytesIO()
    size = size_mm * mm
    c = pdf.canvas(out, pagesize=(size, size), pageCompression=1)
    c.setTitle(f"Метка {a.inventory_no or a.qr_code}")
    _sticker(c, 0, 0, size, url, a, cut=False)
    c.showPage()
    c.save()
    return out.getvalue()


def sheet(items: list[tuple[str, object]], size_mm: float, title: str) -> bytes:
    """Labels in rows on A4 pages, cut lines around each."""
    out = BytesIO()
    size, gap, margin = size_mm * mm, 2 * mm, 10 * mm
    width, height = A4
    cols = max(1, int((width - 2 * margin + gap) // (size + gap)))
    rows = max(1, int((height - 2 * margin + gap) // (size + gap)))
    c = pdf.canvas(out, pagesize=A4, pageCompression=1)
    c.setTitle(title)
    for n, (url, a) in enumerate(items):
        k = n % (cols * rows)
        if n and k == 0:
            c.showPage()
        col, row = k % cols, k // cols
        x = margin + col * (size + gap)
        y = height - margin - (row + 1) * size - row * gap
        _sticker(c, x, y, size, url, a, cut=True)
    c.showPage()
    c.save()
    return out.getvalue()
