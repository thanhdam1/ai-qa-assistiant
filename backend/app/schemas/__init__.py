from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class RequirementObligation(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1)
    revision: int = Field(default=1, ge=1)
    supersedes: list[str] = Field(default_factory=list)


class ExistingCriterion(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    criterion: str = Field(min_length=1)
    source_reference: str
    source_id: str | None = None
    revision: int = Field(default=1, ge=1)
    obligations: list[RequirementObligation] = Field(default_factory=list)


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

    @field_validator("expected_result", mode="before")
    @classmethod
    def normalize_step_expected_result(cls, v: Any) -> Any:
        if isinstance(v, list):
            return "\n".join(str(item).strip() for item in v if str(item).strip())
        return v


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

    @field_validator("expected_result", mode="before")
    @classmethod
    def normalize_case_expected_result(cls, v: Any) -> Any:
        if isinstance(v, list):
            return "\n".join(str(item).strip() for item in v if str(item).strip())
        return v

    @field_validator(
        "preconditions",
        "test_data",
        "assumptions",
        "requirement_traceability",
        "api_traceability",
        mode="before",
    )
    @classmethod
    def normalize_lists(cls, v: Any) -> Any:
        if isinstance(v, str):
            return [line.strip() for line in v.splitlines() if line.strip()]
        return v

    @model_validator(mode="after")
    def has_source_traceability(self) -> TestCase:
        if not self.requirement_traceability and not self.api_traceability:
            raise ValueError(
                f"Test case {self.id} needs requirement_traceability or api_traceability"
            )
        return self

class CoverageTargetType(str, Enum):
    acceptance_criterion = "acceptance_criterion"
    requirement_obligation = "requirement_obligation"
    risk = "risk"
    category = "category"
    api_check = "api_check"


class CoverageStatus(str, Enum):
    covered = "covered"
    needs_clarification = "needs_clarification"


class CoverageAssertion(BaseModel):
    test_case_id: str = Field(min_length=1)
    assertion: str = Field(min_length=1)
    verifies_business_outcome: bool


class CoverageEntry(BaseModel):
    target_type: CoverageTargetType
    target_id: str = Field(min_length=1, max_length=120)
    status: CoverageStatus
    test_case_ids: list[str] = Field(default_factory=list)
    explanation: str = Field(min_length=1)
    assertion_evidence: list[CoverageAssertion] = Field(default_factory=list)
    unverified_aspects: list[str] = Field(default_factory=list)


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


class CoverageDecisionInput(BaseModel):
    target_type: CoverageTargetType
    target_id: str = Field(min_length=1)
    disposition: Literal["confirmed", "accepted_risk", "deferred", "blocked", "not_applicable"]
    decided_by: str = Field(min_length=1, max_length=120)
    assertion_case_id: str | None = None
    assertion: str | None = None
    reason: str | None = None
    owner: str | None = None


class CoverageAcceptanceInput(BaseModel):
    accepted_by: str = Field(min_length=1, max_length=120)


class CaseReadinessInput(BaseModel):
    assessed_by: str = Field(min_length=1, max_length=120)
    environment_ready: bool
    test_data_ready: bool
    verification_ready: bool
    note: str | None = None


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
    review_status: Literal["draft", "approved"] = "draft"
    coverage_status: Literal["complete", "partial", "unsubstantiated"] = "unsubstantiated"
    coverage_acceptance_status: Literal["pending", "accepted"] = "pending"
    execution_readiness: Literal["not_assessed", "partial", "ready"] = "not_assessed"
    coverage_target_count: int = 0
    candidate_coverage_count: int = 0
    qa_confirmed_target_count: int = 0
    gap_decision_count: int = 0
    content_version: int = 1
    coverage_decisions: list[dict] = Field(default_factory=list)
    case_readiness: list[dict] = Field(default_factory=list)
    coverage_accepted_at: datetime | None = None
    coverage_accepted_by: str | None = None
    stale: bool
    model_name: str
    prompt_version: str
    generation_info: dict
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def derive_assessment(self) -> TestCaseSetRead:
        self.review_status = self.status
        if self.stale:
            self.coverage_acceptance_status = "pending"
            self.coverage_status = "unsubstantiated"
            self.execution_readiness = "not_assessed"
            return self
        targets = {
            (row.target_type.value, row.target_id)
            for row in self.content.coverage_matrix
            if row.target_type != CoverageTargetType.category
        }
        self.coverage_target_count = len(targets)
        candidates = {
            (row.target_type.value, row.target_id)
            for row in self.content.coverage_matrix
            if row.target_type != CoverageTargetType.category
            and row.status == CoverageStatus.covered
            and row.assertion_evidence
            and not row.unverified_aspects
        }
        self.candidate_coverage_count = len(candidates)
        current = [
            item for item in self.coverage_decisions
            if item.get("story_version") == self.story_version
            and item.get("review_id") == self.review_id
            and item.get("api_contract_review_id") == self.api_contract_review_id
            and item.get("api_specification_id") == self.generation_info.get("api_specification_id")
            and item.get("content_version") == self.content_version
            and (item.get("target_type"), item.get("target_id")) in targets
        ]
        confirmed = {
            (item["target_type"], item["target_id"])
            for item in current if item.get("disposition") == "confirmed"
        }
        self.qa_confirmed_target_count = len(confirmed)
        self.gap_decision_count = len(current) - len(confirmed)
        if targets and len(candidates) == len(targets):
            self.coverage_status = "complete"
        elif candidates:
            self.coverage_status = "partial"
        self.coverage_acceptance_status = "accepted" if self.coverage_accepted_at and len(current) == len(targets) else "pending"
        case_ids = {case.id for case in self.content.test_cases}
        ready = {
            item.get("case_id") for item in self.case_readiness
            if item.get("content_version") == self.content_version
            and item.get("story_version") == self.story_version
            and item.get("environment_ready") and item.get("test_data_ready") and item.get("verification_ready")
        }
        eligible = {case.id for case in self.content.test_cases if not case.needs_clarification}
        ready &= eligible
        if case_ids and ready == case_ids:
            self.execution_readiness = "ready"
        elif ready:
            self.execution_readiness = "partial"
        return self


class DependencyType(str, Enum):
    precondition = "precondition"
    data_fixture = "data_fixture"
    api_contract = "api_contract"


class ImpactStatus(str, Enum):
    synced = "synced"
    suspect_stale = "suspect_stale"
    broken = "broken"


class BindingContract(BaseModel):
    consumed_outputs: list[str] = Field(default_factory=list)
    bound_rules: list[str] = Field(default_factory=list)
    data_mappings: dict[str, str] = Field(default_factory=dict)


class StoryDependencyCreate(BaseModel):
    target_story_id: str = Field(min_length=1, max_length=36, description="ID của Story hạ nguồn")
    dependency_type: DependencyType = Field(default=DependencyType.precondition)
    binding_contract: BindingContract = Field(default_factory=BindingContract)


class StoryDependencyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    source_story_id: str
    target_story_id: str
    dependency_type: str
    synced_source_version: int
    target_story_version: int
    binding_contract: dict
    impact_status: str
    stale_reason: dict | None = None
    impacted_case_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class DependencyNode(BaseModel):
    id: str
    title: str
    version: int
    dependency_type: str
    impact_status: str
    synced_source_version: int | None = None
    current_source_version: int | None = None
    stale_reason: dict | None = None
    impacted_case_ids: list[str] = Field(default_factory=list)


class StoryDependencyTree(BaseModel):
    story_id: str
    story_title: str
    story_version: int
    upstream: list[DependencyNode] = Field(default_factory=list)
    downstream: list[DependencyNode] = Field(default_factory=list)


class ImpactedCaseDetail(BaseModel):
    case_id: str
    title: str
    reason: str


class ImpactReportItem(BaseModel):
    dependency_id: str
    source_story_id: str
    source_story_title: str
    target_story_id: str
    target_story_title: str
    synced_source_version: int
    current_source_version: int
    impact_status: str
    stale_reason: dict | None = None
    impacted_case_ids: list[str] = Field(default_factory=list)
    impacted_cases: list[ImpactedCaseDetail] = Field(default_factory=list)


class StoryImpactAnalysisReport(BaseModel):
    story_id: str
    story_title: str
    story_version: int
    has_impacted_dependencies: bool
    upstream_impacts: list[ImpactReportItem] = Field(default_factory=list)
    downstream_impacts: list[ImpactReportItem] = Field(default_factory=list)


class StoryWorkspace(StoryRead):
    reviews: list[RequirementReviewRead]
    test_case_sets: list[TestCaseSetRead]
    api_specifications: list[ApiSpecificationRead] = Field(default_factory=list)
    api_contract_reviews: list[ApiContractReviewRead] = Field(default_factory=list)
    upstream_dependencies: list[StoryDependencyRead] = Field(default_factory=list)
    downstream_dependencies: list[StoryDependencyRead] = Field(default_factory=list)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


