"""Ограниченное по времени превью RTSP → MJPEG без хранения кадров на диске."""

import asyncio
import time
from collections.abc import AsyncIterator

from app.core.errors import AppError

# На один процесс приложения. Просмотр ограничен минутой, затем клиент обновляет сеанс:
# снова проверяются права. Долгоживущая аналитика не должна использовать этот адаптер.
slots = asyncio.Semaphore(4)


async def preview(url: str) -> AsyncIterator[bytes]:
    try:
        await asyncio.wait_for(slots.acquire(), timeout=0.1)
    except TimeoutError:
        raise AppError("Все каналы просмотра заняты. Попробуйте позже.", status=503) from None
    process = None
    try:
        try:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
                "-rtsp_transport", "tcp", "-rw_timeout", "10000000", "-i", url,
                "-t", "60", "-an", "-vf", "fps=5,scale=960:-2", "-threads", "1",
                "-c:v", "mjpeg", "-q:v", "5", "-f", "mpjpeg", "pipe:1",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError:
            raise AppError("Просмотр недоступен: на сервере нужен FFmpeg.", status=503) from None
        assert process.stdout is not None
        # Ограничение wall-clock, в том числе для камеры с некорректными timestamps.
        # Первый чанк читается в обработчике, остальные — в задаче StreamingResponse.
        # Контекст asyncio.timeout нельзя переносить между этими задачами через yield.
        deadline = time.monotonic() + 70
        while (remaining := deadline - time.monotonic()) > 0:
            chunk = await asyncio.wait_for(process.stdout.read(65536), timeout=min(12, remaining))
            if not chunk:
                break
            yield chunk
    except TimeoutError:
        raise AppError("Камера не отвечает. Проверьте подключение.", status=504) from None
    finally:
        try:
            if process is not None and process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await asyncio.shield(process.wait())
        finally:
            slots.release()
