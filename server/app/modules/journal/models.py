import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, Index, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Entry(Base):
    """Запись журнала. Таблица только для добавления: изменить или удалить запись не даёт
    триггер базы (удаление разрешено лишь очистке по сроку хранения, api.purge_before)."""

    __tablename__ = "entry"
    __table_args__ = (
        Index("ix_entry_refs", "refs", postgresql_using="gin"),
        {"schema": "journal"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                         index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID, index=True)
    # имя на момент действия: «Андреева Н. В.», «система», «гость по ссылке»
    actor_name: Mapped[str] = mapped_column(String(200))
    # что сделано, для программы: "user.create", "auth.login_failed"…
    action: Mapped[str] = mapped_column(String(100), index=True)
    # что сделано, для человека
    summary: Mapped[str] = mapped_column(Text)
    # над чем: "user:<id>", "document:<id>"…
    entity: Mapped[str] = mapped_column(String(100))
    # по чему запись найдётся в лентах (здание, этаж, помещение, предмет, единица,
    # документ, пользователь): сама сущность и то, к чему она относится
    refs: Mapped[list[str]] = mapped_column(ARRAY(String(100)))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
