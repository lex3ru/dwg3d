"""Запуск приложения: сколько процессов (R-051)."""

from app.__main__ import serve_workers


def test_windows_serves_with_one_process() -> None:
    # несколько процессов uvicorn в Windows делят один слушающий сокет, и процесс застревает
    # в accept: его запросы ждут, пока к нему не придёт новое соединение (R-051)
    assert serve_workers(4, "win32") == 1
    assert serve_workers(1, "win32") == 1


def test_linux_serves_with_requested_processes() -> None:
    assert serve_workers(4, "linux") == 4
    assert serve_workers(2, "linux") == 2
