"""Backfill source anchored requirement IDs and invalidate dependent test suites."""

from types import SimpleNamespace

import sqlalchemy as sa

from alembic import op
from app.schemas import RequirementReviewContent
from app.services.identity import acceptance_criterion_sources
from app.services.workflow import _normalize_requirement_ids

revision = "0003_requirement_identity"
down_revision = "0002_api_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    stories = sa.table(
        "stories",
        sa.column("id", sa.String),
        sa.column("description", sa.Text),
        sa.column("business_context", sa.Text),
        sa.column("dependencies", sa.JSON),
        sa.column("acceptance_criteria", sa.JSON),
    )
    reviews = sa.table(
        "requirement_reviews",
        sa.column("id", sa.String),
        sa.column("story_id", sa.String),
        sa.column("content", sa.JSON),
        sa.column("status", sa.String),
        sa.column("approved_at", sa.DateTime(timezone=True)),
    )
    sets = sa.table(
        "test_case_sets", sa.column("review_id", sa.String), sa.column("stale", sa.Boolean)
    )
    story_by_id = {
        row.id: SimpleNamespace(**row._mapping)
        for row in bind.execute(sa.select(stories)).all()
    }
    for row in bind.execute(sa.select(reviews)).all():
        story = story_by_id.get(row.story_id)
        if story is None:
            continue
        content = RequirementReviewContent.model_validate(row.content)
        normalized = _normalize_requirement_ids(content, story)
        new_content = normalized.model_dump(mode="json")
        expected_sources = {item["source_id"] for item in acceptance_criterion_sources(story)}
        actual_sources = {item.source_id for item in normalized.existing_acceptance_criteria}
        incomplete = bool(expected_sources - actual_sources)
        if new_content != row.content or (incomplete and row.status == "approved"):
            bind.execute(
                sa.update(reviews).where(reviews.c.id == row.id).values(
                    content=new_content,
                    status="draft" if incomplete else row.status,
                    approved_at=None if incomplete else row.approved_at,
                )
            )
            bind.execute(
                sa.update(sets).where(sets.c.review_id == row.id).values(stale=True)
            )


def downgrade() -> None:
    # Identity migration is intentionally irreversible; historical AI output is retained.
    pass
