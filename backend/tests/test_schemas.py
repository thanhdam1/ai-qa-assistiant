from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app import schemas
from app.errors import AppError
from app.services import workflow
from app.services.identity import acceptance_criterion_sources, criterion_source_id
from app.services.workflow import (
    _normalize_coverage_matrix,
    _normalize_requirement_ids,
    _validate_coverage_content,
)


def test_category_coverage_is_validated_by_workflow_not_schema(test_content):
    data = test_content.model_dump()
    data["test_cases"][-1]["type"] = "positive"
    content = schemas.TestCaseSetContent.model_validate(data)
    with pytest.raises(AppError, match="Coverage matrix must contain exactly one row"):
        _validate_coverage_content(content)


def test_review_schema_round_trip(review_content):
    assert review_content.model_validate(review_content.model_dump()).language == "vi"
    assert review_content.missing_acceptance_criteria[0].severity == "high"


def test_missing_traceability_names_each_test_case(test_content):
    data = test_content.model_dump(mode="json")
    for index in (0, 2):
        data["test_cases"][index]["requirement_traceability"] = []
        data["test_cases"][index]["api_traceability"] = []
    with pytest.raises(ValidationError) as error:
        schemas.TestCaseSetContent.model_validate(data)
    locations = {tuple(item["loc"]) for item in error.value.errors()}
    assert ("test_cases", 0) in locations
    assert ("test_cases", 2) in locations
    message = str(error.value)
    assert "TC-001" in message
    assert "TC-003" in message


def test_requirement_ids_do_not_depend_on_list_position(review_content):
    original = _normalize_requirement_ids(review_content)
    changed = review_content.model_copy(
        update={
            "existing_acceptance_criteria": [
                schemas.ExistingCriterion(
                    id="NEW", criterion="An unrelated rule", source_reference="Description"
                ),
                *review_content.existing_acceptance_criteria,
            ]
        }
    )
    normalized_changed = _normalize_requirement_ids(changed)
    assert original.existing_acceptance_criteria[0].id == normalized_changed.existing_acceptance_criteria[1].id
    assert len(original.existing_acceptance_criteria[0].obligations) == 1
    assert original.existing_acceptance_criteria[0].obligations[0].id.startswith("OBL-")


def test_coverage_matrix_tracks_each_requirement_obligation(review_content, test_content):
    normalized_review = _normalize_requirement_ids(review_content)
    normalized_suite = _normalize_coverage_matrix(test_content, normalized_review, None)
    obligation = normalized_review.existing_acceptance_criteria[0].obligations[0]
    rows = [
        entry for entry in normalized_suite.coverage_matrix
        if entry.target_type == schemas.CoverageTargetType.requirement_obligation
    ]
    assert len(rows) == 1
    assert rows[0].target_id == obligation.id
    assert rows[0].status == schemas.CoverageStatus.needs_clarification


def test_source_identity_survives_ai_paraphrase(review_content):
    story = SimpleNamespace(
        acceptance_criteria=["Both wallets belong to the customer"],
        description="", business_context="", dependencies=[],
    )
    source_id = acceptance_criterion_sources(story)[0]["source_id"]
    first = review_content.model_copy(update={"existing_acceptance_criteria": [
        schemas.ExistingCriterion(
            id="AC-001", criterion="Both wallets belong to the customer",
            source_reference="AC 1", source_id=source_id,
        )
    ]})
    normalized = _normalize_requirement_ids(first, story)
    paraphrased = first.model_copy(update={"existing_acceptance_criteria": [
        schemas.ExistingCriterion(
            id="AI-NEW", criterion="The customer owns both wallets",
            source_reference="acceptance_criteria[0]", source_id=source_id,
        )
    ]})
    updated = _normalize_requirement_ids(paraphrased, story, normalized)
    assert updated.existing_acceptance_criteria[0].id == normalized.existing_acceptance_criteria[0].id
    assert updated.existing_acceptance_criteria[0].revision == 2
    assert updated.existing_acceptance_criteria[0].obligations[0].id == normalized.existing_acceptance_criteria[0].obligations[0].id


def test_context_rule_identity_uses_source_statement():
    story = SimpleNamespace(
        acceptance_criteria=[], description="",
        business_context="Both balance changes occur atomically. A receipt is created later.",
        dependencies=[],
    )
    first = schemas.ExistingCriterion(
        id="A", criterion="Atomic balance update",
        source_reference="Both balance changes occur",
    )
    second = schemas.ExistingCriterion(
        id="B", criterion="Either both balances change or neither does",
        source_reference="occur atomically",
    )
    assert criterion_source_id(first, story) == criterion_source_id(second, story)


def test_review_cannot_omit_a_source_acceptance_criterion(review_content):
    story = SimpleNamespace(
        acceptance_criteria=["A", "B"], description="", business_context="", dependencies=[],
    )
    normalized = _normalize_requirement_ids(review_content, story)
    with pytest.raises(AppError, match="Every source acceptance criterion"):
        workflow._validate_requirement_review(normalized, story)
