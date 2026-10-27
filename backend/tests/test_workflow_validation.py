from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.database import Base, SessionLocal, engine
from app.errors import AIProviderError, AppError
from app.models import RequirementReview, Story
from app.schemas import CoverageAssertion, CoverageStatus, CoverageTargetType
from app.schemas import TestCaseSetContent as SuiteContent
from app.services import workflow


def test_generate_and_approval_reject_the_same_step_order(review_content, test_content):
    review = workflow._normalize_requirement_ids(review_content)
    invalid = test_content.model_dump(mode="json")
    invalid["test_cases"][0]["steps"][0]["order"] = 2
    suite = SuiteContent.model_validate(invalid)
    with pytest.raises(AppError) as generated:
        workflow._prepare_generated_test_suite(suite, review, None, None, {"AC-001"})
    assert generated.value.code == "invalid_test_case_steps"

    normalized = workflow._normalize_coverage_matrix(suite, review, None)
    with pytest.raises(AppError) as approved:
        workflow.validate_test_suite(normalized, review, None, None, {"AC-001"})
    assert approved.value.code == generated.value.code


def test_coverage_requires_exact_assertion_evidence(review_content, test_content):
    review = workflow._normalize_requirement_ids(review_content)
    obligation_id = review.existing_acceptance_criteria[0].obligations[0].id
    data = test_content.model_dump(mode="json")
    data["test_cases"][0]["requirement_traceability"].append(obligation_id)
    data["coverage_matrix"] = [{
        "target_type": "requirement_obligation", "target_id": obligation_id,
        "status": "covered", "test_case_ids": ["TC-001"], "explanation": "Linked",
    }]
    normalized = workflow._normalize_coverage_matrix(SuiteContent.model_validate(data), review, None)
    row = next(item for item in normalized.coverage_matrix if item.target_type == CoverageTargetType.requirement_obligation)
    assert row.status == CoverageStatus.needs_clarification
    bypass = normalized.model_copy(update={"coverage_matrix": [
        item.model_copy(update={"status": CoverageStatus.covered})
        if item.target_id == obligation_id else item
        for item in normalized.coverage_matrix
    ]})
    with pytest.raises(AppError) as missing:
        workflow.validate_test_suite(bypass, review, None, None, {"AC-001"})
    assert missing.value.code == "missing_coverage_assertion"
    data["coverage_matrix"][0]["assertion_evidence"] = [{
        "test_case_id": "TC-001", "assertion": "Expected behavior occurs",
        "verifies_business_outcome": True,
    }]
    covered = workflow._normalize_coverage_matrix(SuiteContent.model_validate(data), review, None)
    row = next(item for item in covered.coverage_matrix if item.target_type == CoverageTargetType.requirement_obligation)
    assert row.status == CoverageStatus.covered
    bad = row.model_copy(update={"assertion_evidence": [CoverageAssertion(
        test_case_id="TC-001", assertion="Invented assertion", verifies_business_outcome=True,
    )]})
    invalid = covered.model_copy(update={"coverage_matrix": [
        bad if item.target_id == obligation_id else item for item in covered.coverage_matrix
    ]})
    with pytest.raises(AppError) as exc:
        workflow._validate_coverage_content(invalid)
    assert exc.value.code == "invalid_coverage_evidence"


def test_legacy_validation_failure_does_not_commit(monkeypatch, review_content, test_content):
    review = SimpleNamespace(
        content=review_content.model_dump(mode="json"),
        ai_original=review_content.model_dump(mode="json"),
    )
    monkeypatch.setattr(workflow, "get_review", lambda _db, _id: review)
    monkeypatch.setattr(workflow, "get_story", lambda _db, _id: SimpleNamespace(
        acceptance_criteria=[], description="", business_context="", dependencies=[]
    ))
    db = Mock()
    test_set = SimpleNamespace(story_id="story", review_id="legacy-review", api_contract_review_id=None)
    with pytest.raises(AppError, match="Coverage matrix"):
        workflow._validate_test_suite_context(db, test_set, test_content)
    db.commit.assert_not_called()


def test_semantic_error_reaches_repair_before_persistence(review_content, test_content):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    class FakeAI:
        model_name = "fake"
        repair_issues = None

        async def generate_test_cases(self, *_args):
            invalid = test_content.model_dump(mode="json")
            invalid["test_cases"][0]["steps"][0]["order"] = 2
            return SuiteContent.model_validate(invalid)

        async def repair_test_cases(self, _story, _review, _api_review, _spec, _previous, issues):
            self.repair_issues = issues
            return test_content

    with SessionLocal() as db:
        story = Story(title="Story", description="A user signs in", acceptance_criteria=[])
        db.add(story)
        db.commit()
        db.refresh(story)
        review = RequirementReview(
            story_id=story.id, story_version=story.version, status="approved",
            ai_original=review_content.model_dump(mode="json"),
            content=workflow._normalize_requirement_ids(review_content).model_dump(mode="json"),
            idempotency_key="review", model_name="fake", prompt_version="test",
        )
        db.add(review)
        db.commit()
        db.refresh(review)
        ai = FakeAI()
        coroutine = workflow.generate_test_set(db, story.id, review.id, "suite", ai)
        with pytest.raises(StopIteration) as finished:
            coroutine.send(None)
        assert finished.value.value.id
        assert ai.repair_issues[0]["code"] == "invalid_test_case_steps"
        assert finished.value.value.ai_original["test_cases"][0]["steps"][0]["order"] == 2
        assert finished.value.value.content["test_cases"][0]["steps"][0]["order"] == 1

        class StillInvalid(FakeAI):
            async def repair_test_cases(self, *_args):
                return await self.generate_test_cases(None, None)

        failed = workflow.generate_test_set(db, story.id, review.id, "suite-bad", StillInvalid())
        with pytest.raises(AIProviderError) as error:
            failed.send(None)
        assert "invalid_test_case_steps" in error.value.message
        assert "TC-001" in error.value.message
        failures = error.value.details["validation"]["failures"]
        assert [item["code"] for item in failures] == [
            "invalid_test_case_steps", "invalid_test_case_steps"
        ]

        class OrphanApiAI:
            model_name = "fake"

            async def generate_test_cases(self, *_args):
                data = test_content.model_dump(mode="json")
                data["test_cases"][0].update({
                    "api_method": "POST", "api_path": "/redemptions",
                    "api_request": "{}", "expected_status_codes": [201],
                })
                return SuiteContent.model_validate(data)

            async def repair_test_cases(self, *_args):
                data = test_content.model_dump(mode="json")
                data["test_cases"][0]["expected_status_codes"] = [201]
                return SuiteContent.model_validate(data)

        fallback = workflow.generate_test_set(
            db, story.id, review.id, "suite-orphan-api", OrphanApiAI()
        )
        with pytest.raises(StopIteration) as completed:
            fallback.send(None)
        draft = completed.value.value
        case = draft.content["test_cases"][0]
        assert draft.generation_info["quarantined_api_case_ids"] == ["TC-001"]
        assert draft.ai_original["test_cases"][0]["api_method"] == "POST"
        assert case["api_method"] is None
        assert case["expected_status_codes"] == []
        assert case["needs_clarification"] is True
        assert "Đề xuất AI chưa xác minh" in case["expected_result"]
