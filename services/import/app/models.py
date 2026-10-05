"""The tables of the import service (docs/DATA_MODEL.md, section 4)."""
from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, Float, ForeignKey, Integer, Table, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from twin_chassis import metadata

drawings = Table(
    "drawings", metadata,
    Column("id", Uuid, primary_key=True),
    Column("building_id", Uuid, nullable=False, index=True),          # -> buildings
    Column("name", Text, nullable=False, server_default=""),
    # how to read the drawing: layer roles, units, floors, and the corrections of the 2D editor
    # (config.edits, anchored to floor sheets — app/dwg/edits.py)
    Column("config", JSONB, nullable=False, server_default="{}"),
    Column("current_file_id", Uuid),
    Column("current_build_id", Uuid),                                 # the latest build that succeeded
    Column("created_by", Text, nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("deleted_at", DateTime(timezone=True)),
)

drawing_files = Table(
    "drawing_files", metadata,                                        # uploaded files; never changed
    Column("id", Uuid, primary_key=True),
    Column("drawing_id", Uuid, ForeignKey("drawings.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("n", Integer, nullable=False),
    Column("filename", Text, nullable=False),                         # as uploaded
    Column("size", BigInteger, nullable=False),
    Column("sha256", Text, nullable=False),
    Column("storage_key", Text, nullable=False),
    Column("uploaded_by", Text, nullable=False, server_default=""),
    Column("uploaded_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

builds = Table(
    "builds", metadata,                                               # the queue and the history of builds
    Column("id", Uuid, primary_key=True),
    Column("drawing_id", Uuid, ForeignKey("drawings.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("file_id", Uuid, ForeignKey("drawing_files.id"), nullable=False),
    Column("n", Integer, nullable=False),
    Column("status", Text, nullable=False, server_default="queued"),   # queued | running | done | error
    Column("stage", Text, nullable=False, server_default="queued"),
    Column("progress", Float, nullable=False, server_default="0"),
    Column("message", Text, nullable=False, server_default=""),
    Column("error", Text),                                            # for people
    Column("trace", Text),                                            # for the server log only
    Column("config", JSONB),                                          # as used, corrections re-anchored
    Column("result", JSONB),                                          # floors, rooms, warnings... (pipeline.run)
    Column("out_prefix", Text),                                       # its files in the bucket
    Column("requested_by", Text, nullable=False, server_default=""),
    Column("worker", Text),
    Column("heartbeat_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
)
