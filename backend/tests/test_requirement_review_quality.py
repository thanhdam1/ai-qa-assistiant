import pytest

from app.errors import AppError
from app.models import Story
from app.schemas import (
    ExistingCriterion,
    RequirementObligation,
    RequirementReviewContent,
    ReviewItem,
)
from app.services.workflow import (
    _normalize_requirement_ids,
    _sanitize_ai_review,
    _validate_requirement_review,
)


def review_for(story, text=None, reference="acceptance_criteria[0]"):
    return _normalize_requirement_ids(
        RequirementReviewContent(
            language="en",
            business_summary="Review",
            existing_acceptance_criteria=[
                ExistingCriterion(
                    id="TMP",
                    criterion=text or story.acceptance_criteria[0],
                    source_reference=reference,
                )
            ],
            missing_acceptance_criteria=[],
            ambiguities_and_conflicts=[],
            stakeholder_questions=[],
            edge_cases=[],
            assumptions=[],
            risks=[],
        ),
        story,
    )


@pytest.fixture
def story():
    return Story(
        id="quality-story",
        title="Login",
        description="Users may log in.",
        acceptance_criteria=["Wrong password returns HTTP 401"],
        business_context="",
        dependencies=[],
        version=1,
    )


def check(review, story):
    _validate_requirement_review(review, story, verify_sources=True)


def test_changed_status_cannot_be_approved(story):
    with pytest.raises(AppError, match="differs from its source"):
        check(review_for(story, "Wrong password returns HTTP 200"), story)


def test_fake_source_cannot_be_approved_even_with_human_confirmation(story):
    content = review_for(story)
    content.existing_acceptance_criteria.append(
        ExistingCriterion(
            id="FAKE",
            criterion="Must pay subscription",
            source_reference="Imaginary document",
            confirmed_by="QA",
            obligations=[RequirementObligation(id="FAKE-OBL", text="Must pay subscription")],
        )
    )
    with pytest.raises(AppError, match="no verifiable story source"):
        check(content, story)


def test_source_quoted_verbatim_and_atomic_obligations(story):
    story.acceptance_criteria = ["The response has HTTP 401 and contains no token"]
    content = review_for(story)
    criterion = content.existing_acceptance_criteria[0]
    criterion.obligations = [
        RequirementObligation(id="ONE", text="The response has HTTP 401", source_quote="The response has HTTP 401"),
        RequirementObligation(id="TWO", text="contains no token", source_quote="contains no token"),
    ]
    check(content, story)
    criterion.obligations[1].source_quote = "contains a token"
    with pytest.raises(AppError, match="quote is not in its source"):
        check(content, story)


def test_paraphrase_requires_explicit_human_confirmation(story):
    content = review_for(story, "Reject invalid password with HTTP 401")
    with pytest.raises(AppError):
        check(content, story)
    content.existing_acceptance_criteria[0].confirmed_by = "QA"
    check(content, story)


@pytest.mark.parametrize(
    "group", ["missing_acceptance_criteria", "assumptions", "stakeholder_questions"]
)
def test_invalid_classification_cannot_be_approved(story, group):
    content = review_for(story)
    getattr(content, group).append(
        ReviewItem(
            id="F",
            title="Question",
            detail="Question?",
            severity="low",
            classification="requirement",
            source_reference="description",
        )
    )
    with pytest.raises(AppError, match="must"):
        check(content, story)


def test_ai_cannot_fabricate_human_confirmation(story):
    content = review_for(story)
    content.existing_acceptance_criteria[0].confirmed_by = "Fake QA"
    content.assumptions.append(
        ReviewItem(
            id="F",
            title="Question",
            detail="Question?",
            severity="low",
            source_reference="description",
            resolution_status="resolved",
            answer="Invented",
            resolved_by="Fake PO",
            accepted_ac="AC-11: Invented",
            accepted_by="Fake PO",
            proposed_ac="Invented",
        )
    )
    cleaned = _sanitize_ai_review(content)
    assert cleaned.existing_acceptance_criteria[0].confirmed_by is None
    finding = cleaned.assumptions[0]
    assert finding.resolution_status == "open"
    assert (
        finding.answer is finding.accepted_ac is finding.resolved_by is finding.proposed_ac is None
    )
    assert finding.classification.value == "needs_clarification"


def test_blocking_question_requires_answer_and_reviewer(story):
    content = review_for(story)
    finding = ReviewItem(
        id="F",
        title="OTP",
        detail="OTP expiration?",
        severity="high",
        source_reference="description",
        classification="needs_clarification",
        blocks_testability=True,
    )
    content.stakeholder_questions.append(finding)
    with pytest.raises(AppError, match="Resolve blocking"):
        check(content, story)
    finding.resolution_status = "resolved"
    with pytest.raises(AppError, match="need an answer"):
        check(content, story)
    finding.answer = "The PO confirmed expiration is five minutes."
    finding.resolved_by = "PO"
    check(content, story)


async def test_generation_passes_upstream_and_repairs_only_once(monkeypatch, story):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models import Base
    from app.services import workflow

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    contracts = [{"source_story_id": "cart", "source_version": 1}]
    monkeypatch.setattr(workflow, "extract_upstream_contracts", lambda db, sid: contracts)

    class Provider:
        model_name = "test"
        repairs = 0

        async def review_requirements(self, current, upstream_contracts=None):
            assert upstream_contracts == contracts
            result = review_for(current)
            result.existing_acceptance_criteria = []
            return result

        async def repair_requirement_review(
            self, current, previous, missing, upstream_contracts=None
        ):
            self.repairs += 1
            assert missing and upstream_contracts == contracts
            return previous

    with Session(engine) as db:
        db.add(story)
        db.commit()
        provider = Provider()
        result = await workflow.generate_review(db, story.id, "repair", provider)
        assert provider.repairs == 1
        assert result.status == "draft"
        with pytest.raises(AppError, match="Every source acceptance criterion"):
            workflow.approve_review(db, result.id)


async def test_generation_rejects_story_changed_while_ai_runs(story):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models import Base
    from app.errors import StaleVersionError
    from app.services.workflow import generate_review

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(story)
        db.commit()

        class Provider:
            model_name = "test"

            async def review_requirements(self, current, upstream_contracts=None):
                result = review_for(current)
                with Session(engine) as other:
                    other.get(Story, current.id).version += 1
                    other.commit()
                return result

        with pytest.raises(StaleVersionError):
            await generate_review(db, story.id, "concurrent", Provider())


def test_obligation_cannot_hide_changed_number_behind_correct_quote(story):
    content = review_for(story)
    item = content.existing_acceptance_criteria[0]
    item.obligations = [RequirementObligation(id='O', text='Wrong password returns HTTP 200',
                                             source_quote=story.acceptance_criteria[0])]
    with pytest.raises(AppError, match='differs from its source'):
        check(content, story)


def test_dropped_condition_requires_human_confirmation(story):
    story.acceptance_criteria = ['Wrong password returns HTTP 401 and contains no token']
    content = review_for(story)
    content.existing_acceptance_criteria[0].obligations = [
        RequirementObligation(id='O', text='Wrong password returns HTTP 401')]
    with pytest.raises(AppError, match='differs from its source'):
        check(content, story)
