import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.errors import AppError, StaleVersionError
from app.models import Base, RequirementReview, Story, TestCaseSet
from app.schemas import (
    AcceptRecommendationInput,
    BatchCoverageDecisionInput,
    CoverageAssertion,
    CoverageDecisionInput,
    CoverageEntry,
    CoverageStatus,
    CoverageTargetType,
    ExistingCriterion,
    FindingClassification,
    Priority,
    RequirementObligation,
    RequirementReviewContent,
    ReviewItem,
    Severity,
    TestCase,
    TestCaseSetContent,
    TestCaseType,
    TestStep,
)
from app.services.workflow import (
    accept_story_recommendation,
    decide_batch_coverage_targets,
    heal_test_set_coverage_gaps,
)


@pytest.fixture
def mem_session():
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    TestingSession = sessionmaker(bind=test_engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(test_engine)


def test_accept_story_recommendation_from_review(mem_session):
    story = Story(
        id="story-auth-1",
        title="Đăng nhập và phân quyền",
        description="Là người dùng tôi muốn đăng nhập...",
        acceptance_criteria=[
            "AC-01: Đăng nhập thành công với email và mật khẩu",
            "AC-02: Sai mật khẩu trả về HTTP 401",
        ],
        business_context="Bối cảnh bảo mật...",
        dependencies=["users"],
        language="vi",
        version=1,
    )
    mem_session.add(story)
    mem_session.flush()

    review_content = RequirementReviewContent(
        language="vi",
        business_summary="Tóm tắt đăng nhập...",
        existing_acceptance_criteria=[],
        missing_acceptance_criteria=[
            ReviewItem(
                id="MAC-1",
                title="Chặn truy cập /admin đối với Customer",
                detail="Cần có AC chặn người dùng vai trò Customer hoặc Guest truy cập vào /admin với mã HTTP 403.",
                severity=Severity.high,
                source_reference="business_context",
                classification=FindingClassification.recommendation,
            )
        ],
        ambiguities_and_conflicts=[],
        stakeholder_questions=[],
        edge_cases=[],
        assumptions=[],
        risks=[],
    )

    review = RequirementReview(
        id="rev-1",
        story_id=story.id,
        story_version=1,
        idempotency_key="idemp-rev-1",
        ai_original=review_content.model_dump(mode="json"),
        content=review_content.model_dump(mode="json"),
        status="approved",
        stale=False,
        model_name="test-model",
        prompt_version="review-v4",
    )
    mem_session.add(review)
    mem_session.commit()

    # 1. Accept recommendation without custom text (auto extracts title + detail)
    updated = accept_story_recommendation(
        mem_session,
        story.id,
        AcceptRecommendationInput(finding_id="MAC-1"),
    )

    assert updated.version == 2
    assert len(updated.acceptance_criteria) == 3
    assert updated.acceptance_criteria[2] == (
        "AC-03: [Chặn truy cập /admin đối với Customer] "
        "Cần có AC chặn người dùng vai trò Customer hoặc Guest truy cập vào /admin với mã HTTP 403."
    )

    # Verify review is marked stale
    mem_session.refresh(review)
    assert review.stale is True

    # 2. Accept with custom text
    updated_custom = accept_story_recommendation(
        mem_session,
        story.id,
        AcceptRecommendationInput(
            finding_id="MAC-CUSTOM",
            custom_text="Khi tài khoản bị khóa thì không cho phép đăng nhập",
        ),
    )
    assert updated_custom.version == 3
    assert len(updated_custom.acceptance_criteria) == 4
    assert updated_custom.acceptance_criteria[3] == (
        "AC-04: Khi tài khoản bị khóa thì không cho phép đăng nhập"
    )


def test_batch_coverage_decisions(mem_session):
    story = Story(
        id="story-batch-1",
        title="Batch decision story",
        description="Description",
        acceptance_criteria=["AC-01: Rule 1", "AC-02: Rule 2"],
        business_context="Context",
        dependencies=[],
        language="vi",
        version=1,
    )
    mem_session.add(story)
    mem_session.flush()

    review_content = RequirementReviewContent(
        language="vi",
        business_summary="Summary",
        existing_acceptance_criteria=[
            ExistingCriterion(
                id="AC-01",
                criterion="Rule 1",
                source_reference="acceptance_criteria[0]",
                obligations=[RequirementObligation(id="OBL-1", text="Rule 1 obligation")],
            ),
            ExistingCriterion(
                id="AC-02",
                criterion="Rule 2",
                source_reference="acceptance_criteria[1]",
                obligations=[RequirementObligation(id="OBL-2", text="Rule 2 obligation")],
            ),
        ],
        missing_acceptance_criteria=[],
        ambiguities_and_conflicts=[],
        stakeholder_questions=[],
        edge_cases=[],
        assumptions=[],
        risks=[],
    )

    review = RequirementReview(
        id="rev-batch-1",
        story_id=story.id,
        story_version=1,
        idempotency_key="idemp-batch-rev",
        ai_original=review_content.model_dump(mode="json"),
        content=review_content.model_dump(mode="json"),
        status="approved",
        stale=False,
        model_name="test-model",
        prompt_version="review-v4",
    )
    mem_session.add(review)
    mem_session.flush()

    tc1 = TestCase(
        id="TC-001",
        title="Test for Rule 1",
        objective="Verify Rule 1",
        type=TestCaseType.positive,
        basis="requirement",
        priority=Priority.medium,
        preconditions=[],
        test_data=[],
        steps=[TestStep(order=1, action="Execute", expected_result="Success")],
        expected_result="Success",
        requirement_traceability=["OBL-1"],
        upstream_traceability=[],
        assumptions=[],
        needs_clarification=False,
    )

    category_entries = [
        CoverageEntry(
            target_type=CoverageTargetType.category,
            target_id=cat.value,
            status=CoverageStatus.covered if cat == TestCaseType.positive else CoverageStatus.needs_clarification,
            test_case_ids=["TC-001"] if cat == TestCaseType.positive else [],
            explanation=f"Category {cat.value}",
            assertion_evidence=[],
            unverified_aspects=[],
        )
        for cat in TestCaseType
    ]

    content = TestCaseSetContent(
        language="vi",
        coverage_summary="Summary",
        test_cases=[tc1],
        coverage_matrix=category_entries + [
            CoverageEntry(
                target_type=CoverageTargetType.requirement_obligation,
                target_id="OBL-1",
                status=CoverageStatus.covered,
                test_case_ids=["TC-001"],
                explanation="Covered by TC-001",
                assertion_evidence=[
                    CoverageAssertion(
                        test_case_id="TC-001",
                        assertion="Success",
                        verifies_business_outcome=True,
                    )
                ],
                unverified_aspects=[],
            ),
            CoverageEntry(
                target_type=CoverageTargetType.requirement_obligation,
                target_id="OBL-2",
                status=CoverageStatus.needs_clarification,
                test_case_ids=[],
                explanation="No test yet",
                assertion_evidence=[],
                unverified_aspects=[],
            ),
        ],
    )

    test_set = TestCaseSet(
        id="ts-batch-1",
        story_id=story.id,
        review_id=review.id,
        story_version=1,
        idempotency_key="idemp-ts-batch",
        ai_original=content.model_dump(mode="json"),
        content=content.model_dump(mode="json"),
        status="draft",
        stale=False,
        model_name="test-model",
        prompt_version="testcase-v12",
        generation_info={},
    )
    mem_session.add(test_set)
    mem_session.commit()

    # Apply batch decisions:
    # OBL-1 -> confirmed (using assertion from TC-001)
    # OBL-2 -> accepted_risk (with reason)
    batch_input = BatchCoverageDecisionInput(
        decisions=[
            CoverageDecisionInput(
                target_type=CoverageTargetType.requirement_obligation,
                target_id="OBL-1",
                disposition="confirmed",
                decided_by="QA Lead",
                assertion_case_id="TC-001",
                assertion="Success",
            ),
            CoverageDecisionInput(
                target_type=CoverageTargetType.requirement_obligation,
                target_id="OBL-2",
                disposition="accepted_risk",
                decided_by="QA Lead",
                reason="Kiểm chứng tại unit test nội bộ",
            ),
        ]
    )

    updated_ts = decide_batch_coverage_targets(mem_session, test_set.id, batch_input)

    assert len(updated_ts.coverage_decisions) == 2
    d1 = next((d for d in updated_ts.coverage_decisions if d["target_id"] == "OBL-1"), None)
    d2 = next((d for d in updated_ts.coverage_decisions if d["target_id"] == "OBL-2"), None)
    assert d1 is not None and d1["disposition"] == "confirmed"
    assert d2 is not None and d2["disposition"] == "accepted_risk"


@pytest.fixture
def heal_setup(mem_session):
    story = Story(
        id="story-heal-1",
        title="Heal Gaps Story",
        description="Description",
        acceptance_criteria=["AC-01: Rule 1", "AC-02: Rule 2"],
        business_context="Context",
        dependencies=[],
        language="vi",
        version=1,
    )
    mem_session.add(story)
    mem_session.flush()

    review_content = RequirementReviewContent(
        language="vi",
        business_summary="Summary",
        existing_acceptance_criteria=[
            ExistingCriterion(
                id="AC-01",
                criterion="Rule 1",
                source_reference="acceptance_criteria[0]",
                obligations=[RequirementObligation(id="OBL-1", text="Rule 1 obligation")],
            ),
            ExistingCriterion(
                id="AC-02",
                criterion="Rule 2",
                source_reference="acceptance_criteria[1]",
                obligations=[RequirementObligation(id="OBL-2", text="Rule 2 obligation")],
            ),
        ],
        missing_acceptance_criteria=[],
        ambiguities_and_conflicts=[],
        stakeholder_questions=[],
        edge_cases=[],
        assumptions=[],
        risks=[],
    )

    review = RequirementReview(
        id="rev-heal-1",
        story_id=story.id,
        story_version=1,
        idempotency_key="idemp-heal-rev",
        ai_original=review_content.model_dump(mode="json"),
        content=review_content.model_dump(mode="json"),
        status="approved",
        stale=False,
        model_name="test-model",
        prompt_version="review-v4",
    )
    mem_session.add(review)
    mem_session.flush()

    tc1 = TestCase(
        id="TC-001",
        title="Test for Rule 1",
        objective="Verify Rule 1",
        type=TestCaseType.positive,
        basis="requirement",
        priority=Priority.medium,
        preconditions=[],
        test_data=[],
        steps=[TestStep(order=1, action="Execute", expected_result="Success")],
        expected_result="Success",
        requirement_traceability=["OBL-1"],
        upstream_traceability=[],
        assumptions=[],
        needs_clarification=False,
        is_customized=True,
    )

    category_entries = [
        CoverageEntry(
            target_type=CoverageTargetType.category,
            target_id=cat.value,
            status=CoverageStatus.covered if cat == TestCaseType.positive else CoverageStatus.needs_clarification,
            test_case_ids=["TC-001"] if cat == TestCaseType.positive else [],
            explanation=f"Category {cat.value}",
            assertion_evidence=[],
            unverified_aspects=[],
        )
        for cat in TestCaseType
    ]

    initial_content = TestCaseSetContent(
        language="vi",
        coverage_summary="Initial summary",
        test_cases=[tc1],
        coverage_matrix=category_entries + [
            CoverageEntry(
                target_type=CoverageTargetType.requirement_obligation,
                target_id="OBL-1",
                status=CoverageStatus.covered,
                test_case_ids=["TC-001"],
                explanation="Covered by TC-001",
                assertion_evidence=[
                    CoverageAssertion(
                        test_case_id="TC-001",
                        assertion="Success",
                        verifies_business_outcome=True,
                    )
                ],
                unverified_aspects=[],
            ),
            CoverageEntry(
                target_type=CoverageTargetType.requirement_obligation,
                target_id="OBL-2",
                status=CoverageStatus.needs_clarification,
                test_case_ids=[],
                explanation="Gap - missing assertion",
                assertion_evidence=[],
                unverified_aspects=["Rule 2 unverified"],
            ),
        ],
    )

    test_set = TestCaseSet(
        id="ts-heal-1",
        story_id=story.id,
        review_id=review.id,
        story_version=1,
        content_version=1,
        idempotency_key="idemp-ts-heal",
        ai_original=initial_content.model_dump(mode="json"),
        content=initial_content.model_dump(mode="json"),
        status="draft",
        stale=False,
        model_name="test-model",
        prompt_version="testcase-v12",
        generation_info={},
    )
    mem_session.add(test_set)
    mem_session.commit()

    class MockAI:
        async def heal_coverage_gaps(
            self,
            story,
            review,
            api_review,
            specification,
            current_suite,
            unresolved_targets,
            upstream_contracts=None,
        ):
            tc2 = TestCase(
                id="TC-002",
                title="Boundary test for Rule 2",
                objective="Verify Rule 2 boundary",
                type=TestCaseType.boundary,
                basis="requirement",
                priority=Priority.high,
                preconditions=[],
                test_data=[],
                steps=[TestStep(order=1, action="Verify boundary", expected_result="Boundary condition verified")],
                expected_result="Boundary condition verified",
                requirement_traceability=["OBL-2"],
                upstream_traceability=[],
                assumptions=[],
                needs_clarification=False,
            )

            healed_cats = [
                CoverageEntry(
                    target_type=CoverageTargetType.category,
                    target_id=cat.value,
                    status=CoverageStatus.covered
                    if cat in (TestCaseType.positive, TestCaseType.boundary)
                    else CoverageStatus.needs_clarification,
                    test_case_ids=["TC-001"]
                    if cat == TestCaseType.positive
                    else ["TC-002"]
                    if cat == TestCaseType.boundary
                    else [],
                    explanation=f"Category {cat.value}",
                    assertion_evidence=[],
                    unverified_aspects=[],
                )
                for cat in TestCaseType
            ]

            return TestCaseSetContent(
                language="vi",
                coverage_summary="Healed summary",
                test_cases=[tc1, tc2],
                coverage_matrix=healed_cats + [
                    CoverageEntry(
                        target_type=CoverageTargetType.requirement_obligation,
                        target_id="OBL-1",
                        status=CoverageStatus.covered,
                        test_case_ids=["TC-001"],
                        explanation="Covered by TC-001",
                        assertion_evidence=[
                            CoverageAssertion(
                                test_case_id="TC-001",
                                assertion="Success",
                                verifies_business_outcome=True,
                            )
                        ],
                        unverified_aspects=[],
                    ),
                    CoverageEntry(
                        target_type=CoverageTargetType.requirement_obligation,
                        target_id="OBL-2",
                        status=CoverageStatus.covered,
                        test_case_ids=["TC-002"],
                        explanation="Covered by TC-002",
                        assertion_evidence=[
                            CoverageAssertion(
                                test_case_id="TC-002",
                                assertion="Boundary condition verified",
                                verifies_business_outcome=True,
                            )
                        ],
                        unverified_aspects=[],
                    ),
                ],
            )

    return mem_session, test_set, MockAI()


def test_heal_test_set_coverage_gaps(heal_setup):
    mem_session, test_set, ai = heal_setup
    original_case = test_set.content["test_cases"][0].copy()
    test_set.status = "approved"
    test_set.approved_at = datetime.now(UTC)
    test_set.coverage_accepted_at = datetime.now(UTC)
    test_set.coverage_accepted_by = "QA"
    test_set.coverage_decisions = [{"target_id": "OBL-1"}]
    test_set.case_readiness = [{"case_id": "TC-001"}]
    mem_session.commit()
    coro = heal_test_set_coverage_gaps(mem_session, test_set.id, ai)
    with pytest.raises(StopIteration) as finished:
        coro.send(None)
    healed_result = finished.value.value

    assert healed_result.status == "draft"
    assert healed_result.approved_at is None
    assert healed_result.coverage_accepted_at is None
    assert healed_result.coverage_accepted_by is None
    assert healed_result.coverage_decisions == []
    assert healed_result.case_readiness == []
    assert healed_result.content["test_cases"][0] == original_case
    assert healed_result.content_version == 2
    cases = healed_result.content["test_cases"]
    assert len(cases) == 2
    tc1_saved = next(c for c in cases if c["id"] == "TC-001")
    assert tc1_saved.get("is_customized") is True  # RULE-03 preserved!

    # Check coverage matrix: OBL-2 should now be covered
    matrix = healed_result.content["coverage_matrix"]
    obl2_row = next(r for r in matrix if r["target_id"] == "OBL-2")
    assert obl2_row["status"] == "covered"
    assert len(obl2_row["assertion_evidence"]) > 0



def _run(coro):
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value


@pytest.mark.parametrize("change", ["modify", "remove"])
def test_heal_rejects_changes_to_customized_case(heal_setup, change):
    db, suite, ai = heal_setup
    original = suite.content.copy()

    class ConflictingAI:
        async def heal_coverage_gaps(self, *args, **kwargs):
            result = await ai.heal_coverage_gaps(*args, **kwargs)
            if change == "modify":
                result.test_cases[0].title = "AI overwrites QA"
            else:
                result.test_cases = result.test_cases[1:]
            return result

    with pytest.raises(AppError) as error:
        _run(heal_test_set_coverage_gaps(db, suite.id, ConflictingAI()))
    assert error.value.code == "customized_case_conflict"
    assert error.value.status_code == 409
    db.refresh(suite)
    assert suite.content == original
    assert suite.content_version == 1


@pytest.mark.parametrize("source", ["suite", "review", "story_version", "review_approval"])
def test_heal_rejects_stale_sources_before_ai(heal_setup, source):
    db, suite, _ = heal_setup
    if source == "suite":
        suite.stale = True
    elif source == "review":
        db.get(RequirementReview, suite.review_id).stale = True
    elif source == "review_approval":
        db.get(RequirementReview, suite.review_id).status = "draft"
    else:
        db.get(Story, suite.story_id).version += 1
    db.commit()

    class NeverCalledAI:
        async def heal_coverage_gaps(self, *args, **kwargs):
            pytest.fail("AI must not run for stale sources")

    with pytest.raises(StaleVersionError):
        _run(heal_test_set_coverage_gaps(db, suite.id, NeverCalledAI()))
    assert suite.content_version == 1


@pytest.mark.parametrize("change", ["suite_version", "story_version", "review_stale"])
def test_heal_rechecks_sources_after_ai(heal_setup, change):
    db, suite, ai = heal_setup
    original = suite.content.copy()

    class ConcurrentAI:
        async def heal_coverage_gaps(self, *args, **kwargs):
            result = await ai.heal_coverage_gaps(*args, **kwargs)
            # A separate session simulates an edit committed during the provider call.
            with sessionmaker(bind=db.get_bind())() as other:
                if change == "suite_version":
                    other.get(TestCaseSet, suite.id).content_version += 1
                elif change == "story_version":
                    other.get(Story, suite.story_id).version += 1
                else:
                    other.get(RequirementReview, suite.review_id).stale = True
                other.commit()
            return result

    with pytest.raises(StaleVersionError):
        _run(heal_test_set_coverage_gaps(db, suite.id, ConcurrentAI()))
    db.refresh(suite)
    assert suite.content == original
    assert suite.content_version == (2 if change == "suite_version" else 1)


@pytest.mark.parametrize("category", ["stakeholder_questions", "assumptions"])
def test_accept_question_and_assumption_as_story_ac(heal_setup, category):
    db, suite, _ = heal_setup
    review = db.get(RequirementReview, suite.review_id)
    finding = ReviewItem(
        id="NEW-1", title="Confirmed rule", detail="Confirmed by PO",
        severity=Severity.low, source_reference="Story description",
        classification=FindingClassification.recommendation,
    )
    review.content = {**review.content, category: [finding.model_dump(mode="json")]}
    db.commit()
    story = accept_story_recommendation(
        db, suite.story_id, AcceptRecommendationInput(finding_id=finding.id)
    )
    assert story.version == 2
    assert story.acceptance_criteria[-1] == "AC-03: [Confirmed rule] Confirmed by PO"
    assert suite.stale
