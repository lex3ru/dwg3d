"""Requests of the service, under /api/ping/v1 (contracts/openapi/ping.v1.json)."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, insert, select
from twin_chassis import Identity, Problem, current_identity, emit, require_admin, uuid7

from .models import notes

router = APIRouter(tags=["notes"])


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=200, description="Текст заметки")


class Note(BaseModel):
    id: UUID
    text: str
    created_by: str
    created_at: datetime
    echoed_at: datetime | None = Field(description="Когда сервис получил событие о создании этой заметки")
    echoes: int = Field(description="Сколько раз событие обработано; больше одного быть не должно")


class NoteList(BaseModel):
    items: list[Note]


def _visible(me: Identity):
    """A note is seen by its author and by system administrators."""
    return notes.c.created_by == me.sub if not me.is_admin else notes.c.id.is_not(None)


@router.post("/notes", status_code=201, response_model=Note, summary="Создать заметку")
async def create_note(body: NoteIn, request: Request, me: Identity = Depends(current_identity)):
    async with request.app.state.db.begin() as session:
        row = (await session.execute(
            insert(notes).values(id=uuid7(), text=body.text, created_by=me.sub).returning(notes))).one()
        await emit(session, "ping.note.created", ("note", row.id), {"text": row.text})
    return row._mapping


@router.get("/notes", response_model=NoteList, summary="Последние заметки, видимые запросившему")
async def list_notes(request: Request, me: Identity = Depends(current_identity)):
    async with request.app.state.db.begin() as session:
        rows = (await session.execute(
            select(notes).where(_visible(me)).order_by(notes.c.created_at.desc()).limit(50))).all()
    return {"items": [r._mapping for r in rows]}


@router.get("/notes/{note_id}", response_model=Note, summary="Заметка")
async def get_note(note_id: UUID, request: Request, me: Identity = Depends(current_identity)):
    async with request.app.state.db.begin() as session:
        row = (await session.execute(select(notes).where(notes.c.id == note_id, _visible(me)))).one_or_none()
    if row is None:
        raise Problem(404, "not_found", "Заметка не найдена")
    return row._mapping


@router.delete("/notes/{note_id}", status_code=204, summary="Удалить заметку (администратор системы)")
async def delete_note(note_id: UUID, request: Request, _: Identity = Depends(require_admin)):
    async with request.app.state.db.begin() as session:
        gone = await session.execute(delete(notes).where(notes.c.id == note_id))
    if gone.rowcount == 0:
        raise Problem(404, "not_found", "Заметка не найдена")
