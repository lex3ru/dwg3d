"""Этап 1: здания, этажи, помещения, лифты; файлы.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    for schema in ("files", "building"):
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    op.create_table('building',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('address', sa.String(length=300), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_building')),
    schema='building'
    )
    op.create_table('file',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('size', sa.BigInteger(), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_file')),
    schema='files'
    )
    op.create_index(op.f('ix_files_file_sha256'), 'file', ['sha256'], unique=False, schema='files')
    op.create_table('floor',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('building_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('elevation', sa.Float(), nullable=False),
    sa.Column('height', sa.Float(), nullable=False),
    sa.Column('plan', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('plan_version', sa.Integer(), nullable=False),
    sa.Column('plan_saved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['building_id'], ['building.building.id'], name=op.f('fk_floor_building_id_building'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_floor')),
    schema='building'
    )
    op.create_index(op.f('ix_building_floor_building_id'), 'floor', ['building_id'], unique=False, schema='building')
    op.create_table('lift',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('building_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('x', sa.Float(), nullable=False),
    sa.Column('y', sa.Float(), nullable=False),
    sa.Column('w', sa.Float(), nullable=False),
    sa.Column('d', sa.Float(), nullable=False),
    sa.Column('angle', sa.Float(), nullable=False),
    sa.Column('door_side', sa.Integer(), nullable=False),
    sa.Column('floor_ids', postgresql.ARRAY(sa.UUID()), nullable=False),
    sa.Column('stop_ids', postgresql.ARRAY(sa.UUID()), nullable=False),
    sa.ForeignKeyConstraint(['building_id'], ['building.building.id'], name=op.f('fk_lift_building_id_building'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_lift')),
    schema='building'
    )
    op.create_index(op.f('ix_building_lift_building_id'), 'lift', ['building_id'], unique=False, schema='building')
    op.create_table('room',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('building_id', sa.UUID(), nullable=False),
    sa.Column('floor_id', sa.UUID(), nullable=False),
    sa.Column('number', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('purpose_id', sa.String(length=64), nullable=True),
    sa.Column('area', sa.Float(), nullable=False),
    sa.Column('outline', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('x', sa.Float(), nullable=False),
    sa.Column('y', sa.Float(), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('continued_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['building_id'], ['building.building.id'], name=op.f('fk_room_building_id_building'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['continued_by'], ['building.room.id'], name=op.f('fk_room_continued_by_room'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['floor_id'], ['building.floor.id'], name=op.f('fk_room_floor_id_floor'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_room')),
    schema='building'
    )
    op.create_index(op.f('ix_building_room_building_id'), 'room', ['building_id'], unique=False, schema='building')
    op.create_index(op.f('ix_building_room_floor_id'), 'room', ['floor_id'], unique=False, schema='building')


def downgrade() -> None:
    op.drop_index(op.f('ix_building_room_floor_id'), table_name='room', schema='building')
    op.drop_index(op.f('ix_building_room_building_id'), table_name='room', schema='building')
    op.drop_table('room', schema='building')
    op.drop_index(op.f('ix_building_lift_building_id'), table_name='lift', schema='building')
    op.drop_table('lift', schema='building')
    op.drop_index(op.f('ix_building_floor_building_id'), table_name='floor', schema='building')
    op.drop_table('floor', schema='building')
    op.drop_index(op.f('ix_files_file_sha256'), table_name='file', schema='files')
    op.drop_table('file', schema='files')
    op.drop_table('building', schema='building')
    op.execute("DROP SCHEMA IF EXISTS building")
    op.execute("DROP SCHEMA IF EXISTS files")
