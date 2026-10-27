import importlib.util
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import RequirementReview, Story
from app.models import TestCaseSet as SuiteRow


def test_identity_backfill_and_stale_in_one_upgrade(monkeypatch, review_content):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        story = Story(
            title="Sign in", description="The user signs in",
            acceptance_criteria=["The user signs in"], dependencies=[],
        )
        db.add(story)
        db.flush()
        review = RequirementReview(
            story_id=story.id, story_version=1, status="approved",
            ai_original=review_content.model_dump(mode="json"),
            content=review_content.model_dump(mode="json"),
            idempotency_key="review", model_name="old", prompt_version="old",
        )
        db.add(review)
        db.flush()
        suite = SuiteRow(
            story_id=story.id, review_id=review.id, story_version=1,
            ai_original={}, content={}, idempotency_key="suite", model_name="old",
            prompt_version="old", generation_info={},
        )
        db.add(suite)
        db.commit()
        review_id, suite_id = review.id, suite.id

    path = Path(__file__).parents[1] / "alembic" / "versions" / "0003_requirement_identity.py"
    spec = importlib.util.spec_from_file_location("identity_migration", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    with engine.begin() as connection:
        monkeypatch.setattr(module.op, "get_bind", lambda: connection)
        module.upgrade()
    with Session(engine) as db:
        review = db.scalar(select(RequirementReview).where(RequirementReview.id == review_id))
        suite = db.scalar(select(SuiteRow).where(SuiteRow.id == suite_id))
        criterion = review.content["existing_acceptance_criteria"][0]
        assert criterion["id"].startswith("REQ-")
        assert criterion["source_id"].startswith("SRC-AC-")
        assert criterion["obligations"][0]["id"].startswith("OBL-")
        assert suite.stale is True
        assert review.ai_original["existing_acceptance_criteria"][0]["id"] == "AC-001"
