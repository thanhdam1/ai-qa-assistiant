"""Add OpenAPI specification and contract review persistence."""

from alembic import op
import sqlalchemy as sa


revision = "0002_api_contract"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("api_specifications"):
        op.create_table(
            "api_specifications",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("story_id", sa.String(36), sa.ForeignKey("stories.id", ondelete="CASCADE"), nullable=False),
            sa.Column("title", sa.String(240), nullable=False),
            sa.Column("file_name", sa.String(255), nullable=False),
            sa.Column("openapi_version", sa.String(16), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("document", sa.JSON(), nullable=False),
            sa.Column("operations", sa.JSON(), nullable=False),
            sa.Column("checksum", sa.String(64), nullable=False),
            sa.Column("stale", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("story_id", "version", name="uq_api_spec_story_version"),
        )
    if "ix_api_spec_story_version" not in {index["name"] for index in sa.inspect(bind).get_indexes("api_specifications")}:
        op.create_index("ix_api_spec_story_version", "api_specifications", ["story_id", "version"])
    if not sa.inspect(bind).has_table("api_contract_reviews"):
        op.create_table(
            "api_contract_reviews",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("story_id", sa.String(36), sa.ForeignKey("stories.id", ondelete="CASCADE"), nullable=False),
            sa.Column("specification_id", sa.String(36), sa.ForeignKey("api_specifications.id", ondelete="CASCADE"), nullable=False),
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
            sa.UniqueConstraint("specification_id", "idempotency_key", name="uq_api_review_spec_idempotency"),
        )
    if "ix_api_review_story_spec" not in {index["name"] for index in sa.inspect(bind).get_indexes("api_contract_reviews")}:
        op.create_index("ix_api_review_story_spec", "api_contract_reviews", ["story_id", "specification_id"])
    if "api_contract_review_id" not in {column["name"] for column in sa.inspect(bind).get_columns("test_case_sets")}:
        with op.batch_alter_table("test_case_sets") as batch_op:
            batch_op.add_column(sa.Column("api_contract_review_id", sa.String(36), nullable=True))
            batch_op.create_foreign_key(
                "fk_test_case_sets_api_contract_review_id",
                "api_contract_reviews",
                ["api_contract_review_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    with op.batch_alter_table("test_case_sets") as batch_op:
        batch_op.drop_constraint("fk_test_case_sets_api_contract_review_id", type_="foreignkey")
        batch_op.drop_column("api_contract_review_id")
    op.drop_index("ix_api_review_story_spec", table_name="api_contract_reviews")
    op.drop_table("api_contract_reviews")
    op.drop_index("ix_api_spec_story_version", table_name="api_specifications")
    op.drop_table("api_specifications")
