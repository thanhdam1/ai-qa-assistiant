"""Async jobs tracking for background tasks and re-sync engine."""

import sqlalchemy as sa
from alembic import op

revision = "0006_async_jobs"
down_revision = "0005_cross_story_dependencies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "async_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("story_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_async_jobs_story_id", "async_jobs", ["story_id"])
    op.create_index("ix_async_jobs_status", "async_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_async_jobs_status", table_name="async_jobs")
    op.drop_index("ix_async_jobs_story_id", table_name="async_jobs")
    op.drop_table("async_jobs")
