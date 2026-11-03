import uuid

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, SecretStr

from app.core.auth import Admin, CurrentActor
from app.core.db import DB
from app.core.errors import AppError, NotFound
from app.modules.surveillance import api
from app.modules.surveillance.stream import preview

router = APIRouter(prefix="/api/surveillance", tags=["surveillance"])


@router.get("/cameras/{item_id}")
def camera(item_id: uuid.UUID, actor: CurrentActor, session: DB) -> dict:
    source = api.connection(session, actor, item_id)
    return api.view(source, actor)


@router.get("/cameras/{item_id}/preview")
async def live(item_id: uuid.UUID, actor: CurrentActor, session: DB) -> StreamingResponse:
    source = api.connection(session, actor, item_id)
    if source is None:
        raise NotFound("Физическая камера ещё не подключена.")
    frames = preview(api.stream_url(source))
    try:
        first = await anext(frames)
    except StopAsyncIteration:
        raise AppError("Не удалось получить видео с камеры.", status=502) from None

    async def body():
        try:
            yield first
            async for chunk in frames:
                yield chunk
        except AppError:
            # После отправки заголовков JSON-ошибка уже невозможна. Клиент переподключится.
            return
        finally:
            await frames.aclose()

    return StreamingResponse(body(), media_type="multipart/x-mixed-replace; boundary=ffmpeg",
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
