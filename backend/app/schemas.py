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


class ApiFindingType(str, Enum):
    positive = "positive"
    negative = "negative"
    boundary = "boundary"
    schema = "schema"
    security = "security"
    gap = "gap"
    conflict = "conflict"


class ApiOperationSummary(BaseModel):
    operation_id: str
    method: str
    path: str
    summary: str = ""


class ApiContractFinding(BaseModel):
    id: str = Field(pattern=r"^API-[A-Za-z0-9_-]+$")
    operation_id: str
    method: str
    path: str
    type: ApiFindingType
    title: str = Field(min_length=1, max_length=240)
    detail: str = Field(min_length=1)
    severity: Severity
    classification: FindingClassification
    source_reference: str = Field(min_length=1, description="OpenAPI operation or JSON Pointer")
    story_reference: str | None = None
    expected_status_codes: list[int] = Field(default_factory=list)
    needs_clarification: bool


class ApiContractReviewContent(BaseModel):
    language: Literal["vi", "en"]
    summary: str = Field(min_length=1)
    operations: list[ApiOperationSummary]
    findings: list[ApiContractFinding]


class ApiSpecificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    story_id: str
    title: str
    file_name: str
    openapi_version: str
    version: int
    operations: list[ApiOperationSummary]
    checksum: str
    stale: bool
    created_at: datetime


class ApiContractReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    story_id: str
    specification_id: str
    story_version: int
    ai_original: ApiContractReviewContent
    content: ApiContractReviewContent
    status: Literal["draft", "approved"]
    stale: bool
    model_name: str
    prompt_version: str
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


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
    requirement_traceability: list[str] = Field(default_factory=list)
    api_traceability: list[str] = Field(default_factory=list)
    api_method: str | None = None
    api_path: str | None = None
    api_request: str | None = None
    expected_status_codes: list[int] = Field(default_factory=list)
    assumptions: list[str]
    needs_clarification: bool

class CoverageTargetType(str, Enum):
    acceptance_criterion = "acceptance_criterion"
    risk = "risk"
    category = "category"
    api_check = "api_check"


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
        if any(
            not case.requirement_traceability and not case.api_traceability
            for case in self.test_cases
        ):
            raise ValueError("Test cases need traceability to a requirement or API finding")
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
    api_contract_review_id: str | None = None


class TestCaseSetUpdate(BaseModel):
    content: TestCaseSetContent


class TestCaseSetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    story_id: str
    review_id: str
    api_contract_review_id: str | None = None
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
    api_specifications: list[ApiSpecificationRead] = Field(default_factory=list)
    api_contract_reviews: list[ApiContractReviewRead] = Field(default_factory=list)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody
