"""Tkinter front end: pick a PDF, tune options, convert, look at the result."""
from __future__ import annotations

import math
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import ezdxf
import pymupdf
from ezdxf import path as dxfpath

from .cli import TWIN_FILL_LAYER, TWIN_WALL_LAYER, parse_scale
from .convert import Options, Report, convert_pdf, page_is_vector, parse_pages

SCALES = ["1", "1:20", "1:25", "1:50", "1:100", "1:200", "1:500"]
MODE_LABELS = {"auto": "Авто", "vector": "Векторный", "raster": "Растровый (скан)"}


def build_options(*, scale: str, mode: str, fills: bool, text: bool, lineweights: bool,
                  tol: str, dpi: str, min_len: str, simplify: str,
                  twin: bool = False, wall_layer: str = TWIN_WALL_LAYER,
                  fill_layer: str = TWIN_FILL_LAYER) -> Options:
    """Validate form strings and make Options; raises ValueError with a readable message."""
    try:
        sc = parse_scale(scale)
    except (ValueError, ZeroDivisionError):
        raise ValueError(f"Масштаб «{scale}» не понят. Пример: 100 или 1:100")
    if sc <= 0:
        raise ValueError("Масштаб должен быть больше нуля")

    def num(name: str, raw: str, lo: float) -> float:
        try:
            v = float(raw.replace(",", "."))
        except ValueError:
            raise ValueError(f"{name}: «{raw}» — не число")
        if v < lo:
            raise ValueError(f"{name}: должно быть не меньше {lo}")
        return v

    if twin and not wall_layer.strip():
        raise ValueError("Укажите имя слоя для линий (например, A-WALL)")
    return Options(
        drop_frame=twin,
        stroke_layer=wall_layer.strip() if twin else None,
        fill_layer=(fill_layer.strip() or None) if twin else None,
        scale=sc, mode=mode, fills=fills, text=text, lineweights=lineweights,
        tol=num("Допуск дуг", tol, 0.0001), dpi=int(num("Разрешение", dpi, 50)),
        min_len=num("Мин. длина линии", min_len, 0), simplify=num("Упрощение", simplify, 0.05),
    )


def dxf_shapes(doc) -> tuple[list, tuple[float, float, float, float] | None]:
    """Flatten a DXF modelspace into drawable primitives.

    Returns ([("line", color, [(x, y), ...]), ("fill", color, [...]), ("text", color, (x, y, h, rot, str))], bbox)
    """
    shapes: list = []
    xs: list[float] = []
    ys: list[float] = []

    def color_of(e) -> str:
        layer = doc.layers.get(e.dxf.layer) if e.dxf.layer in doc.layers else None
        if e.dxf.hasattr("true_color"):
            r, g, b = ezdxf.colors.int2rgb(e.dxf.true_color)
        elif layer is not None and layer.dxf.hasattr("true_color"):
            r, g, b = ezdxf.colors.int2rgb(layer.dxf.true_color)
        else:
            return "#000000"
        return f"#{r:02x}{g:02x}{b:02x}"

    def keep(pts):
        for x, y in pts:
            xs.append(x)
            ys.append(y)

    for e in doc.modelspace():
        t = e.dxftype()
        try:
            if t in ("LINE", "ARC", "CIRCLE", "LWPOLYLINE", "SPLINE"):
                pts = [(v.x, v.y) for v in dxfpath.make_path(e).flattening(0.05)]
                if len(pts) >= 2:
                    shapes.append(("line", color_of(e), pts))
                    keep(pts)
            elif t == "HATCH":
                for p in e.paths:
                    if isinstance(p, ezdxf.entities.PolylinePath):
                        pts = [(v[0], v[1]) for v in p.vertices]
                        if len(pts) >= 3:
                            shapes.append(("fill", color_of(e), pts))
                            keep(pts)
            elif t == "TEXT":
                x, y = e.dxf.insert.x, e.dxf.insert.y
                shapes.append(("text", color_of(e), (x, y, e.dxf.height, e.dxf.get("rotation", 0.0), e.dxf.text)))
                keep([(x, y)])
        except Exception:  # a broken entity must not kill the preview
            continue
    bbox = (min(xs), min(ys), max(xs), max(ys)) if xs else None
    return shapes, bbox


