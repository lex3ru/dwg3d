"""Equipment specification: placed items counted per catalog position.

  equipment(project_id)  one project, with the count per floor
  equipment(None)        all projects, with the count per project

Items whose floor is not in the current build count under "без этажа".
Sums are per currency; items without a price are listed and counted but
left out of the sums. `to_xlsx()` writes the same table with formulas
(quantity × price, totals), so edits in Excel recalculate.
"""
from __future__ import annotations

import io
from collections import defaultdict
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import CatalogCategory, CatalogItem, Floor, Placement, Project

NO_FLOOR = "без этажа"


def _project_name(p: Project) -> str:
    return p.name or p.filename.rsplit(".", 1)[0]


def equipment(s: Session, project_id: str | None = None) -> dict:
    q = (select(Placement.project_id, Placement.item_id, Floor.name, Floor.candidate, Floor.level,
                func.count())
         .join(Project, Project.id == Placement.project_id)
         .outerjoin(Floor, Floor.id == Placement.floor_id)
         .where(Project.deleted_at.is_(None))
         .group_by(Placement.project_id, Placement.item_id, Floor.name, Floor.candidate, Floor.level))
    if project_id is not None:
        q = q.where(Placement.project_id == project_id)
    counts = s.execute(q).all()
    items = {i.id: i for i in s.scalars(select(CatalogItem).where(CatalogItem.id.in_({c[1] for c in counts})))}
    cats = {c.id: c for c in s.scalars(select(CatalogCategory))}
    projects = {p.id: p for p in s.scalars(select(Project).where(Project.id.in_({c[0] for c in counts} |
                                                                                 ({project_id} if project_id else set()))))}

    rows: dict[str, dict] = {}
    floor_order: dict[str, tuple] = {}
    for pid, iid, fname, cand, level, n in counts:
        it, key = items.get(iid), iid
        r = rows.get(key)
        if r is None:
            cat = cats.get(it.category_id) if it else None
            r = rows[key] = {
                "item": iid, "name": it.name if it else f"Неизвестный предмет ({iid})",
                "category": cat.name if cat else "", "category_sort": cat.sort if cat else 1e9,
                "sort": it.sort if it else 1e9, "article": (it.article if it else None) or "",
                "supplier": (it.supplier if it else None) or "",
                "price": float(it.price) if it and it.price is not None else None,
                "currency": it.currency if it and it.price is not None else None,
                "qty": 0, "by": defaultdict(int)}
        r["qty"] += n
        if project_id is not None:
            label = (fname or cand) if cand else NO_FLOOR
            floor_order.setdefault(label, (0 if cand else 1, level if level is not None else 0, label))
            r["by"][label] += n
        else:
            r["by"][pid] += n

    out_rows = sorted(rows.values(), key=lambda r: (r["category_sort"], r["sort"], r["name"]))
    totals: dict[str, float] = defaultdict(float)
    for r in out_rows:
        r["sum"] = round(r["price"] * r["qty"], 2) if r["price"] is not None else None
        if r["sum"] is not None:
            totals[r["currency"]] += r["sum"]
        r["by"] = dict(r["by"])
        del r["category_sort"], r["sort"]
    if project_id is not None:
        p = projects.get(project_id)
        columns = [label for label in sorted(floor_order, key=lambda k: floor_order[k])]
        head = {"project": {"id": project_id, "name": _project_name(p) if p else project_id}}
    else:
        # projects with most items first
        per = defaultdict(int)
        for r in out_rows:
            for pid, n in r["by"].items():
                per[pid] += n
        order = sorted(per, key=lambda pid: (-per[pid], _project_name(projects[pid])))
        columns = order
        names = [_project_name(projects[pid]) for pid in order]
        # buildings uploaded from the same drawing share a name: tell the columns apart
        head = {"projects": [{"id": pid, "name": f"{n} · {pid[:6]}" if names.count(n) > 1 else n}
                             for pid, n in zip(order, names, strict=True)]}
    return {**head, "columns": columns, "rows": out_rows,
            "totals": {k: round(v, 2) for k, v in totals.items()},
            "qty": sum(r["qty"] for r in out_rows),
            "unpriced": sum(1 for r in out_rows if r["price"] is None),
            "generated": datetime.now().astimezone().isoformat(timespec="minutes")}


def to_xlsx(rep: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    single = "project" in rep
    ws.title = "Спецификация" if single else "Сводная"
    col_names = [p["name"] for p in rep["projects"]] if not single else rep["columns"]
    title = (f"Спецификация оборудования: {rep['project']['name']}" if single
             else f"Сводная спецификация оборудования по проектам ({len(rep['projects'])})")
    ws.append([title])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([f"Сформирована {rep['generated'][:16].replace('T', ' ')}"])
    ws.append([])
    fixed = ["№", "Категория", "Наименование", "Артикул", "Поставщик", "Ед."]
    head = fixed + col_names + ["Кол-во", "Цена", "Сумма", "Валюта"]
    ws.append(head)
    hr = ws.max_row
    for c in ws[hr]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="E9ECEF")
        c.alignment = Alignment(wrap_text=True, vertical="top")
    first = hr + 1
    nb = len(col_names)
    qty_col = len(fixed) + nb + 1
    L = get_column_letter
    keys = rep["columns"]
    for k, r in enumerate(rep["rows"], start=1):
        row = first + k - 1
        by = [r["by"].get(key) or None for key in keys]
        qty = f"=SUM({L(len(fixed) + 1)}{row}:{L(len(fixed) + nb)}{row})" if nb else r["qty"]
        price = r["price"]
        total = f"={L(qty_col)}{row}*{L(qty_col + 1)}{row}" if price is not None else None
        ws.append([k, r["category"], r["name"], r["article"], r["supplier"], "шт."] + by +
                  [qty, price, total, r["currency"] or ""])
    last = ws.max_row
    if rep["rows"]:
        ws.append([])
        ws.append(["", "", "Итого", "", "", ""] + [f"=SUM({L(len(fixed) + 1 + i)}{first}:{L(len(fixed) + 1 + i)}{last})"
                                                   for i in range(nb)] +
                  [f"=SUM({L(qty_col)}{first}:{L(qty_col)}{last})", None,
                   f"=SUM({L(qty_col + 2)}{first}:{L(qty_col + 2)}{last})" if len(rep["totals"]) <= 1 else None,
                   next(iter(rep["totals"]), "")])
        for c in ws[ws.max_row]:
            c.font = Font(bold=True)
        if len(rep["totals"]) > 1:
            for cur, v in rep["totals"].items():
                ws.append(["", "", f"Итого, {cur}"] + [None] * (qty_col + 1 - 3) + [v, cur])
        if rep["unpriced"]:
            ws.append(["", "", f"Без цены: {rep['unpriced']} поз. (не вошли в сумму)"])
    widths = [5, 24, 44, 16, 22, 6] + [10] * nb + [9, 12, 14, 8]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[L(i)].width = w
    for row in ws.iter_rows(min_row=first, max_row=ws.max_row):
        for c in row:
            if c.column in (qty_col + 1, qty_col + 2):
                c.number_format = "#,##0.00"
    ws.freeze_panes = ws.cell(row=first, column=4)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

