from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.errors import (
    AIProviderError,
    AppError,
    NotFoundError,
    ReviewNotApprovedError,
    StaleVersionError,
)
from app.models import RequirementReview, Story, TestCaseSet
from app.schemas import (
    CoverageTargetType,
    RequirementReviewContent,
    StoryCreate,
    StoryUpdate,
    TestCaseSetContent,
)
from app.services.ai import AIProvider
from app.services.prompts import REVIEW_PROMPT_VERSION, TEST_CASE_PROMPT_VERSION


def get_story(db: Session, story_id: str, with_history: bool = False) -> Story:
    query = select(Story).where(Story.id == story_id)
    if with_history:
        query = query.options(selectinload(Story.reviews), selectinload(Story.test_case_sets))
    story = db.scalar(query)
    if not story:
        raise NotFoundError("Story")
    return story


def list_stories(db: Session) -> list[Story]:
    return list(db.scalars(select(Story).order_by(Story.updated_at.desc())).all())


def _validate_story_size(values: dict) -> None:
    text_parts = [
        values.get("title") or "",
        values.get("description") or "",
        values.get("business_context") or "",
        *(values.get("acceptance_criteria") or []),
        *(values.get("dependencies") or []),
    ]
    actual = sum(len(part) for part in text_parts)
    if actual > settings.max_story_chars:
        raise AppError(
            "story_too_large",
            f"Story content exceeds the configured {settings.max_story_chars} character limit",
            422,
            {"actual": actual, "limit": settings.max_story_chars},
        )


def create_story(db: Session, payload: StoryCreate) -> Story:
    values = payload.model_dump()
    _validate_story_size(values)
    story = Story(**values)
    db.add(story)
    db.commit()
    db.refresh(story)
    return story


def update_story(db: Session, story_id: str, payload: StoryUpdate) -> Story:
    story = get_story(db, story_id)
    changes = payload.model_dump(exclude_unset=True)
    candidate = {
        "title": story.title,
        "description": story.description,
        "acceptance_criteria": story.acceptance_criteria,
        "business_context": story.business_context,
        "dependencies": story.dependencies,
    } | changes
    _validate_story_size(candidate)
    changed = any(getattr(story, key) != value for key, value in changes.items())
    if not changed:
        return story
    for key, value in changes.items():
        setattr(story, key, value)
    story.version += 1
    db.execute(
        update(RequirementReview).where(RequirementReview.story_id == story.id).values(stale=True)
    )
    db.execute(update(TestCaseSet).where(TestCaseSet.story_id == story.id).values(stale=True))
    db.commit()
    db.refresh(story)
    return story


def _review_by_key(db: Session, story_id: str, key: str) -> RequirementReview | None:
    return db.scalar(
        select(RequirementReview).where(
            RequirementReview.story_id == story_id, RequirementReview.idempotency_key == key
        )
    )


async def generate_review(
    db: Session, story_id: str, idempotency_key: str, ai: AIProvider
) -> RequirementReview:
    existing = _review_by_key(db, story_id, idempotency_key)
    if existing:
        return existing
    story = get_story(db, story_id)
    result = await ai.review_requirements(story)
    review = RequirementReview(
        story_id=story.id,
        story_version=story.version,
        ai_original=result.model_dump(mode="json"),
        content=result.model_dump(mode="json"),
        idempotency_key=idempotency_key,
        model_name=ai.model_name,
        prompt_version=REVIEW_PROMPT_VERSION,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


def get_review(db: Session, review_id: str) -> RequirementReview:
    review = db.get(RequirementReview, review_id)
    if not review:
        raise NotFoundError("Requirement review")
    return review


def edit_review(
    db: Session, review_id: str, content: RequirementReviewContent
) -> RequirementReview:
    review = get_review(db, review_id)
    if review.stale:
        raise StaleVersionError()
    review.content = content.model_dump(mode="json")
    review.status = "draft"
    review.approved_at = None
    for test_set in review.test_case_sets:
        test_set.stale = True
    db.commit()
    db.refresh(review)
    return review


def approve_review(db: Session, review_id: str) -> RequirementReview:
    review = get_review(db, review_id)
    story = get_story(db, review.story_id)
    if review.stale or review.story_version != story.version:
        raise StaleVersionError()
    review.status = "approved"
    review.approved_at = datetime.now(UTC)
    db.commit()
    db.refresh(review)
    return review


def _testset_by_key(db: Session, story_id: str, key: str) -> TestCaseSet | None:
    return db.scalar(
        select(TestCaseSet).where(
            TestCaseSet.story_id == story_id, TestCaseSet.idempotency_key == key
        )
    )


async def generate_test_set(
    db: Session,
    story_id: str,
    review_id: str,
    idempotency_key: str,
    ai: AIProvider,
) -> TestCaseSet:
    existing = _testset_by_key(db, story_id, idempotency_key)
    if existing:
        return existing
    story = get_story(db, story_id)
    review = get_review(db, review_id)
    if review.story_id != story.id:
        raise ReviewNotApprovedError()
    if review.status != "approved":
        raise ReviewNotApprovedError()
    if review.stale or review.story_version != story.version:
        raise StaleVersionError()
    review_content = RequirementReviewContent.model_validate(review.content)
    result = await ai.generate_test_cases(story, review_content)
    coverage = {
        (entry.target_type, entry.target_id): entry for entry in result.coverage_matrix
    }
    required_targets = {
        (CoverageTargetType.acceptance_criterion, f"AC-{index:03d}")
        for index, _ in enumerate(story.acceptance_criteria, start=1)
    }
    required_targets.update(
        (CoverageTargetType.category, category)
        for category in ("positive", "negative", "boundary", "integration")
    )
    required_targets.update(
        (CoverageTargetType.risk, risk.id)
        for risk in review_content.risks
        if risk.severity.value in {"high", "critical"}
    )
    if required_targets - coverage.keys():
        raise AIProviderError(
            "Generated test suite omitted required coverage targets",
            provider_code="incomplete_coverage",
        )
    test_set = TestCaseSet(
        story_id=story.id,
        review_id=review.id,
        story_version=story.version,
        ai_original=result.model_dump(mode="json"),
        content=result.model_dump(mode="json"),
        idempotency_key=idempotency_key,
        model_name=ai.model_name,
        prompt_version=TEST_CASE_PROMPT_VERSION,
        generation_info={"review_prompt_version": review.prompt_version},
    )
    db.add(test_set)
    db.commit()
    db.refresh(test_set)
    return test_set


def get_test_set(db: Session, test_set_id: str) -> TestCaseSet:
    test_set = db.get(TestCaseSet, test_set_id)
    if not test_set:
        raise NotFoundError("Test case set")
    return test_set


def edit_test_set(db: Session, test_set_id: str, content: TestCaseSetContent) -> TestCaseSet:
    test_set = get_test_set(db, test_set_id)
    if test_set.stale:
        raise StaleVersionError()
    test_set.content = content.model_dump(mode="json")
    test_set.status = "draft"
    test_set.approved_at = None
    db.commit()
    db.refresh(test_set)
    return test_set


def approve_test_set(db: Session, test_set_id: str) -> TestCaseSet:
    test_set = get_test_set(db, test_set_id)
    story = get_story(db, test_set.story_id)
    review = get_review(db, test_set.review_id)
    if test_set.stale or review.stale or test_set.story_version != story.version:
        raise StaleVersionError()
    if review.status != "approved":
        raise ReviewNotApprovedError()
    test_set.status = "approved"
    test_set.approved_at = datetime.now(UTC)
    db.commit()
    db.refresh(test_set)
    return test_set
