"""Запуск приложения: сколько процессов (R-051), объекты запуска — вне сборки мусора
(DWG3D-10), очередь запросов и проверка живости процессов под пиком (R-036)."""

import asyncio
import gc
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app import __main__ as cli
from app import main
from app.__main__ import serve_workers
from app.core.admission import Admission
from app.core.config import config
from app.core.db import OUTSIDE_QUEUE, connections_needed, engine


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


def burst(limit: int, n: int, app: Any, scope_type: str = "http") -> list[Any]:
    """n запросов разом через Admission(limit) к ASGI-приложению app; что каждый отправил
    (или исключение, если запрос упал)."""

    async def run() -> list[Any]:
        gate = Admission(app, limit=limit)

        async def one() -> list[str]:
            sent: list[str] = []

            async def send(message: dict[str, Any]) -> None:
                sent.append(message["type"])

            async def receive() -> dict[str, Any]:
                return {"type": "http.request"}

            await gate({"type": scope_type}, receive, send)
            return sent

        return await asyncio.gather(*(one() for _ in range(n)), return_exceptions=True)

    return asyncio.run(run())


def test_r036_admission_lets_through_no_more_than_limit() -> None:
    """Под пиком запросов одновременно не больше соединений пула, лишние ждут очереди, а не
    таймаута пула с ответом 500 (R-036, ADR-0020) — и все дожидаются ответа."""
    now, most = 0, 0

    async def app(scope: Any, receive: Any, send: Any) -> None:
        nonlocal now, most
        now += 1
        most = max(most, now)
        await asyncio.sleep(0.01)
        now -= 1
        await send({"type": "http.response.start"})
        await send({"type": "http.response.body"})

    done = burst(3, 20, app)
    assert most == 3
    assert done == [["http.response.start", "http.response.body"]] * 20


def test_r036_admission_frees_the_place_when_the_answer_starts() -> None:
    """Соединение вернулось в пул до ответа: долгая отдача тела (файл, выгрузка) места в
    очереди не держит. Упавший запрос место тоже освобождает. Сокеты очередь не проходят."""
    order: list[str] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "websocket":
            return
        me = str(sum(1 for o in order if " " not in o) + 1)
        order.append(me)
        if me == "2":
            raise RuntimeError("сбой")
        await send({"type": "http.response.start"})
        if me == "1":
            await asyncio.sleep(0.05)  # тело ещё отдаётся
            order.append("1 тело")
            await send({"type": "http.response.body"})

    done = burst(1, 3, app)
    assert order == ["1", "2", "3", "1 тело"]
    assert sum(isinstance(d, RuntimeError) for d in done) == 1
    assert burst(1, 2, app, "websocket") == [[], []]


def test_r036_requests_at_once_equal_pool_size(app) -> None:  # type: ignore[no-untyped-def]
    """Очередь пускает APP_DB_POOL запросов — столько соединений в пуле: запрос держит одно
    (вход и маршрут — в одной сессии). Сверх них — запас сокетам изменений, которые проверяют
    сеанс мимо очереди: под пиком сокет ждал соединение 30 с и получал отказ (R-036)."""
    pool = engine().pool
    assert pool.size() == config().db_pool  # type: ignore[attr-defined]
    assert pool._max_overflow == OUTSIDE_QUEUE > 0  # type: ignore[attr-defined]
    gates = [m for m in app.user_middleware if m.cls is Admission]
    assert len(gates) == 1 and gates[0].kwargs == {"limit": config().db_pool}


def served(monkeypatch) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """С какими настройками `python -m app serve` запускает uvicorn."""
    import uvicorn

    got: dict[str, Any] = {}
    monkeypatch.setattr(sys, "argv", ["app", "serve"])
    monkeypatch.setattr(cli, "migrate", lambda: None)
    monkeypatch.setattr(cli, "seed", lambda: None)
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: got.update(kw))
    with pytest.raises(SystemExit):
        cli.main()
    return got


def test_r036_busy_process_is_not_killed_as_hung(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Процесс, занятый долгим счётом, отвечает на проверку живости uvicorn не сразу: за 5 с
    по умолчанию супервизор убивал его вместе с запросами (R-036)."""
    assert served(monkeypatch)["timeout_worker_healthcheck"] >= 60


def test_r036_idle_connection_outlives_caddy(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Простаивающее соединение Caddy держит до 2 мин (reverse_proxy по умолчанию), uvicorn —
    5 с: Caddy отправлял запрос в соединение, которое uvicorn как раз закрыл, и POST получал
    502. На стенде под пиком — «socket hang up» у 2 из 200 запросов (R-036)."""
    assert served(monkeypatch)["timeout_keep_alive"] > 120


COMPOSE = Path(__file__).resolve().parents[2] / "deploy" / "compose.yml"


def test_r036_connections_fit_postgres_of_the_installation() -> None:
    """Под пиком установке нужно соединений не больше, чем пускает PostgreSQL из
    deploy/compose.yml, — с запасом, и при 8 процессах, которые INSTALL.md разрешает на восьми
    ядрах: иначе «too many clients» и 500 (R-036, ADR-0020)."""
    text = COMPOSE.read_text(encoding="utf-8")

    def setting(pattern: str) -> int:
        found = re.search(pattern, text)
        assert found, pattern
        return int(found[1])

    limit = setting(r"max_connections=(\d+)")
    assert setting(r"APP_DB_POOL:-(\d+)") == config().db_pool
    assert connections_needed(setting(r"APP_WORKERS:-(\d+)")) <= limit // 2
    assert connections_needed(8) <= limit * 0.8


def test_r036_serve_warns_when_connections_do_not_fit(monkeypatch, caplog) -> None:  # type: ignore[no-untyped-def]
    with caplog.at_level("WARNING", logger="app"):
        cli.check_connections(4)
    assert not caplog.text
    monkeypatch.setattr(config(), "db_pool", 40)
    with caplog.at_level("WARNING", logger="app"):
        cli.check_connections(4)
    assert "max_connections" in caplog.text and "APP_DB_POOL" in caplog.text
