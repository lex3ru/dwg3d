"""layers, layer objects, rooms

Projects get layers (furniture, CCTV, and later routes, zones, networks...);
placed furniture becomes objects of layers: CCTV equipment (catalog category
"security") goes to a "Видеонаблюдение" layer, the rest to "Мебель и
оборудование". Rooms get rows that keep their id across builds.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None

TS = dict(server_default=sa.text("now()"), nullable=False)


def upgrade():
    op.create_table(
        "layers",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("visible", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("locked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("sort", sa.Integer(), server_default="0", nullable=False),
        sa.Column("props", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), **TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **TS),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_layers_project_id", "layers", ["project_id"])

    op.create_table(
        "rooms",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("drawing_id", sa.Text(), nullable=False),
        sa.Column("floor_id", sa.BigInteger(), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=True),
        sa.Column("name", sa.Text(), server_default="", nullable=False),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("area", sa.Float(), server_default="0", nullable=False),
        sa.Column("poly", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["drawing_id"], ["drawings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["floor_id"], ["floors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("floor_id", "idx"),
    )
    op.create_index("ix_rooms_drawing_id", "rooms", ["drawing_id"])

    op.create_table(
        "layer_objects",
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("layer_id", sa.Text(), nullable=False),
        sa.Column("drawing_id", sa.Text(), nullable=False),
        sa.Column("floor_id", sa.BigInteger(), nullable=True),
        sa.Column("room_id", sa.BigInteger(), nullable=True),
        sa.Column("item_id", sa.Text(), nullable=True),
        sa.Column("geom", sa.Text(), server_default="point", nullable=False),
        sa.Column("x", sa.Float(53), nullable=False),
        sa.Column("y", sa.Float(53), nullable=False),
        sa.Column("angle", sa.Float(), server_default="0", nullable=False),
        sa.Column("points", postgresql.JSONB(), nullable=True),
        sa.Column("size", postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column("elev", sa.Float(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("props", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **TS),
        sa.CheckConstraint("geom IN ('point', 'polyline', 'polygon', 'route')", name="layer_objects_geom"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["layer_id"], ["layers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["drawing_id"], ["drawings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["floor_id"], ["floors.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("project_id", "id"),
    )
    for col in ("layer_id", "drawing_id", "floor_id", "item_id"):
        op.create_index(f"ix_layer_objects_{col}", "layer_objects", [col])

    # ---- placements -> layer objects
    op.execute("""
        CREATE TEMP TABLE _placed AS
        SELECT p.*, d.project_id,
               CASE WHEN i.category_id = 'security' THEN 'cctv' ELSE 'furniture' END AS kind
        FROM placements p
        JOIN drawings d ON d.id = p.drawing_id
        LEFT JOIN catalog_items i ON i.id = p.item_id""")
    op.execute("""
        INSERT INTO layers (id, project_id, kind, name, sort)
        SELECT substr(md5(k.project_id || k.kind), 1, 12), k.project_id, k.kind,
               CASE k.kind WHEN 'cctv' THEN 'Видеонаблюдение' ELSE 'Мебель и оборудование' END,
               CASE k.kind WHEN 'cctv' THEN 1 ELSE 0 END
        FROM (SELECT DISTINCT project_id, kind FROM _placed) k""")
    op.execute("""
        INSERT INTO layer_objects (project_id, id, layer_id, drawing_id, floor_id, item_id, geom, x, y, angle,
                                   size, elev, note, props, version, updated_by, created_at, updated_at)
        SELECT project_id, id, substr(md5(project_id || kind), 1, 12), drawing_id, floor_id, item_id, 'point',
               x, y, angle, size, elev, note,
               jsonb_strip_nulls(jsonb_build_object('fov', fov, 'range', range)),
               version, updated_by, created_at, updated_at
        FROM _placed""")
    op.execute("DROP TABLE _placed")
    op.drop_table("placements")
    op.execute("UPDATE audit_log SET entity = 'object' WHERE entity = 'placement'")


def downgrade():
    op.create_table(
        "placements",
        sa.Column("drawing_id", sa.Text(), nullable=False),
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("floor_id", sa.BigInteger(), nullable=True),
        sa.Column("item_id", sa.Text(), nullable=False),
        sa.Column("x", sa.Float(53), nullable=False),
        sa.Column("y", sa.Float(53), nullable=False),
        sa.Column("angle", sa.Float(), server_default="0", nullable=False),
        sa.Column("size", postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column("elev", sa.Float(), nullable=True),
        sa.Column("fov", sa.Float(), nullable=True),
        sa.Column("range", sa.Float(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **TS),
        sa.ForeignKeyConstraint(["drawing_id"], ["drawings.id"], name="placements_drawing_id_fkey", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["floor_id"], ["floors.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("drawing_id", "id"),
    )
    op.create_index("ix_placements_floor_id", "placements", ["floor_id"])
    op.create_index("ix_placements_item_id", "placements", ["item_id"])
    op.execute("""
        INSERT INTO placements (drawing_id, id, floor_id, item_id, x, y, angle, size, elev, fov, range, note,
                                version, updated_by, created_at, updated_at)
        SELECT drawing_id, id, floor_id, item_id, x, y, angle, size, elev,
               (props->>'fov')::float, (props->>'range')::float, note, version, updated_by, created_at, updated_at
        FROM layer_objects WHERE geom = 'point' AND item_id IS NOT NULL""")
    op.execute("UPDATE audit_log SET entity = 'placement' WHERE entity = 'object'")
    op.drop_table("layer_objects")
    op.drop_table("rooms")
    op.drop_table("layers")
