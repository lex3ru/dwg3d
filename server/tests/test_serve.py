"""Запуск приложения: сколько процессов (R-051), объекты запуска — вне сборки мусора
(DWG3D-10)."""

import gc
import subprocess
import sys
from pathlib import Path

from app import main
from app.__main__ import serve_workers


def test_windows_serves_with_one_process() -> None:
    # несколько процессов uvicorn в Windows делят один слушающий сокет, и процесс застревает
    # в accept: его запросы ждут, пока к нему не придёт новое соединение (R-051)
    assert serve_workers(4, "win32") == 1
    assert serve_workers(1, "win32") == 1


def test_linux_serves_with_requested_processes() -> None:
    assert serve_workers(4, "linux") == 4
    assert serve_workers(2, "linux") == 2


def test_served_app_leaves_startup_objects_out_of_gc(app, monkeypatch) -> None:
    # полная сборка мусора обходит только то, что создано после запуска: в CI паузы сборки по
    # 150–250 мс попадали в замер зоны обзора (8.2, DWG3D-10, ADR-0010). Приложение — уже
    # собранное: второй create_app в одном процессе удвоил бы подписки модулей (R-013)
    monkeypatch.setattr(main, "create_app", lambda: app)
    gc.unfreeze()
    try:
        assert main.serve_app() is app
        assert gc.get_freeze_count() > 10_000
    finally:
        gc.unfreeze()


def test_served_app_freezes_report_libraries() -> None:
    # библиотеки отчётов иначе грузятся при первом отчёте — уже после заморозки, и их объекты
    # обходила бы каждая полная сборка (DWG3D-10, ADR-0010). В Windows нет Pango — PDF там не
    # печатается и weasyprint не грузится. Отдельный процесс: в этом их уже загрузили другие тесты
    names = ["openpyxl"] + ([] if sys.platform == "win32" else ["weasyprint"])
    code = "\n".join([
        "import gc, sys",
        "from app import main",
        "main.create_app = lambda: None",
        "main.serve_app()",
        "live = {id(o) for o in gc.get_objects()}",
        "for name in sys.argv[1:]:",
        "    mod = sys.modules.get(name)",
        "    print(name, mod is not None and id(vars(mod)) not in live)",
    ])
    r = subprocess.run([sys.executable, "-c", code, *names], cwd=Path(__file__).parents[1],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == [x for name in names for x in (name, "True")]
