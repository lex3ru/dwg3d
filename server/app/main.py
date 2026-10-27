"""Сборка приложения: модули из app.modules.INSTALLED, общие обработчики, интерфейс."""

import asyncio
import gc
import importlib
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm.exc import StaleDataError
from starlette.concurrency import run_in_threadpool

from app.core import events, search
from app.core.actor import Actor
from app.core.auth import CurrentActor
from app.core.config import config
from app.core.db import DB, transaction
from app.core.errors import AppError, stale
from app.core.module import Module
from app.modules import INSTALLED
from app.modules.access import api as access

log = logging.getLogger("app")
_SAFE = {"GET", "HEAD", "OPTIONS"}
PING_AFTER = 25  # с: тишина в сокете изменений, после которой сервер шлёт ping (6.1 п. 8)
# ошибки базы от одновременной работы (8.3 п. 2): значение уже занял, строку убрал другой
# сеанс, база разорвала взаимоблокировку или не смогла упорядочить транзакции
CONFLICTS = {"23505", "23503", "40P01", "40001"}


def installed_modules() -> list[Module]:
    return [importlib.import_module(f"app.modules.{name}.module").module
            for name in INSTALLED]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    events.hub.start()
    yield
    events.hub.stop()


def create_app() -> FastAPI:
    logging.basicConfig(level=config().log_level,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = FastAPI(title="Планировка и учёт имущества", lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)

    for module in installed_modules():
        for router in module.routers:
            app.include_router(router)
        if module.setup:
            module.setup(app)

    @app.middleware("http")
    async def guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]
                    ) -> Response:
        # запросы, меняющие данные, — только из своего интерфейса: чужой сайт не может
        # прислать этот заголовок без разрешения CORS, которого нет
        if (request.method not in _SAFE and request.url.path.startswith("/api/")
                and request.headers.get("x-requested-with") != "app"):
            return JSONResponse(AppError("Запрос отклонён: нет заголовка X-Requested-With.",
                                         code="csrf", status=403).body(), status_code=403)
        return await call_next(request)

    @app.exception_handler(AppError)
    async def app_error(_: Request, e: AppError) -> JSONResponse:
        return JSONResponse(jsonable_encoder(e.body()), status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, e: RequestValidationError) -> JSONResponse:
        errors = e.errors()
        field = ".".join(str(p) for p in errors[0]["loc"][1:]) if errors else None
        return JSONResponse(AppError(f"Проверьте поле «{field}»." if field else
                                     "Запрос заполнен неверно.", field=field).body(),
                            status_code=422)

    # одновременная работа, которую не развела очередь (ADR-0003), — «обновите и повторите»,
    # а не «внутренняя ошибка»; прочие ошибки базы — дальше, в crash
    @app.exception_handler(DBAPIError)
    async def database(request: Request, e: DBAPIError) -> JSONResponse:
        if getattr(e.orig, "sqlstate", None) not in CONFLICTS:
            raise e
        log.warning("%s %s: conflict %s", request.method, request.url.path, e.orig)
        return await app_error(request, stale("Эти данные"))

    @app.exception_handler(StaleDataError)
    async def stale_data(request: Request, e: StaleDataError) -> JSONResponse:
        log.warning("%s %s: conflict %s", request.method, request.url.path, e)
        return await app_error(request, stale("Эти данные"))

    @app.exception_handler(Exception)
    async def crash(request: Request, e: Exception) -> JSONResponse:
        ref = uuid.uuid4().hex[:8]
        log.error("%s %s failed, ref %s", request.method, request.url.path, ref, exc_info=e)
        return JSONResponse(AppError(
            f"Внутренняя ошибка сервера. Сообщите администратору код {ref} и время "
            f"{datetime.now(UTC):%Y-%m-%d %H:%M} UTC.", code="internal", status=500).body(),
            status_code=500)

    @app.get("/api/health", tags=["system"])
    def health(session: DB) -> dict[str, Any]:
        session.execute(text("SELECT 1"))
        return {"ok": True}

    @app.get("/api/search", tags=["system"])
    def find(q: str, actor: CurrentActor, session: DB
             ) -> dict[str, Any]:
        return {"items": [hit.__dict__ for hit in search.search(session, actor, q)]}

    @app.websocket("/api/ws")
    async def changes(ws: WebSocket) -> None:
        # сеанс — в пуле потоков: запрос к базе прямо в цикле событий остановил бы, пока он
        # ждёт, все запросы этого процесса (R-051)
        actor = await run_in_threadpool(_actor_for, ws.cookies.get(access.COOKIE))
        if actor is None:
            await ws.close(code=4401)
            return
        await ws.accept()

        def allowed(message: dict[str, Any]) -> bool:
            if actor.is_admin:
                return True
            return any(ref.startswith("building:") and ref[9:] in
                       {str(b) for b in actor.building_ids} for ref in message.get("refs", []))

        sub = events.hub.subscribe(allowed)
        receive = asyncio.ensure_future(ws.receive_text())
        get: asyncio.Future[dict[str, Any]] | None = None
        try:
            while True:
                get = asyncio.ensure_future(sub[0].get())
                done, _ = await asyncio.wait({receive, get}, timeout=PING_AFTER,
                                             return_when=asyncio.FIRST_COMPLETED)
                if receive in done:
                    receive.result()  # закрыто клиентом — WebSocketDisconnect
                    receive = asyncio.ensure_future(ws.receive_text())
                if get in done:
                    await ws.send_json(get.result())
                else:
                    get.cancel()
                    if not done:
                        await ws.send_json({"action": "ping"})
        except WebSocketDisconnect:
            pass
        finally:
            # ожидания отменить, а не бросить: брошенные висят до сборщика мусора (R-051)
            receive.cancel()
            if get is not None:
                get.cancel()
            events.hub.unsubscribe(sub)

    _mount_web(app)
    return app


def serve_app() -> FastAPI:
    """Приложение для `python -m app serve`. Всё, что создано при запуске (модули, маршруты,
    схемы), — вне сборки мусора: полная сборка обходит только созданное потом, и её пауза не
    попадает в расчёт зоны обзора (8.2, DWG3D-10, ADR-0010). Тесты создают приложение через
    create_app, без заморозки: замороженное сборщик не освобождает."""
    app = create_app()
    gc.collect()
    gc.freeze()
    return app


def _actor_for(token: str | None) -> Actor | None:
    with transaction() as session:
        return access.actor_for_token(session, token)


def _mount_web(app: FastAPI) -> None:
    """Собранный интерфейс: файлы как есть, остальные адреса — index.html (6.1 п. 7)."""
    root = config().static_dir
    index = root / "index.html"
    if not index.exists():
        return
    if (root / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        if path.startswith("api/"):
            return JSONResponse(AppError("Нет такого адреса.", code="not_found",
                                         status=404).body(), status_code=404)
        candidate = (root / path).resolve()
        if path and candidate.is_file() and root.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
