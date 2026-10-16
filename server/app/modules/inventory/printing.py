"""Печать (5.4.4 п. 5, 5.4.7): QR-метки — листом А4 с наклейками или на принтере этикеток;
печатные формы документов — свои, простые."""

import html
from datetime import date
from typing import Any

import segno

from app.modules.inventory.rules import doc_title


def _e(text: Any) -> str:
    return html.escape(str(text or ""))


def _qr(url: str, size_mm: float) -> str:
    svg = segno.make(url, error="m").svg_inline(scale=1, border=0, dark="#000")
    return f'<div class="qr" style="width:{size_mm:.1f}mm;height:{size_mm:.1f}mm">{svg}</div>'


def labels_pdf(
    labels: list[dict[str, str]], settings: dict[str, Any], base_url: str, mode: str = "sheet"
) -> bytes:
    """labels: code, number, title. Ссылка на метке постоянная: /q/<код> (5.4.7)."""
    from weasyprint import HTML

    w, h = float(settings["label_width_mm"]), float(settings["label_height_mm"])
    org = _e(settings.get("organization_name", ""))
    qr = min(h - 2, w * 0.45)

    def one(item: dict[str, str]) -> str:
        url = f"{base_url.rstrip('/')}/q/{item['code']}"
        return (
            f'<div class="label">{_qr(url, qr)}<div class="text">'
            f'<div class="number">{_e(item["number"])}</div>'
            f'<div class="title">{_e(item["title"])}</div>'
            f'<div class="org">{org}</div></div></div>'
        )

    style = f"""
    body {{ margin: 0; font-family: "DejaVu Sans", sans-serif; }}
    .label {{ width: {w}mm; height: {h}mm; box-sizing: border-box; padding: 1mm; display: flex;
              gap: 1.2mm; align-items: center; overflow: hidden; }}
    .qr svg {{ width: 100%; height: 100%; }}
    .text {{ flex: 1; min-width: 0; }}
    .number {{ font-weight: bold; font-size: {max(6, h * 0.36):.1f}pt; }}
    .title {{ font-size: {max(4.5, h * 0.2):.1f}pt; line-height: 1.15; max-height: {h * 0.5:.1f}mm;
              overflow: hidden; }}
    .org {{ font-size: 4.5pt; color: #444; margin-top: .5mm; }}
    """
    if mode == "printer":
        page = f"@page {{ size: {w}mm {h}mm; margin: 0; }} .label {{ page-break-after: always; }}"
        body = "".join(one(i) for i in labels)
    else:
        cols, rows = int(settings["label_sheet_cols"]), int(settings["label_sheet_rows"])
        top, left = float(settings["label_sheet_top_mm"]), float(settings["label_sheet_left_mm"])
        gap = float(settings["label_sheet_gap_mm"])
        page = (
            f"@page {{ size: A4; margin: {top}mm 0 0 {left}mm; }}"
            f" .sheet {{ display: grid; grid-template-columns: repeat({cols}, {w}mm);"
            f" grid-auto-rows: {h}mm; gap: {gap}mm; }}"
            f" .label {{ outline: 0.1mm dotted #bbb; }} .sheet {{ page-break-after: always; }}"
        )
        per = cols * rows
        sheets = [labels[i : i + per] for i in range(0, len(labels), per)] or [[]]
        body = "".join(f'<div class="sheet">{"".join(one(x) for x in s)}</div>' for s in sheets)
    return HTML(
        string=f"<html><head><style>{page}{style}</style></head><body>{body}</body></html>"
    ).write_pdf()


SIGNATURES = {
    "opening": ["Ответственный за учёт"],
    "receipt": ["Сдал (поставщик)", "Принял"],
    "transfer": ["Сдал", "Принял"],
    "repair": ["Сдал", "Принял"],
    "writeoff": ["Председатель комиссии", "Член комиссии", "Член комиссии"],
    "revaluation": ["Председатель комиссии", "Член комиссии", "Член комиссии"],
}


