"""placements pins audit

Furniture, markers and comments move from projects.view (JSONB) to rows;
furniture whose floor was lost (furniture_unplaced + _anchor) gets a floor
row without a candidate, so it returns when the sheet is found again.
The downgrade restores the column empty (the rows are not written back).

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-30 14:05:49.469267
"""
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('audit_log',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('project_id', sa.Text(), nullable=True),
    sa.Column('entity', sa.Text(), nullable=False),
    sa.Column('entity_id', sa.Text(), nullable=False),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('actor', sa.Text(), nullable=True),
    sa.Column('before', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('after', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('audit_log_project', 'audit_log', ['project_id', 'id'], unique=False)
    op.create_table('pins',
    sa.Column('project_id', sa.Text(), nullable=False),
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('floor_id', sa.BigInteger(), nullable=True),
    sa.Column('x', sa.Float(precision=53), nullable=False),
    sa.Column('y', sa.Float(precision=53), nullable=False),
    sa.Column('z', sa.Float(precision=53), nullable=False),
    sa.Column('text', sa.Text(), server_default='', nullable=False),
    sa.Column('label', sa.Text(), server_default='', nullable=False),
    sa.Column('author', sa.Text(), server_default='', nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('marker', 'comment')", name='pins_kind'),
    sa.ForeignKeyConstraint(['floor_id'], ['floors.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('project_id', 'id')
    )
    op.create_index(op.f('ix_pins_floor_id'), 'pins', ['floor_id'], unique=False)
    op.create_table('placements',
    sa.Column('project_id', sa.Text(), nullable=False),
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('floor_id', sa.BigInteger(), nullable=True),
    sa.Column('item_id', sa.Text(), nullable=False),
    sa.Column('x', sa.Float(precision=53), nullable=False),
    sa.Column('y', sa.Float(precision=53), nullable=False),
    sa.Column('angle', sa.Float(), server_default='0', nullable=False),
    sa.Column('size', postgresql.ARRAY(sa.Float()), nullable=True),
    sa.Column('elev', sa.Float(), nullable=True),
    sa.Column('fov', sa.Float(), nullable=True),
    sa.Column('range', sa.Float(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['floor_id'], ['floors.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('project_id', 'id')
    )
    op.create_index(op.f('ix_placements_floor_id'), 'placements', ['floor_id'], unique=False)
    op.create_index(op.f('ix_placements_item_id'), 'placements', ['item_id'], unique=False)
    _move_view_data(op.get_bind())
    op.drop_column('projects', 'view')


def _move_view_data(conn):
    q = sa.text
    for pid, view in conn.execute(q("SELECT id, view FROM projects WHERE view <> '{}'::jsonb")).all():
        floors = dict(conn.execute(q("SELECT candidate, id FROM floors WHERE project_id = :p "
                                     "AND candidate IS NOT NULL"), {"p": pid}).all())
        lost = {}

        def lost_floor(anchor):
            key = json.dumps(anchor, sort_keys=True)
            if key not in lost:
                lost[key] = conn.execute(q("INSERT INTO floors (project_id, anchor, name) "
                                           "VALUES (:p, CAST(:a AS jsonb), :n) RETURNING id"),
                                         {"p": pid, "a": key, "n": anchor.get("name")}).scalar()
            return lost[key]

        items = [(it, floors.get(it.get("floor") or "")) for it in view.get("furniture") or []]
        items += [(it, lost_floor(it["_anchor"]) if it.get("_anchor") else None)
                  for it in view.get("furniture_unplaced") or []]
        for it, fid in items:
            conn.execute(q("INSERT INTO placements (project_id, id, floor_id, item_id, x, y, angle, size, elev, "
                           "fov, range, note) VALUES (:p, :id, :f, :item, :x, :y, :angle, :size, :elev, :fov, "
                           ":range, :note) ON CONFLICT DO NOTHING"),
                         {"p": pid, "id": it["id"], "f": fid, "item": it["item"], "x": it["at"][0], "y": it["at"][1],
                          "angle": it.get("angle") or 0, "size": it.get("size"), "elev": it.get("elev"),
                          "fov": it.get("fov"), "range": it.get("range"), "note": it.get("note")})
        for kind, key in (("marker", "markers"), ("comment", "comments")):
            for pin in view.get(key) or []:
                conn.execute(q("INSERT INTO pins (project_id, id, kind, floor_id, x, y, z, text, label, author, "
                               "created_at) VALUES (:p, :id, :kind, :f, :x, :y, :z, :text, :label, :author, "
                               "COALESCE(to_timestamp(CAST(:created AS double precision)), now())) ON CONFLICT DO NOTHING"),
                             {"p": pid, "id": pin["id"], "kind": kind, "f": floors.get(pin.get("floor") or ""),
                              "x": pin["pos"][0], "y": pin["pos"][1], "z": pin["pos"][2], "text": pin.get("text") or "",
                              "label": pin.get("label") or "", "author": pin.get("author") or "",
                              "created": pin.get("created")})


def downgrade():
    op.add_column('projects', sa.Column('view', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), autoincrement=False, nullable=False))
    op.drop_index(op.f('ix_placements_item_id'), table_name='placements')
    op.drop_index(op.f('ix_placements_floor_id'), table_name='placements')
    op.drop_table('placements')
    op.drop_index(op.f('ix_pins_floor_id'), table_name='pins')
    op.drop_table('pins')
    op.drop_index('audit_log_project', table_name='audit_log')
    op.drop_table('audit_log')
