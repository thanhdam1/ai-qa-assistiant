from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Severity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class FindingClassification(str, Enum):
    requirement = "requirement"
    recommendation = "recommendation"
    needs_clarification = "needs_clarification"


class Priority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ReviewItem(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=240)
    detail: str = Field(min_length=1)
    severity: Severity
    source_reference: str = Field(description="Quote or precise reference to the source story")
    classification: FindingClassification = Field(
        default=FindingClassification.recommendation,
        description="Whether this is a stated requirement, AI recommendation, or unresolved question",
    )


class ExistingCriterion(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    criterion: str = Field(min_length=1)
    source_reference: str


class RequirementReviewContent(BaseModel):
    language: Literal["vi", "en"]
    business_summary: str = Field(min_length=1)
    existing_acceptance_criteria: list[ExistingCriterion]
    missing_acceptance_criteria: list[ReviewItem]
    ambiguities_and_conflicts: list[ReviewItem]
    stakeholder_questions: list[ReviewItem]
    edge_cases: list[ReviewItem]
    assumptions: list[ReviewItem]
    risks: list[ReviewItem]


class TestCaseType(str, Enum):
    positive = "positive"
    negative = "negative"
    boundary = "boundary"
    integration = "integration"


class TestStep(BaseModel):
    order: int = Field(ge=1)
    action: str = Field(min_length=1)
    expected_result: str = Field(min_length=1)


class TestCase(BaseModel):
    id: str = Field(pattern=r"^TC-[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=240)
    objective: str = Field(min_length=1)
    type: TestCaseType
    basis: Literal["requirement", "recommendation"] = Field(
        default="recommendation",
        description="Requirement means explicitly supported by the story; recommendation is additional QA coverage"
    )
    priority: Priority
    preconditions: list[str]
    test_data: list[str]
    steps: list[TestStep] = Field(min_length=1)
    expected_result: str = Field(min_length=1)
    requirement_traceability: list[str] = Field(min_length=1)
    assumptions: list[str]
    needs_clarification: bool


class CoverageTargetType(str, Enum):
    acceptance_criterion = "acceptance_criterion"
    risk = "risk"
    category = "category"


class CoverageStatus(str, Enum):
    covered = "covered"
    needs_clarification = "needs_clarification"


class CoverageEntry(BaseModel):
    target_type: CoverageTargetType
    target_id: str = Field(min_length=1, max_length=120)
    status: CoverageStatus
    test_case_ids: list[str] = Field(default_factory=list)
    explanation: str = Field(min_length=1)


class TestCaseSetContent(BaseModel):
    language: Literal["vi", "en"]
    coverage_summary: str = Field(min_length=1)
    test_cases: list[TestCase] = Field(min_length=1)
    coverage_matrix: list[CoverageEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def includes_all_categories(self) -> TestCaseSetContent:
        case_ids = {case.id for case in self.test_cases}
        if len(case_ids) != len(self.test_cases):
            raise ValueError("Test case IDs must be unique")
        matrix_keys = [(entry.target_type, entry.target_id) for entry in self.coverage_matrix]
        if len(set(matrix_keys)) != len(matrix_keys):
            raise ValueError("Coverage matrix targets must be unique")
        for entry in self.coverage_matrix:
            unknown_ids = set(entry.test_case_ids) - case_ids
            if unknown_ids:
                raise ValueError(f"Coverage references unknown test case IDs: {', '.join(sorted(unknown_ids))}")
            if entry.status == CoverageStatus.covered and not entry.test_case_ids:
                raise ValueError("Covered targets must reference at least one test case")
            if entry.status == CoverageStatus.needs_clarification and not entry.explanation.strip():
                raise ValueError("Unresolved coverage targets need an explanation")
            if entry.target_type != CoverageTargetType.category:
                for case in self.test_cases:
                    if case.id in entry.test_case_ids and entry.target_id not in case.requirement_traceability:
                        raise ValueError(
                            f"Test case {case.id} must trace coverage target {entry.target_id}"
                        )
        if not self.coverage_matrix:
            return self
        for category in TestCaseType:
            entries = [
                entry for entry in self.coverage_matrix
                if entry.target_type == CoverageTargetType.category and entry.target_id == category.value
            ]
            if len(entries) != 1:
                raise ValueError(f"Coverage matrix must report category {category.value} exactly once")
            has_case = any(case.type == category for case in self.test_cases)
            if has_case != (entries[0].status == CoverageStatus.covered):
                raise ValueError(f"Category coverage status does not match generated {category.value} tests")
        return self


class StoryBase(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=30_000)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=100)
    business_context: str | None = Field(default=None, max_length=10_000)
    dependencies: list[str] = Field(default_factory=list, max_length=100)
    language: Literal["auto", "vi", "en"] = "auto"


class StoryCreate(StoryBase):
    pass


class StoryUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, min_length=1, max_length=30_000)
    acceptance_criteria: list[str] | None = Field(default=None, max_length=100)
    business_context: str | None = Field(default=None, max_length=10_000)
    dependencies: list[str] | None = Field(default=None, max_length=100)
    language: Literal["auto", "vi", "en"] | None = None


class StoryRead(StoryBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    version: int
    created_at: datetime
    updated_at: datetime


class ReviewUpdate(BaseModel):
    content: RequirementReviewContent


class RequirementReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    story_id: str
    story_version: int
    ai_original: RequirementReviewContent
    content: RequirementReviewContent
    status: Literal["draft", "approved"]
    stale: bool
    model_name: str
    prompt_version: str
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TestCaseSetCreate(BaseModel):
    review_id: str


class TestCaseSetUpdate(BaseModel):
    content: TestCaseSetContent


class TestCaseSetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    story_id: str
    review_id: str
    story_version: int
    ai_original: TestCaseSetContent
    content: TestCaseSetContent
    status: Literal["draft", "approved"]
    stale: bool
    model_name: str
    prompt_version: str
    generation_info: dict
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class StoryWorkspace(StoryRead):
    reviews: list[RequirementReviewRead]
    test_case_sets: list[TestCaseSetRead]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody
