"""Запуск приложения: сколько процессов (R-051), объекты запуска — вне сборки мусора
(DWG3D-10)."""

import gc

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
