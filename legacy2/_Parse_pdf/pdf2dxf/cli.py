from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .convert import Options, convert_pdf


TWIN_WALL_LAYER = "A-WALL"   # matched by the import pipeline's layers.walls ("*WALL*")
TWIN_FILL_LAYER = "Штриховка"  # matched by layers.ignore: filled glyphs / hatches are not walls


def parse_scale(s: str) -> float:
    """'100' or '1:100' -> 100.0"""
    s = s.strip()
    if ":" in s:
        a, b = s.split(":", 1)
        return float(b) / float(a)
    return float(s)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pdf2dxf", description="Конвертер PDF-чертежей в DXF для CAD.")
    ap.add_argument("pdf", type=Path, help="входной PDF")
    ap.add_argument("-o", "--output", type=Path, help="выходной DXF (по умолчанию рядом с PDF)")
    ap.add_argument("-p", "--pages", default="1", help="страницы: 1, 2-4, 1,3 или all (по умолчанию 1); "
                    "для нескольких страниц создаётся по файлу на страницу")
    ap.add_argument("-s", "--scale", default="1", type=parse_scale,
                    help="масштаб чертежа: 100 или 1:100 — размеры на бумаге умножаются на него (по умолчанию 1:1, мм бумаги)")
    ap.add_argument("-m", "--mode", choices=["auto", "vector", "raster"], default="auto",
                    help="vector — векторная графика, raster — трассировка пикселей (сканы), "
                         "auto — по странице (по умолчанию)")
    ap.add_argument("--dpi", type=int, default=300, help="растровый режим: разрешение (300)")
    ap.add_argument("--min-len", type=float, default=1.0, help="растровый режим: отбрасывать линии короче, мм (1)")
    ap.add_argument("--simplify", type=float, default=0.4, help="растровый режим: допуск упрощения ломаных, мм (0.4)")
    ap.add_argument("--tol", type=float, default=0.02, help="допуск замены кривых дугами, мм (0.02)")
    ap.add_argument("--drop-frame", action="store_true", help="убрать рамку листа (длинные линии вдоль краёв)")
    ap.add_argument("--stroke-layer", metavar="ИМЯ", help="все линии — на этот слой (напр. A-WALL), вместо слоёв по цвету")
    ap.add_argument("--fill-layer", metavar="ИМЯ", help="все заливки — на этот слой (напр. Штриховка)")
    ap.add_argument("--twin", action="store_true",
                    help="для импорта в цифровой двойник: --drop-frame --stroke-layer A-WALL --fill-layer Штриховка")
    ap.add_argument("--no-fills", action="store_true", help="не переносить заливки (HATCH)")
    ap.add_argument("--no-text", action="store_true", help="не переносить текст")
    ap.add_argument("--no-lineweights", action="store_true", help="не переносить толщины линий")
    a = ap.parse_args(argv)
    if a.twin:
        a.drop_frame = True
        a.stroke_layer = a.stroke_layer or TWIN_WALL_LAYER
        a.fill_layer = a.fill_layer or TWIN_FILL_LAYER

    if not a.pdf.is_file():
        print(f"нет файла: {a.pdf}", file=sys.stderr)
        return 2
    out = a.output or a.pdf.with_suffix(".dxf")
    opts = Options(
        scale=a.scale, mode=a.mode, fills=not a.no_fills, text=not a.no_text,
        lineweights=not a.no_lineweights, tol=a.tol, dpi=a.dpi, min_len=a.min_len, simplify=a.simplify,
        drop_frame=a.drop_frame, stroke_layer=a.stroke_layer, fill_layer=a.fill_layer,
    )
    try:
        results = convert_pdf(a.pdf, out, a.pages, opts)
    except ValueError as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 2

    status = 0
    for path, rep in results:
        stats = ", ".join(f"{k}: {v}" for k, v in sorted(rep.counts.items())) or "пусто"
        print(f"стр. {rep.page} [{rep.mode}] -> {path}  ({stats})")
        for w in rep.warnings:
            print(f"  ! {w}", file=sys.stderr)
        if not rep.counts:
            status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
