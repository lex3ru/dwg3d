"""ORM tables. The schema itself is changed only through Alembic migrations
(dwg3d/migrations/versions); keep these classes in step with them."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class CatalogCategory(Base):
    __tablename__ = "catalog_categories"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    color: Mapped[str] = mapped_column(Text, server_default="#868e96")
    sort: Mapped[int] = mapped_column(Integer, server_default="0")


class CatalogItem(Base):
    """One piece of furniture / equipment. Ids ('diag.mri') are referenced by
    placed items, so an item is deactivated rather than deleted."""
    __tablename__ = "catalog_items"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    category_id: Mapped[str] = mapped_column(ForeignKey("catalog_categories.id"), index=True)
    name: Mapped[str] = mapped_column(Text)
    w: Mapped[float] = mapped_column(Float)
    d: Mapped[float] = mapped_column(Float)
    h: Mapped[float] = mapped_column(Float)
    elev: Mapped[float | None] = mapped_column(Float)
    clear: Mapped[float | None] = mapped_column(Float)
    wall: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    kind: Mapped[str] = mapped_column(Text)                 # procedural model
    color: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)         # GLB under frontend/public/catalog/
    model_rot: Mapped[float | None] = mapped_column(Float)
    camera: Mapped[dict | None] = mapped_column(JSONB)      # {fov, range, ident}
    params: Mapped[dict | None] = mapped_column(JSONB)      # {radio: {tx, range}} | {detect: {radius}} | {light: {flux, power, beam, cct}}
    tags: Mapped[str | None] = mapped_column(Text)
    article: Mapped[str | None] = mapped_column(Text)
    supplier: Mapped[str | None] = mapped_column(Text)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(CHAR(3), server_default="RUB")
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    sort: Mapped[int] = mapped_column(Integer, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    """A user signed in through Keycloak (`sub` of the tokens). `roles` are the
    application's client roles (dwg3d.<role>) as of the last sign-in or token
    refresh; `role` is the global one they give: admin, catalog_admin, user."""
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('user', 'catalog_admin', 'admin')", name="users_role"),
                      Index("users_login", func.lower(text("login")), unique=True),
                      Index("users_sub", "sub", unique=True))

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sub: Mapped[str | None] = mapped_column(Text)
    login: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text, server_default="")
    email: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, server_default="user")
    roles: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(Base):
    """A signed-in browser: the cookie holds the token, the row its SHA-256
    and the Keycloak tokens (refreshed now and then: a user signed out or
    disabled in Keycloak loses the session)."""
    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    user_agent: Mapped[str] = mapped_column(Text, server_default="")
    id_token: Mapped[str | None] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Project(Base):
    """A container for everything about one object: its drawings (buildings,
    sections, revisions) and, later, its layers."""
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(Text, primary_key=True)        # 12 hex chars
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Drawing(Base):
    """An uploaded DWG/DXF and everything the user set on it (builds, floors,
    map binding, detail model). Its files are in the file store under
    drawings/<id>/ (files.py; see Build.out_dir)."""
    __tablename__ = "drawings"

    id: Mapped[str] = mapped_column(Text, primary_key=True)        # 12 hex chars, as in data/jobs/<id>
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str | None] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(Text)                     # original upload name
    input_path: Mapped[str] = mapped_column(Text)                   # relative to the drawing dir
    size: Mapped[int] = mapped_column(BigInteger, server_default="0")
    config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))   # overrides for the next build
    site: Mapped[dict | None] = mapped_column(JSONB)                # map binding
    detail: Mapped[dict | None] = mapped_column(JSONB)              # detailed model alignment
    current_build: Mapped[int] = mapped_column(Integer, server_default="0")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Build(Base):
    """Result of one successful pipeline run (build numbers start at 1)."""
    __tablename__ = "builds"

    drawing_id: Mapped[str] = mapped_column(ForeignKey("drawings.id", ondelete="CASCADE"), primary_key=True)
    n: Mapped[int] = mapped_column(Integer, primary_key=True)
    result: Mapped[dict] = mapped_column(JSONB)                     # floors, rooms, entrances, warnings...
    config: Mapped[dict] = mapped_column(JSONB)                     # overrides as re-anchored by this build
    out_dir: Mapped[str] = mapped_column(Text)                      # its own tree in the file store:
                                                                    # builds/<job> (out before versioning)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


JOB_ACTIVE = ("queued", "running")


class Job(Base):
    """Build queue: workers claim queued rows with SELECT ... FOR UPDATE SKIP LOCKED."""
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'running', 'done', 'error')", name="jobs_status"),
        # at most one queued/running build per drawing
        Index("jobs_one_active", "drawing_id", unique=True, postgresql_where=text("status IN ('queued', 'running')")),
        Index("jobs_queue", "status", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    drawing_id: Mapped[str] = mapped_column(ForeignKey("drawings.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(Text, server_default="queued")
    stage: Mapped[str] = mapped_column(Text, server_default="queued")
    progress: Mapped[float] = mapped_column(Float, server_default="0")
    message: Mapped[str] = mapped_column(Text, server_default="")
    error: Mapped[str | None] = mapped_column(Text)
    trace: Mapped[str | None] = mapped_column(Text)                 # server log only, never sent to the client
    worker: Mapped[str | None] = mapped_column(Text)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Floor(Base):
    """A floor that keeps its identity across builds: `anchor` (sheet + alignment,
    see edits.py) is matched to each new build; `candidate` is its id there
    (c0, c3...) or NULL when its sheet is no longer found."""
    __tablename__ = "floors"
    __table_args__ = (UniqueConstraint("drawing_id", "candidate"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    drawing_id: Mapped[str] = mapped_column(ForeignKey("drawings.id", ondelete="CASCADE"), index=True)
    anchor: Mapped[dict] = mapped_column(JSONB)
    candidate: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    level: Mapped[int | None] = mapped_column(Integer)
    elevation: Mapped[float | None] = mapped_column(Float)
    height: Mapped[float | None] = mapped_column(Float)


class Layer(Base):
    """A layer of a project: furniture, CCTV, routes, zones... (`kind`, see layers.py).
    Its objects may stand on any drawing of the project."""
    __tablename__ = "layers"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    visible: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    locked: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    sort: Mapped[int] = mapped_column(Integer, server_default="0")
    props: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Room(Base):
    """A room that keeps its id across builds (matched by name and outline,
    see rooms.py). `idx` is its index in the current build's plan of the floor
    (node floor_<candidate>_room_<idx>), NULL when the room is gone; `poly` is
    its outline in plan coordinates of the current (or its last) build."""
    __tablename__ = "rooms"
    __table_args__ = (UniqueConstraint("floor_id", "idx"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    drawing_id: Mapped[str] = mapped_column(ForeignKey("drawings.id", ondelete="CASCADE"), index=True)
    floor_id: Mapped[int] = mapped_column(ForeignKey("floors.id", ondelete="CASCADE"))
    idx: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text, server_default="")
    type: Mapped[str | None] = mapped_column(Text)
    area: Mapped[float] = mapped_column(Float, server_default="0")
    poly: Mapped[list] = mapped_column(JSONB)


class LayerObject(Base):
    """An object of a layer on a floor of one of the project's drawings.
    `x, y` are plan coordinates (m) of the current build (the anchor: the
    position of a point, the first point of a line); `points` the vertices of
    lines and polygons. When a rebuild moves the floor, the rows move with
    it. floor_id NULL, or a floor whose sheet is gone (candidate NULL), means
    "not on a floor" until it is put back. room_id is the room it stands in."""
    __tablename__ = "layer_objects"
    __table_args__ = (CheckConstraint("geom IN ('point', 'polyline', 'polygon', 'route')", name="layer_objects_geom"),)

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True)                     # client-made, per project
    layer_id: Mapped[str] = mapped_column(ForeignKey("layers.id", ondelete="CASCADE"), index=True)
    drawing_id: Mapped[str] = mapped_column(ForeignKey("drawings.id", ondelete="CASCADE"), index=True)
    floor_id: Mapped[int | None] = mapped_column(ForeignKey("floors.id", ondelete="SET NULL"), index=True)
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id", ondelete="SET NULL"))
    # no FK: catalog ids are never deleted, and old data must import even before the catalog is loaded
    item_id: Mapped[str | None] = mapped_column(Text, index=True)
    geom: Mapped[str] = mapped_column(Text, server_default="point")
    x: Mapped[float] = mapped_column(Float(53))
    y: Mapped[float] = mapped_column(Float(53))
    angle: Mapped[float] = mapped_column(Float, server_default="0")
    points: Mapped[list | None] = mapped_column(JSONB(none_as_null=True))
    size: Mapped[list[float] | None] = mapped_column(ARRAY(Float))              # [w, d, h] override
    elev: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(Text)
    props: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))   # kind-specific: fov, range...
    version: Mapped[int] = mapped_column(Integer, server_default="1")          # optimistic locking
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Pin(Base):
    """Marker or comment. `x, y, z` are glTF coordinates of the current build
    (shifted on rebuilds like placements); floor_id NULL = building-wide."""
    __tablename__ = "pins"
    __table_args__ = (CheckConstraint("kind IN ('marker', 'comment')", name="pins_kind"),)

    drawing_id: Mapped[str] = mapped_column(ForeignKey("drawings.id", ondelete="CASCADE"), primary_key=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    floor_id: Mapped[int | None] = mapped_column(ForeignKey("floors.id", ondelete="SET NULL"), index=True)
    x: Mapped[float] = mapped_column(Float(53))
    y: Mapped[float] = mapped_column(Float(53))
    z: Mapped[float] = mapped_column(Float(53))
    text: Mapped[str] = mapped_column(Text, server_default="")
    label: Mapped[str] = mapped_column(Text, server_default="")
    author: Mapped[str] = mapped_column(Text, server_default="")
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectMember(Base):
    """Who may open a project and how: owner (members, share links, deletion),
    editor, viewer. An invitation by e-mail waits with user_id NULL until
    that user signs in."""
    __tablename__ = "project_members"
    __table_args__ = (CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="project_members_role"),
                      CheckConstraint("user_id IS NOT NULL OR email IS NOT NULL", name="project_members_who"),
                      UniqueConstraint("project_id", "user_id"),
                      Index("project_members_invite", "project_id", func.lower(text("email")), unique=True,
                            postgresql_where=text("user_id IS NULL")))

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    email: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShareLink(Base):
    """Read-only access to a project without an account (the link carries a
    token, the row its SHA-256), optionally to some drawings and layers only."""
    __tablename__ = "share_links"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text, server_default="")
    drawings: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    layers: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Proposal(Base):
    """Changes of layer objects on a drawing proposed by the copilot (`ops` as
    viewdata.apply takes them), waiting for a person: open → applied |
    rejected | stale (the rows or the build changed since)."""
    __tablename__ = "proposals"
    __table_args__ = (CheckConstraint("status IN ('open', 'applied', 'rejected', 'stale')", name="proposals_status"),
                      Index("proposals_project", "project_id", "status"))

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    drawing_id: Mapped[str] = mapped_column(ForeignKey("drawings.id", ondelete="CASCADE"))
    agent: Mapped[str] = mapped_column(Text, server_default="")          # who proposed: «Копилот»
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    summary: Mapped[str] = mapped_column(Text, server_default="")
    ops: Mapped[list] = mapped_column(JSONB)
    build: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, server_default="open")
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class UIContext(Base):
    """What an open viewer window shows (uicontext.py): kept while it reports."""
    __tablename__ = "ui_contexts"
    __table_args__ = (Index("ui_contexts_project", "project_id", "user_id"),)

    client: Mapped[str] = mapped_column(Text, primary_key=True)       # random per browser tab
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    data: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppSetting(Base):
    """A setting changed in the UI (copilot.py: the model endpoint, key, limits)."""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class CopilotChat(Base):
    """A conversation of a user with the copilot in a project, in the model API's message format."""
    __tablename__ = "copilot_chats"
    __table_args__ = (Index("copilot_chats_owner", "project_id", "user_id", "updated_at"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(Text, server_default="")
    messages: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CopilotUsage(Base):
    """Requests of a user to the copilot's model a day (the daily limit)."""
    __tablename__ = "copilot_usage"

    user_key: Mapped[str] = mapped_column(Text, primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    requests: Mapped[int] = mapped_column(Integer, server_default="0")
    prompt_tokens: Mapped[int] = mapped_column(BigInteger, server_default="0")
    completion_tokens: Mapped[int] = mapped_column(BigInteger, server_default="0")


class AuditLog(Base):
    """Who changed what. No FK to projects: the history outlives a deleted project."""
    __tablename__ = "audit_log"
    __table_args__ = (Index("audit_log_project", "project_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    project_id: Mapped[str | None] = mapped_column(Text)
    drawing_id: Mapped[str | None] = mapped_column(Text)
    entity: Mapped[str] = mapped_column(Text)            # object, pin, layer, drawing, project
    entity_id: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)            # create, update, delete
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor: Mapped[str | None] = mapped_column(Text)      # login at the time (kept if the user is removed)
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
