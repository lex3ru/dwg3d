import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, SecretStr

from app.core.auth import Admin, CurrentActor
from app.core.db import DB
from app.core.errors import AppError, NotFound
from app.modules.surveillance import api
from app.modules.surveillance.stream import preview

router = APIRouter(prefix="/api/surveillance", tags=["surveillance"])


@router.get("/cameras")
def cameras(building_id: uuid.UUID, actor: CurrentActor, session: DB) -> dict:
    return {"items": api.cameras(session, actor, building_id)}


@router.get("/cameras/{item_id}")
def camera(item_id: uuid.UUID, actor: CurrentActor, session: DB) -> dict:
    source = api.connection(session, actor, item_id)
    return api.view(source, actor)


class PreviewResponse(StreamingResponse):
    """Ожидание камеры входит в отменяемую передачу, а не в транзакцию (ADR-0027)."""

    async def stream_response(self, send):
        frames = self.body_iterator
        started = False
        try:
            try:
                first = await anext(frames)
            except StopAsyncIteration:
                raise AppError("Не удалось получить видео с камеры.", status=502) from None
            started = True
            await send({"type": "http.response.start", "status": self.status_code,
                        "headers": self.raw_headers})
            await send({"type": "http.response.body", "body": first, "more_body": True})
            async for chunk in frames:
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
        except AppError as error:
            if not started:
                response = JSONResponse(error.body(), status_code=error.status,
                                        headers={"Cache-Control": "no-store"})
                await send({"type": "http.response.start", "status": response.status_code,
                            "headers": response.raw_headers})
                await send({"type": "http.response.body", "body": response.body})
                return
        finally:
            await frames.aclose()
        await send({"type": "http.response.body", "body": b"", "more_body": False})


@router.get("/cameras/{item_id}/preview")
def live(item_id: uuid.UUID, actor: CurrentActor, session: DB) -> StreamingResponse:
    source = api.connection(session, actor, item_id)
    if source is None:
        raise NotFound("Физическая камера ещё не подключена.")
    return PreviewResponse(preview(api.stream_url(source)),
                           media_type="multipart/x-mixed-replace; boundary=ffmpeg",
                           headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


class ConnectionIn(BaseModel):
    address: str = Field(min_length=1, max_length=2048)
    username: str = Field(default="", max_length=200)
    password: SecretStr | None = None
    version: int = Field(ge=0)


@router.put("/cameras/{item_id}")
def configure(item_id: uuid.UUID, body: ConnectionIn, actor: Admin, session: DB) -> dict:
    password = body.password.get_secret_value() if body.password is not None else None
    if password is not None and len(password) > 1000:
        raise AppError("Пароль камеры слишком длинный.", field="password")
    return api.save(session, actor, item_id, address=body.address, username=body.username,
                    password=password, version=body.version)
