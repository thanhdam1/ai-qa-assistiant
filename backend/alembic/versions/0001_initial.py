"""Initial schema."""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("acceptance_criteria", sa.JSON(), nullable=False),
        sa.Column("business_context", sa.Text(), nullable=True),
        sa.Column("dependencies", sa.JSON(), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "requirement_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("story_id", sa.String(36), sa.ForeignKey("stories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("story_version", sa.Integer(), nullable=False),
        sa.Column("ai_original", sa.JSON(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("stale", sa.Boolean(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("story_id", "idempotency_key", name="uq_review_story_idempotency"),
    )
    op.create_index("ix_review_story_version", "requirement_reviews", ["story_id", "story_version"])
    op.create_table(
        "test_case_sets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("story_id", sa.String(36), sa.ForeignKey("stories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("review_id", sa.String(36), sa.ForeignKey("requirement_reviews.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("story_version", sa.Integer(), nullable=False),
        sa.Column("ai_original", sa.JSON(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("stale", sa.Boolean(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("generation_info", sa.JSON(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("story_id", "idempotency_key", name="uq_testset_story_idempotency"),
    )
    op.create_index("ix_testset_story_version", "test_case_sets", ["story_id", "story_version"])


def downgrade() -> None:
    op.drop_table("test_case_sets")
    op.drop_table("requirement_reviews")
    op.drop_table("stories")

