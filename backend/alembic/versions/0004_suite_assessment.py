"""Keep QA content approval separate from coverage and execution assessment."""

import sqlalchemy as sa
from alembic import op

revision = "0004_suite_assessment"
down_revision = "0003_requirement_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("test_case_sets") as batch:
        batch.add_column(sa.Column("content_version", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("coverage_decisions", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("case_readiness", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("coverage_accepted_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("coverage_accepted_by", sa.String(length=120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("test_case_sets") as batch:
        batch.drop_column("coverage_accepted_by")
        batch.drop_column("coverage_accepted_at")
        batch.drop_column("case_readiness")
        batch.drop_column("coverage_decisions")
        batch.drop_column("content_version")
