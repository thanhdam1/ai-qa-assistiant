"""Cross-story dependencies and DAG impact tracking."""

import sqlalchemy as sa
from alembic import op

revision = "0005_cross_story_dependencies"
down_revision = "0004_suite_assessment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "story_dependencies",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_story_id", sa.String(length=36), sa.ForeignKey("stories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_story_id", sa.String(length=36), sa.ForeignKey("stories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dependency_type", sa.String(length=32), nullable=False, server_default="precondition"),
        sa.Column("synced_source_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("target_story_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("binding_contract", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("impact_status", sa.String(length=32), nullable=False, server_default="synced"),
        sa.Column("stale_reason", sa.JSON(), nullable=True),
        sa.Column("impacted_case_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_story_id", "target_story_id", name="uq_story_edge"),
    )
    op.create_index("ix_story_dep_source", "story_dependencies", ["source_story_id"])
    op.create_index("ix_story_dep_target", "story_dependencies", ["target_story_id"])


def downgrade() -> None:
    op.drop_index("ix_story_dep_target", table_name="story_dependencies")
    op.drop_index("ix_story_dep_source", table_name="story_dependencies")
    op.drop_table("story_dependencies")
