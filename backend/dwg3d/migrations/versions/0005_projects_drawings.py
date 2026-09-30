"""projects hold drawings

A project becomes a container; what used to be a project (one uploaded
drawing with its builds, floors, furniture and pins) becomes a drawing.
Existing rows keep their ids: the table is renamed, and every old project
gets a new project row with the same id holding that one drawing.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-30
"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None

CHILDREN = ("builds", "floors", "jobs", "placements", "pins")


def upgrade():
    op.rename_table("projects", "drawings")
    op.execute("ALTER TABLE drawings RENAME CONSTRAINT projects_pkey TO drawings_pkey")
    op.execute("ALTER TABLE drawings RENAME CONSTRAINT projects_created_by_fkey TO drawings_created_by_fkey")
    op.execute("ALTER TABLE drawings DROP COLUMN IF EXISTS view")
    for t in CHILDREN:
        op.alter_column(t, "project_id", new_column_name="drawing_id")
        op.execute(f"ALTER TABLE {t} RENAME CONSTRAINT {t}_project_id_fkey TO {t}_drawing_id_fkey")
    op.execute("ALTER INDEX ix_floors_project_id RENAME TO ix_floors_drawing_id")
    op.execute("ALTER TABLE floors RENAME CONSTRAINT floors_project_id_candidate_key TO floors_drawing_id_candidate_key")
    op.execute("ALTER INDEX ix_jobs_project_id RENAME TO ix_jobs_drawing_id")

    op.create_table(
        "projects",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("""
        INSERT INTO projects (id, name, created_by, created_at, updated_at, deleted_at)
        SELECT id, COALESCE(NULLIF(name, ''), regexp_replace(filename, '\\.[^.]*$', '')),
               created_by, created_at, updated_at, deleted_at
        FROM drawings""")
    op.add_column("drawings", sa.Column("project_id", sa.Text(), nullable=True))
    op.execute("UPDATE drawings SET project_id = id")
    op.alter_column("drawings", "project_id", nullable=False)
    op.create_foreign_key("drawings_project_id_fkey", "drawings", "projects", ["project_id"], ["id"],
                          ondelete="CASCADE")
    op.create_index("ix_drawings_project_id", "drawings", ["project_id"])

    op.add_column("audit_log", sa.Column("drawing_id", sa.Text(), nullable=True))
    op.execute("UPDATE audit_log SET drawing_id = project_id WHERE entity IN ('placement', 'pin')")
    op.execute("UPDATE audit_log SET entity = 'drawing', drawing_id = project_id WHERE entity = 'project'")


def downgrade():
    op.execute("UPDATE audit_log SET entity = 'project' WHERE entity = 'drawing'")
    op.drop_column("audit_log", "drawing_id")
    op.drop_index("ix_drawings_project_id", table_name="drawings")
    op.drop_constraint("drawings_project_id_fkey", "drawings", type_="foreignkey")
    # drawings of multi-drawing projects cannot go back: only the one sharing the project id survives
    op.execute("DELETE FROM drawings WHERE id <> project_id")
    op.drop_column("drawings", "project_id")
    op.drop_table("projects")
    op.execute("ALTER INDEX ix_jobs_drawing_id RENAME TO ix_jobs_project_id")
    op.execute("ALTER TABLE floors RENAME CONSTRAINT floors_drawing_id_candidate_key TO floors_project_id_candidate_key")
    op.execute("ALTER INDEX ix_floors_drawing_id RENAME TO ix_floors_project_id")
    for t in CHILDREN:
        op.execute(f"ALTER TABLE {t} RENAME CONSTRAINT {t}_drawing_id_fkey TO {t}_project_id_fkey")
        op.alter_column(t, "drawing_id", new_column_name="project_id")
    op.execute("ALTER TABLE drawings RENAME CONSTRAINT drawings_created_by_fkey TO projects_created_by_fkey")
    op.execute("ALTER TABLE drawings RENAME CONSTRAINT drawings_pkey TO projects_pkey")
    op.rename_table("drawings", "projects")
