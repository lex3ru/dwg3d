from datetime import datetime
from typing import Any

from fastapi import APIRouter

from app.core.auth import Admin
from app.core.db import DB
from app.modules.journal import api

router = APIRouter(prefix="/api/journal", tags=["journal"])


@router.get("")
def journal_feed(_: Admin, session: DB, ref: str | None = None,
                 actor: str | None = None, action: str | None = None,
                 since: datetime | None = None, until: datetime | None = None,
                 q: str | None = None, before_id: int | None = None,
                 limit: int = 50) -> dict[str, Any]:
    entries = api.feed(session, ref=ref, actor_id=actor, action=action, since=since,
                       until=until, text_query=q, before_id=before_id, limit=limit)
    return {
        "items": [{
            "id": e.id, "at": e.at, "actor_id": e.actor_id, "actor_name": e.actor_name,
            "action": e.action, "summary": e.summary, "entity": e.entity, "refs": e.refs,
            "before": e.before, "after": e.after,
        } for e in entries],
        "next_before_id": entries[-1].id if len(entries) == min(limit, 200) else None,
    }
