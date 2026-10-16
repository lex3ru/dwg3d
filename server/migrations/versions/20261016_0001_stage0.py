"""Этап 0: ядро (очередь задач), журнал, доступ, настройки.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    for schema in ("journal", "access", "system"):
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    op.create_table('account',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('login', sa.String(length=50), nullable=False),
    sa.Column('full_name', sa.String(length=200), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=True),
    sa.Column('must_change_password', sa.Boolean(), nullable=False),
    sa.Column('blocked', sa.Boolean(), nullable=False),
    sa.Column('failed_attempts', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint("role IN ('admin', 'viewer')", name=op.f('ck_account_role')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_account')),
    schema='access'
    )
    op.create_index('uq_account_login', 'account', [sa.text('lower(login)')], unique=True, schema='access')
    op.create_table('job',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=100), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('progress_done', sa.Integer(), nullable=False),
    sa.Column('progress_total', sa.Integer(), nullable=True),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_job')),
    schema='core'
    )
    op.create_index(op.f('ix_core_job_kind'), 'job', ['kind'], unique=False, schema='core')
    op.create_index(op.f('ix_core_job_status'), 'job', ['status'], unique=False, schema='core')
    op.create_table('worker_beat',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('name', name=op.f('pk_worker_beat')),
    schema='core'
    )
    op.create_table('entry',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('actor_name', sa.String(length=200), nullable=False),
    sa.Column('action', sa.String(length=100), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('entity', sa.String(length=100), nullable=False),
    sa.Column('refs', postgresql.ARRAY(sa.String(length=100)), nullable=False),
    sa.Column('before', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('after', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_entry')),
    schema='journal'
    )
    op.create_index('ix_entry_refs', 'entry', ['refs'], unique=False, schema='journal', postgresql_using='gin')
    op.create_index(op.f('ix_journal_entry_action'), 'entry', ['action'], unique=False, schema='journal')
    op.create_index(op.f('ix_journal_entry_actor_id'), 'entry', ['actor_id'], unique=False, schema='journal')
    op.create_index(op.f('ix_journal_entry_at'), 'entry', ['at'], unique=False, schema='journal')
    op.create_table('setting',
    sa.Column('key', sa.String(length=100), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_setting')),
    schema='system'
    )
    op.create_table('building_grant',
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('building_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['access.account.id'], name=op.f('fk_building_grant_account_id_account'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('account_id', 'building_id', name=op.f('pk_building_grant')),
    schema='access'
    )
    op.create_index(op.f('ix_access_building_grant_building_id'), 'building_grant', ['building_id'], unique=False, schema='access')
    op.create_table('login_session',
    sa.Column('token_hash', sa.LargeBinary(length=32), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('method', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('user_agent', sa.String(length=300), nullable=True),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['account_id'], ['access.account.id'], name=op.f('fk_login_session_account_id_account'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('token_hash', name=op.f('pk_login_session')),
    schema='access'
    )
    op.create_index(op.f('ix_access_login_session_account_id'), 'login_session', ['account_id'], unique=False, schema='access')
    op.create_table('schedule_run',
    sa.Column('kind', sa.String(length=100), nullable=False),
    sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('job_id', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['job_id'], ['core.job.id'], name=op.f('fk_schedule_run_job_id_job'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('kind', name=op.f('pk_schedule_run')),
    schema='core'
    )
    # журнал только для добавления (9.4 п. 4): изменить запись нельзя, удалить — только
    # очистке по сроку хранения, которая включает journal.purge на время своей транзакции
    op.execute("""
        CREATE FUNCTION journal.append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND current_setting('journal.purge', true) = 'on' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'журнал только для добавления: % запрещено', TG_OP;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON journal.entry
        FOR EACH ROW EXECUTE FUNCTION journal.append_only()
    """)
    op.execute("""
        CREATE TRIGGER append_only_truncate BEFORE TRUNCATE ON journal.entry
        FOR EACH STATEMENT EXECUTE FUNCTION journal.append_only()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER append_only_truncate ON journal.entry")
    op.execute("DROP TRIGGER append_only ON journal.entry")
    op.execute("DROP FUNCTION journal.append_only()")
    op.drop_table('schedule_run', schema='core')
    op.drop_index(op.f('ix_access_login_session_account_id'), table_name='login_session', schema='access')
    op.drop_table('login_session', schema='access')
    op.drop_index(op.f('ix_access_building_grant_building_id'), table_name='building_grant', schema='access')
    op.drop_table('building_grant', schema='access')
    op.drop_table('setting', schema='system')
    op.drop_index(op.f('ix_journal_entry_at'), table_name='entry', schema='journal')
    op.drop_index(op.f('ix_journal_entry_actor_id'), table_name='entry', schema='journal')
    op.drop_index(op.f('ix_journal_entry_action'), table_name='entry', schema='journal')
    op.drop_index('ix_entry_refs', table_name='entry', schema='journal', postgresql_using='gin')
    op.drop_table('entry', schema='journal')
    op.drop_table('worker_beat', schema='core')
    op.drop_index(op.f('ix_core_job_status'), table_name='job', schema='core')
    op.drop_index(op.f('ix_core_job_kind'), table_name='job', schema='core')
    op.drop_table('job', schema='core')
    op.drop_index('uq_account_login', table_name='account', schema='access')
    op.drop_table('account', schema='access')
    for schema in ("system", "access", "journal"):
        op.execute(f"DROP SCHEMA IF EXISTS {schema}")
