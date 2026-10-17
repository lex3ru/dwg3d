"""Печать таблиц для отчётов и ведомостей (5.6): PDF (WeasyPrint) и Excel (openpyxl) из одного
описания — заголовок, разделы с таблицами, итоги, места для подписей."""

import html
import io
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Section:
    title: str
    columns: list[str]
    rows: list[list[Any]]
    total: list[Any] | None = None  # строка итогов
    numeric: set[int] = field(default_factory=set)  # колонки чисел — вправо


@dataclass
class Report:
    title: str
    subtitle: str = ""
    organization: str = ""
    sections: list[Section] = field(default_factory=list)
    signatures: list[str] = field(default_factory=list)  # «Председатель комиссии», …
    landscape: bool = True


def _e(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def _cell(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:,.2f}".replace(",", " ").replace(".", ",")
    return _e(v)


def pdf(r: Report) -> bytes:
    from weasyprint import HTML

    parts = []
    for s in r.sections:
        head = "".join(f"<th>{_e(c)}</th>" for c in s.columns)
        body = "".join(
            "<tr>"
            + "".join(
                f'<td class="{"n" if i in s.numeric else ""}">{_cell(v)}</td>'
                for i, v in enumerate(row)
            )
            + "</tr>"
            for row in s.rows
        )
        if not s.rows:
            body = f'<tr><td colspan="{len(s.columns)}" class="empty">нет</td></tr>'
        total = (
            '<tr class="total">'
            + "".join(
                f'<td class="{"n" if i in s.numeric else ""}">{_cell(v)}</td>'
                for i, v in enumerate(s.total)
            )
            + "</tr>"
            if s.total
            else ""
        )
        parts.append(f"<h2>{_e(s.title)}</h2><table><tr>{head}</tr>{body}{total}</table>")
    signs = "".join(
        f'<div class="sign"><span>{_e(s)}</span><span class="line"></span>'
        '<span class="hint">подпись / ФИО</span></div>'
        for s in r.signatures
    )
    orientation = "landscape" if r.landscape else "portrait"
    doc = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><style>
@page {{ size: A4 {orientation}; margin: 12mm;
  @bottom-right {{ content: counter(page) " из " counter(pages); font-size: 8pt; }} }}
body {{ font-family: "DejaVu Sans", sans-serif; font-size: 9pt; margin: 0; }}
.org {{ color: #555; font-size: 8pt; }} h1 {{ font-size: 13pt; margin: 1mm 0; }}
.sub {{ color: #333; margin-bottom: 3mm; }} h2 {{ font-size: 10.5pt; margin: 4mm 0 1.5mm; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 0.2mm solid #999; padding: 1mm 1.5mm; vertical-align: top; }}
th {{ background: #eee; text-align: left; font-weight: 600; }}
.n {{ text-align: right; white-space: nowrap; }} .empty {{ color: #777; }}
.total td {{ font-weight: bold; }}
.signs {{ margin-top: 8mm; }}
.sign {{ display: flex; gap: 3mm; align-items: flex-end; margin: 5mm 0; }}
.sign .line {{ flex: 1; border-bottom: 0.2mm solid #000; max-width: 90mm; height: 4mm; }}
.sign .hint {{ color: #777; font-size: 7pt; }}
</style></head><body>
<div class="org">{_e(r.organization)}</div><h1>{_e(r.title)}</h1>
<div class="sub">{_e(r.subtitle)} · сформировано {datetime.now():%d.%m.%Y %H:%M}</div>
{"".join(parts)}
{f'<div class="signs">{signs}</div>' if signs else ""}
</body></html>"""
    return HTML(string=doc).write_pdf()


def xlsx(r: Report) -> bytes:
    # потоком (write-only): листы на десятки тысяч строк не держатся в памяти целиком (8.1)
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook(write_only=True)
    used: set[str] = set()
    bold, fill = Font(bold=True), PatternFill("solid", fgColor="EEEEEE")
    for s in r.sections or [Section("Лист", [], [])]:
        name = "".join(ch for ch in s.title if ch not in "[]:*?/\\")[:31] or "Лист"
        base, n = name, 2
        while name in used:
            name = f"{base[:28]} {n}"
            n += 1
        used.add(name)
        ws = wb.create_sheet(name)
        for i, col in enumerate(s.columns, 1):
            width = max(
                [len(str(col))] + [len(str(row[i - 1])) for row in s.rows if i - 1 < len(row)] + [8]
            )
            ws.column_dimensions[get_column_letter(i)].width = min(60, width + 2)
        head = 4 if r.subtitle else 3
        ws.freeze_panes = f"A{head + 1}"

        def styled(values: list[Any], font: Any, fill_: Any = None, ws: Any = ws) -> list[Any]:
            out = []
            for v in values:
                c = WriteOnlyCell(ws, value=v)
                c.font = font
                if fill_ is not None:
                    c.fill = fill_
                out.append(c)
            return out

        ws.append(styled([r.title], Font(bold=True, size=12)))
        if r.subtitle:
            ws.append([r.subtitle])
        ws.append([])
        ws.append(styled(list(s.columns), bold, fill))
        for row in s.rows:
            ws.append(list(row))
        if s.total:
            ws.append(styled(list(s.total), bold))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