class ZoomCanvas(tk.Canvas):
    """Canvas showing dxf_shapes() with wheel zoom and drag pan (y axis up)."""

    def __init__(self, master, **kw):
        super().__init__(master, background="white", highlightthickness=0, **kw)
        self.shapes: list = []
        self.bbox = None
        self.k = 1.0
        self.ox = self.oy = 0.0
        self.bind("<Configure>", lambda e: self.fit())
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<MouseWheel>", lambda e: self._zoom(e.x, e.y, 1.25 if e.delta > 0 else 0.8))
        self.bind("<Button-4>", lambda e: self._zoom(e.x, e.y, 1.25))
        self.bind("<Button-5>", lambda e: self._zoom(e.x, e.y, 0.8))
        self.bind("<Double-Button-1>", lambda e: self.fit())

    def show(self, shapes, bbox) -> None:
        self.shapes, self.bbox = shapes, bbox
        self.fit()

    def fit(self) -> None:
        w, h = max(self.winfo_width(), 50), max(self.winfo_height(), 50)
        if self.bbox:
            x0, y0, x1, y1 = self.bbox
            bw, bh = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
            self.k = 0.95 * min(w / bw, h / bh)
            self.ox = w / 2 - (x0 + x1) / 2 * self.k
            self.oy = h / 2 + (y0 + y1) / 2 * self.k
        self.redraw()

    def _xy(self, x, y):
        return x * self.k + self.ox, -y * self.k + self.oy

    def redraw(self) -> None:
        self.delete("all")
        for kind, col, data in self.shapes:
            if kind == "text":
                x, y, h, rot, s = data
                px = max(1, int(h * self.k * 1.3))
                if px >= 4:
                    self.create_text(*self._xy(x, y), text=s, fill=col, anchor="sw", angle=rot,
                                     font=("DejaVu Sans", -px))
                continue
            flat = [c for p in data for c in self._xy(*p)]
            if kind == "fill":
                self.create_polygon(flat, fill=col, outline="")
            else:
                self.create_line(flat, fill=col)

    def _press(self, e):
        self._last = (e.x, e.y)

    def _drag(self, e):
        self.ox += e.x - self._last[0]
        self.oy += e.y - self._last[1]
        self._last = (e.x, e.y)
        self.redraw()

    def _zoom(self, px, py, f):
        self.ox = px - (px - self.ox) * f
        self.oy = py - (py - self.oy) * f
        self.k *= f
        self.redraw()