def document_pdf(doc: dict[str, Any], organization: str) -> bytes:
    from weasyprint import HTML

    def money(v: Any) -> str:
        return f"{float(v or 0):,.2f}".replace(",", " ").replace(".", ",")

    rows = []
    for i, line in enumerate(doc["lines"], 1):
        numbers = ", ".join(u["number"] for u in line["created_units"]) or line.get("number") or ""
        what = numbers if line["accounting"] == "piece" else f"{line['qty']:g} {line['unit']}"
        extra = []
        if line.get("from_title") and doc["kind"] in ("transfer", "writeoff"):
            extra.append(f"откуда: {line['from_title']}")
        if line.get("to_title") and doc["kind"] in ("transfer", "opening"):
            extra.append(f"куда: {line['to_title']}")
        if line.get("reason") and doc["kind"] == "writeoff":
            extra.append(f"причина: {line['reason']}")
        if line.get("new_value") is not None:
            extra.append(f"новая стоимость: {money(line['new_value'])} ₽")
        rows.append(
            f"<tr><td>{i}</td><td>{_e(line['type_name'])}"
            f"{(' ' + _e(line['model_name'])) if line['model_name'] else ''}"
            f"{'<div class=small>' + _e('; '.join(extra)) + '</div>' if extra else ''}</td>"
            f"<td>{_e(what)}</td><td class=n>{money(line['price'])}</td>"
            f"<td class=n>{money(line['amount'])}</td></tr>"
        )
    head = []
    if doc["from_title"]:
        head.append(f"<div>Откуда: <b>{_e(doc['from_title'])}</b></div>")
    if doc["to_title"]:
        head.append(f"<div>Куда: <b>{_e(doc['to_title'])}</b></div>")
    if doc["supplier"]:
        head.append(f"<div>Поставщик: {_e(doc['supplier'])}</div>")
    if doc["kind"] == "repair":
        head.append(
            "<div>"
            + ("Отправка в ремонт" if doc["repair"] == "send" else "Возврат из ремонта")
            + (", исполнитель: " + _e(doc["contractor"]) if doc["contractor"] else "")
            + (
                ", стоимость ремонта: " + money(doc["repair_cost"]) + " ₽"
                if doc["repair_cost"]
                else ""
            )
            + "</div>"
        )
    if doc["basis"]:
        head.append(f"<div>Основание: {_e(doc['basis'])}</div>")
    sigs = "".join(
        f'<div class="sig"><span>{_e(s)}</span><span class="line"></span>'
        '<span class="hint">подпись / ФИО</span></div>'
        for s in SIGNATURES[doc["kind"]]
    )
    status = {"draft": " (черновик)", "cancelled": " (отменён)"}.get(doc["status"], "")
    when = doc["date"] if isinstance(doc["date"], date) else date.fromisoformat(str(doc["date"]))
    body = f"""
    <div class="org">{_e(organization)}</div>
    <h1>{_e(doc_title(doc["kind"], doc["number"]))} от {when:%d.%m.%Y}{status}</h1>
    {"".join(head)}
    <table><thead><tr><th>№</th><th>Наименование</th><th>Инв. номер / кол-во</th>
    <th>Цена, ₽</th><th>Сумма, ₽</th></tr></thead><tbody>{"".join(rows)}</tbody>
    <tfoot><tr><td></td><td colspan=3>Итого</td>
    <td class=n>{money(doc["total"])}</td></tr></tfoot></table>
    <div class="sigs">{sigs}</div>
    """
    style = """
    @page { size: A4; margin: 15mm 12mm;
            @bottom-right { content: counter(page) " / " counter(pages); font-size: 8pt; } }
    body { font-family: "DejaVu Sans", sans-serif; font-size: 9.5pt; }
    .org { color: #444; margin-bottom: 4mm; }
    h1 { font-size: 14pt; margin: 0 0 4mm; }
    table { width: 100%; border-collapse: collapse; margin: 5mm 0; }
    th, td { border: 0.3mm solid #999; padding: 1.5mm 2mm; vertical-align: top; text-align: left; }
    th { background: #eef2f6; font-weight: normal; font-size: 8.5pt; }
    .n { text-align: right; white-space: nowrap; }
    tfoot td { font-weight: bold; }
    .small { font-size: 8pt; color: #555; }
    .sigs { margin-top: 10mm; }
    .sig { display: flex; align-items: baseline; gap: 4mm; margin-bottom: 8mm; }
    .sig .line { flex: 1; border-bottom: 0.3mm solid #000; }
    .sig .hint { font-size: 7pt; color: #777; }
    """
    return HTML(
        string=f"<html><head><style>{style}</style></head><body>{body}</body></html>"
    ).write_pdf()
