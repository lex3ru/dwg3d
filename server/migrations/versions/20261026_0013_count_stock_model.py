"""Пересчёт остатков при инвентаризации — по позиции «место + тип + модель» (R-021, ADR-0005).

Пересчёт в черновиках ведомостей переносится на позицию: у типа в этом месте одна позиция с
остатком — берёт её модель; несколько — пересчёт строки удаляется, его вводят заново по
моделям; ни одной — остаётся без модели. Проведённые и отменённые ведомости не трогаются: их
итог — в строках документа.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('count_stock', sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False), schema='inventory')
    op.alter_column('count_stock', 'id', server_default=None, schema='inventory')
    op.add_column('count_stock', sa.Column('model_id', sa.UUID(), nullable=True), schema='inventory')
    op.drop_constraint('pk_count_stock', 'count_stock', type_='primary', schema='inventory')
    op.create_primary_key('pk_count_stock', 'count_stock', ['id'], schema='inventory')
    op.create_foreign_key(op.f('fk_count_stock_model_id_model'), 'count_stock', 'model', ['model_id'], ['id'], source_schema='inventory', referent_schema='catalog')

    conn = op.get_bind()
    rows = conn.execute(sa.text("""
        SELECT cs.id, array_agg(p.model_id) AS models
        FROM inventory.count_stock cs
        JOIN inventory.document d ON d.id = cs.document_id AND d.status = 'draft'
        JOIN LATERAL (
            SELECT sm.model_id FROM inventory.stock_move sm
            WHERE sm.place = cs.place AND sm.type_id = cs.type_id
            GROUP BY sm.model_id HAVING sum(sm.qty) <> 0
        ) p ON true
        GROUP BY cs.id
    """)).all()
    for row_id, models in rows:
        if len(models) == 1:
            conn.execute(sa.text("UPDATE inventory.count_stock SET model_id = :m WHERE id = :id"),
                         {"m": models[0], "id": row_id})
        else:
            conn.execute(sa.text("DELETE FROM inventory.count_stock WHERE id = :id"), {"id": row_id})

    op.create_unique_constraint('count_stock_position', 'count_stock', ['document_id', 'place', 'type_id', 'model_id'], schema='inventory', postgresql_nulls_not_distinct=True)


def downgrade() -> None:
    # по типу — одна строка: пересчёт моделей там, где их несколько у одного типа, теряется
    op.execute("""
        DELETE FROM inventory.count_stock cs
        WHERE cs.model_id IS NOT NULL AND EXISTS (
            SELECT 1 FROM inventory.count_stock o
            WHERE o.document_id = cs.document_id AND o.place = cs.place
              AND o.type_id = cs.type_id AND o.id <> cs.id
        )
    """)
    op.drop_constraint('count_stock_position', 'count_stock', type_='unique', schema='inventory')
    op.drop_constraint(op.f('fk_count_stock_model_id_model'), 'count_stock', type_='foreignkey', schema='inventory')
    op.drop_constraint('pk_count_stock', 'count_stock', type_='primary', schema='inventory')
    op.drop_column('count_stock', 'model_id', schema='inventory')
    op.drop_column('count_stock', 'id', schema='inventory')
    op.create_primary_key('pk_count_stock', 'count_stock', ['document_id', 'place', 'type_id'], schema='inventory')