class App(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=8)
        self.master = master
        master.title("PDF → DXF")
        master.geometry("1180x900")
        master.minsize(900, 700)
        self.pack(fill="both", expand=True)

        self.pdf_path: Path | None = None
        self.results: list[tuple[Path, Report]] = []
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self._preview_img: tk.PhotoImage | None = None
        self._preview_job = None

        v = self.v = {
            "pdf": tk.StringVar(), "out": tk.StringVar(), "pages": tk.StringVar(value="1"),
            "scale": tk.StringVar(value="1"), "mode": tk.StringVar(value="auto"),
            "fills": tk.BooleanVar(value=True), "text": tk.BooleanVar(value=True),
            "lineweights": tk.BooleanVar(value=True), "tol": tk.StringVar(value="0.02"),
            "dpi": tk.StringVar(value="300"), "min_len": tk.StringVar(value="1.0"),
            "simplify": tk.StringVar(value="0.4"),
            "twin": tk.BooleanVar(value=True), "wall_layer": tk.StringVar(value=TWIN_WALL_LAYER),
            "fill_layer": tk.StringVar(value=TWIN_FILL_LAYER), "detected": tk.StringVar(value="—"),
            "result_file": tk.StringVar(),
        }
        self._build(v)
        self.after(100, self._poll)
        v["pages"].trace_add("write", lambda *_: self._schedule_preview())

    # -- layout -------------------------------------------------------------
    def _build(self, v) -> None:
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)
        left = ttk.Frame(paned, padding=(0, 0, 8, 0))
        right = ttk.Frame(paned)
        paned.add(left, weight=0)
        paned.add(right, weight=1)

        f = ttk.LabelFrame(left, text="Файлы", padding=6)
        f.pack(fill="x")
        ttk.Label(f, text="PDF").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=v["pdf"], width=34, state="readonly").grid(row=1, column=0, sticky="ew")
        ttk.Button(f, text="Открыть…", command=self.choose_pdf).grid(row=1, column=1, padx=(4, 0))
        ttk.Label(f, text="DXF").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(f, textvariable=v["out"], width=34).grid(row=3, column=0, sticky="ew")
        ttk.Button(f, text="Обзор…", command=self.choose_out).grid(row=3, column=1, padx=(4, 0))
        f.columnconfigure(0, weight=1)

        f = ttk.LabelFrame(left, text="Чертёж", padding=6)
        f.pack(fill="x", pady=(8, 0))
        ttk.Label(f, text="Страницы").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=v["pages"], width=12).grid(row=0, column=1, sticky="w")
        ttk.Label(f, text="1, 2-4 или all", foreground="gray").grid(row=0, column=2, sticky="w", padx=6)
        ttk.Label(f, text="Масштаб").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(f, textvariable=v["scale"], values=SCALES, width=10).grid(row=1, column=1, sticky="w", pady=(6, 0))
        ttk.Label(f, text="1:100 → размеры в модели ×100", foreground="gray").grid(row=1, column=2, sticky="w", padx=6, pady=(6, 0))
        ttk.Label(f, text="Тип графики").grid(row=2, column=0, sticky="nw", pady=(6, 0))
        mf = ttk.Frame(f)
        mf.grid(row=2, column=1, columnspan=2, sticky="w", pady=(6, 0))
        for key, label in MODE_LABELS.items():
            ttk.Radiobutton(mf, text=label, value=key, variable=v["mode"]).pack(anchor="w")
        ttk.Label(f, textvariable=v["detected"], foreground="gray").grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))

        f = ttk.LabelFrame(left, text="Переносить", padding=6)
        f.pack(fill="x", pady=(8, 0))
        ttk.Checkbutton(f, text="Заливки (HATCH)", variable=v["fills"]).pack(anchor="w")
        ttk.Checkbutton(f, text="Текст", variable=v["text"]).pack(anchor="w")
        ttk.Checkbutton(f, text="Толщины линий", variable=v["lineweights"]).pack(anchor="w")

        f = ttk.LabelFrame(left, text="Импорт в цифровой двойник", padding=6)
        f.pack(fill="x", pady=(8, 0))
        ttk.Checkbutton(f, text="Слои под конвейер и без рамки листа", variable=v["twin"],
                        command=self._twin_toggle).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(f, text="Линии → слой").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.e_wall = ttk.Entry(f, textvariable=v["wall_layer"], width=16)
        self.e_wall.grid(row=1, column=1, padx=4, pady=(4, 0))
        ttk.Label(f, text="должен содержать WALL / Стен", foreground="gray").grid(row=1, column=2, sticky="w", pady=(4, 0))
        ttk.Label(f, text="Заливки → слой").grid(row=2, column=0, sticky="w")
        self.e_fill = ttk.Entry(f, textvariable=v["fill_layer"], width=16)
        self.e_fill.grid(row=2, column=1, padx=4)
        ttk.Label(f, text="игнорируется конвейером", foreground="gray").grid(row=2, column=2, sticky="w")
        ttk.Label(f, text="В PDF нет слоёв, поэтому все линии идут на один слой стен.\n"
                          "Для импорта нужен реальный масштаб чертежа (1:200 и т. п.).",
                  foreground="gray", justify="left").grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))

        f = ttk.LabelFrame(left, text="Дополнительно", padding=6)
        f.pack(fill="x", pady=(8, 0))
        for r, (label, key, hint) in enumerate([
            ("Допуск дуг, мм", "tol", "кривая → дуга"),
            ("Разрешение, dpi", "dpi", "растр"),
            ("Мин. длина, мм", "min_len", "растр: мусор"),
            ("Упрощение, мм", "simplify", "растр: ломаные"),
        ]):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=1)
            ttk.Entry(f, textvariable=v[key], width=8).grid(row=r, column=1, padx=4)
            ttk.Label(f, text=hint, foreground="gray").grid(row=r, column=2, sticky="w")

        bf = ttk.Frame(left)
        bf.pack(fill="x", pady=(10, 0))
        self.btn_run = ttk.Button(bf, text="Конвертировать", command=self.run)
        self.btn_run.pack(side="left", fill="x", expand=True)
        self.btn_open = ttk.Button(bf, text="Открыть DXF", command=self.open_result, state="disabled")
        self.btn_open.pack(side="left", padx=(6, 0))
        self.progress = ttk.Progressbar(left, mode="indeterminate")
        self.progress.pack(fill="x", pady=(6, 0))

        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill="both", expand=True)
        self.preview = tk.Canvas(self.tabs, background="#e9e9e9", highlightthickness=0)
        self.preview.bind("<Configure>", lambda e: self._schedule_preview())
        self.tabs.add(self.preview, text="PDF")
        rf = ttk.Frame(self.tabs)
        top = ttk.Frame(rf)
        top.pack(fill="x")
        ttk.Label(top, text="Файл:").pack(side="left", padx=4)
        self.result_box = ttk.Combobox(top, textvariable=v["result_file"], state="readonly", width=40)
        self.result_box.pack(side="left", pady=2)
        self.result_box.bind("<<ComboboxSelected>>", lambda e: self._show_result())
        ttk.Label(top, text="колесо — масштаб, мышь — сдвиг, 2×клик — вписать",
                  foreground="gray").pack(side="left", padx=8)
        self.result = ZoomCanvas(rf)
        self.result.pack(fill="both", expand=True)
        self.tabs.add(rf, text="Результат DXF")

        self.log = tk.Text(right, height=7, wrap="word", state="disabled", background="#fafafa")
        self.log.pack(fill="x", pady=(8, 0))
        self.write_log("Откройте PDF с чертежом.")

    def _twin_toggle(self) -> None:
        state = "normal" if self.v["twin"].get() else "disabled"
        self.e_wall.configure(state=state)
        self.e_fill.configure(state=state)

    # -- helpers ------------------------------------------------------------
    def write_log(self, msg: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def choose_pdf(self) -> None:
        p = filedialog.askopenfilename(title="PDF с чертежом", filetypes=[("PDF", "*.pdf"), ("Все файлы", "*")])
        if p:
            self.load_pdf(Path(p))

    def load_pdf(self, path: Path) -> None:
        try:
            with pymupdf.open(path) as pdf:
                total = len(pdf)
        except Exception as e:
            messagebox.showerror("PDF", f"Не удалось открыть файл:\n{e}")
            return
        self.pdf_path = path
        self.v["pdf"].set(str(path))
        self.v["out"].set(str(path.with_suffix(".dxf")))
        self.v["pages"].set("1")
        self.write_log(f"Открыт {path.name}, страниц: {total}")
        self.tabs.select(self.preview)
        self._schedule_preview()

    def choose_out(self) -> None:
        p = filedialog.asksaveasfilename(title="Куда сохранить", defaultextension=".dxf",
                                         initialfile=Path(self.v["out"].get() or "out.dxf").name,
                                         filetypes=[("DXF", "*.dxf")])
        if p:
            self.v["out"].set(p)

    def _first_page(self) -> int | None:
        try:
            with pymupdf.open(self.pdf_path) as pdf:
                idx = parse_pages(self.v["pages"].get() or "1", len(pdf))
            return idx[0] if idx else None
        except Exception:
            return None

    def _schedule_preview(self) -> None:
        if self._preview_job:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(200, self._draw_preview)

    def _draw_preview(self) -> None:
        self._preview_job = None
        self.preview.delete("all")
        if not self.pdf_path:
            return
        n = self._first_page()
        if n is None:
            self.v["detected"].set("Страницы указаны неверно")
            return
        w, h = max(self.preview.winfo_width(), 50), max(self.preview.winfo_height(), 50)
        with pymupdf.open(self.pdf_path) as pdf:
            page = pdf[n]
            zoom = min(w / page.rect.width, h / page.rect.height) * 0.98
            png = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).tobytes("png")
            kind = "векторная" if page_is_vector(page) else "растровая (скан)"
        self.v["detected"].set(f"Страница {n + 1}: {kind} графика")
        self._preview_img = tk.PhotoImage(data=png)
        self.preview.create_image(w // 2, h // 2, image=self._preview_img)

    # -- conversion ---------------------------------------------------------
    def run(self) -> None:
        if self.busy:
            return
        if not self.pdf_path:
            messagebox.showinfo("PDF → DXF", "Сначала откройте PDF.")
            return
        v = self.v
        try:
            opts = build_options(
                scale=v["scale"].get(), mode=v["mode"].get(), fills=v["fills"].get(), text=v["text"].get(),
                lineweights=v["lineweights"].get(), tol=v["tol"].get(), dpi=v["dpi"].get(),
                min_len=v["min_len"].get(), simplify=v["simplify"].get(),
                twin=v["twin"].get(), wall_layer=v["wall_layer"].get(), fill_layer=v["fill_layer"].get(),
            )
        except ValueError as e:
            messagebox.showerror("Настройки", str(e))
            return
        out = Path(v["out"].get().strip() or self.pdf_path.with_suffix(".dxf"))
        pages, src = v["pages"].get() or "1", self.pdf_path
        self.busy = True
        self.btn_run.configure(state="disabled")
        self.btn_open.configure(state="disabled")
        self.progress.start(12)
        self.write_log("Конвертация…")

        def work():
            try:
                self.events.put(("done", convert_pdf(src, out, pages, opts)))
            except Exception as e:
                self.events.put(("error", e))

        threading.Thread(target=work, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                self.busy = False
                self.progress.stop()
                self.btn_run.configure(state="normal")
                if kind == "error":
                    self.write_log(f"Ошибка: {payload}")
                    messagebox.showerror("Конвертация", str(payload))
                else:
                    self._finish(payload)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _finish(self, results: list[tuple[Path, Report]]) -> None:
        self.results = results
        for path, rep in results:
            stats = ", ".join(f"{k}: {n}" for k, n in sorted(rep.counts.items())) or "пусто"
            self.write_log(f"стр. {rep.page} [{rep.mode}] → {path}\n    {stats}")
            for w in rep.warnings:
                self.write_log(f"    ! {w}")
        self.btn_open.configure(state="normal")
        self.result_box.configure(values=[str(p) for p, _ in results])
        self.v["result_file"].set(str(results[0][0]))
        self._show_result()
        self.tabs.select(self.result.master)

    def _show_result(self) -> None:
        p = self.v["result_file"].get()
        if not p:
            return
        try:
            shapes, bbox = dxf_shapes(ezdxf.readfile(p))
        except Exception as e:
            self.write_log(f"Предпросмотр недоступен: {e}")
            return
        self.result.show(shapes, bbox)

    def open_result(self) -> None:
        p = self.v["result_file"].get()
        if not p:
            return
        if sys.platform == "win32":
            os.startfile(p)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])


def setup_fonts() -> None:
    """Tk may pick an ugly bitmap font on Linux; prefer a scalable one when installed."""
    families = set(tkfont.families())
    family = next((f for f in ("Ubuntu", "DejaVu Sans", "Noto Sans", "Segoe UI") if f in families), None)
    if not family:
        return
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        tkfont.nametofont(name).configure(family=family, size=10)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass
    setup_fonts()
    app = App(root)
    if argv and Path(argv[0]).is_file():
        app.load_pdf(Path(argv[0]))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
