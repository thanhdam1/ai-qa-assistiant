"""Story collections and flow orchestration tables.

Revision ID: 0007_story_collections
Revises: 0006_async_jobs
Create Date: 2026-11-02
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_story_collections"
down_revision = "0006_async_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "story_collections",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("collection_type", sa.String(length=32), nullable=False, server_default="dag_journey"),
        sa.Column("execution_order", sa.JSON(), nullable=False),
        sa.Column("health_status", sa.String(length=32), nullable=False, server_default="synced"),
        sa.Column("metadata_info", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_collection_code", "story_collections", ["code"])
    op.create_index("ix_collection_health", "story_collections", ["health_status"])

    op.create_table(
        "collection_story_members",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("collection_id", sa.String(length=36), sa.ForeignKey("story_collections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("story_id", sa.String(length=36), sa.ForeignKey("stories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("role_in_flow", sa.String(length=32), nullable=False, server_default="intermediate"),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("collection_id", "story_id", name="uq_collection_story"),
    )
    op.create_index("ix_col_member_col", "collection_story_members", ["collection_id"])
    op.create_index("ix_col_member_story", "collection_story_members", ["story_id"])


def downgrade() -> None:
    op.drop_index("ix_col_member_story", table_name="collection_story_members")
    op.drop_index("ix_col_member_col", table_name="collection_story_members")
    op.drop_table("collection_story_members")

    op.drop_index("ix_collection_health", table_name="story_collections")
    op.drop_index("ix_collection_code", table_name="story_collections")
    op.drop_table("story_collections")
