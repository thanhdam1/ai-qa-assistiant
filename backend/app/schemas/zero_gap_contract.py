from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ResolutionStatus(str, Enum):
    COVERED_AUTOMATED = "covered_automated"
    HEALED_BY_DELTA = "healed_by_delta"
    NEEDS_CLARIFICATION = "needs_clarification"
    ACCEPTED_RISK = "accepted_risk"
    DEFERRED = "deferred"


class AtomicRequirement(BaseModel):
    req_id: str = Field(..., description="ID nguyên tử, VD: REQ-001")
    clause_text: str = Field(..., description="Mệnh đề điều kiện đơn đã tách")
    source_ac: str = Field(..., description="Câu Acceptance Criteria gốc")


class BVAPartitionItem(BaseModel):
    bva_id: str = Field(..., description="ID phân vùng biên, VD: BVA-age-min_minus_1")
    endpoint: str
    field_path: str
    partition_type: str  # min_minus_1, min, nominal, max, max_plus_1, null, empty, wrong_type
    test_value: Any
    expected_http_status: int


class ASTBranchNode(BaseModel):
    branch_id: str = Field(..., description="ID nhánh code, VD: AST-create_order-B1")
    function_name: str
    condition_expression: str
    line_number: int


class CanonicalTestContract(BaseModel):
    mode: str = Field(default="2-way", description="2-way hoặc 3-way")
    requirements: List[AtomicRequirement] = Field(default_factory=list)
    bva_matrix: List[BVAPartitionItem] = Field(default_factory=list)
    ast_branches: List[ASTBranchNode] = Field(default_factory=list)
    cyclomatic_complexity: int = 1
    spec_conflicts: List[str] = Field(default_factory=list)


class TestCaseSkeleton(BaseModel):
    test_case_id: str
    title: str
    category: str = "Functional"  # Functional | Boundary | Negative | Security
    covered_req_ids: List[str] = Field(default_factory=list)
    covered_bva_ids: List[str] = Field(default_factory=list)
    covered_ast_ids: List[str] = Field(default_factory=list)


class DetailedTestCase(TestCaseSkeleton):
    priority: str = "High"
    preconditions: List[str] = Field(default_factory=list)
    test_steps: List[str] = Field(default_factory=list)
    test_data_payload: Dict[str, Any] = Field(default_factory=dict)
    expected_http_status: int = 200
    expected_result: str
    resolution_status: ResolutionStatus = ResolutionStatus.COVERED_AUTOMATED


class GapForQA(BaseModel):
    target_id: str
    gap_type: str  # REQ_GAP | BVA_GAP | AST_GAP | SPEC_CONFLICT
    reason: str
    status: ResolutionStatus = ResolutionStatus.NEEDS_CLARIFICATION


class ZeroGapSuiteResponse(BaseModel):
    effective_coverage_pct: float
    verification_mode: str
    retries_used: int
    test_cases: List[DetailedTestCase]
    gaps_for_qa: List[GapForQA]
