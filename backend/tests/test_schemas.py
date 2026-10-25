import pytest
from pydantic import ValidationError

from app import schemas


def test_test_suite_requires_all_four_categories(test_content):
    data = test_content.model_dump()
    data["test_cases"][-1]["type"] = "positive"
    with pytest.raises(ValidationError, match="Missing test case categories"):
        schemas.TestCaseSetContent.model_validate(data)


def test_review_schema_round_trip(review_content):
    assert review_content.model_validate(review_content.model_dump()).language == "vi"
    assert review_content.missing_acceptance_criteria[0].severity == "high"
