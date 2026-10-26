import pytest
from app.errors import AppError
from app.services.workflow import (
    _normalize_requirement_ids,
    _normalize_coverage_matrix,
    _validate_coverage_content,
)

from app import schemas


def test_category_coverage_is_validated_by_workflow_not_schema(test_content):
    data = test_content.model_dump()
    data["test_cases"][-1]["type"] = "positive"
    content = schemas.TestCaseSetContent.model_validate(data)
    with pytest.raises(AppError, match="Coverage matrix must contain exactly one row"):
        _validate_coverage_content(content)


def test_review_schema_round_trip(review_content):
    assert review_content.model_validate(review_content.model_dump()).language == "vi"
    assert review_content.missing_acceptance_criteria[0].severity == "high"


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
