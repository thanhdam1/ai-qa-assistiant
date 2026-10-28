# KẾ HOẠCH NÂNG CẤP HỆ THỐNG AI-QA-ASSISTANT (v2.0)
**Mục tiêu:** Đạt chuẩn **100% Zero-Gap Test Generation** tích hợp trực tiếp vào kiến trúc Full-stack (`backend/app/` FastAPI + `frontend/src/` React) với cơ chế **Adaptive 2-Way/3-Way Verification** và **Circuit Breaker Human-in-the-Loop**.

---

## 1. PHẠM VI & ĐỊNH HƯỚNG KIẾN TRÚC (SCOPE v2.0)

Phiên bản v2.0 khắc phục triệt để độ lệch cấu trúc thư mục và rủi ro lặp vô tận bằng cách nhúng trực tiếp các thuật toán tất định (Deterministic Parsers) vào tầng Service/Engine của FastAPI và kết nối thẳng với giao diện `TestWorkbench.tsx` / `SuiteAssessment.tsx`.

### 1.1. Cấu trúc Thư mục Tích hợp (`backend/app/` & `frontend/src/`)
```text
ai-qa-assistiant/
├── backend/
│   └── app/
│       ├── api/routes/
│       │   └── zero_gap_suite.py     # Endpoint điều phối sinh Test Suite Zero-Gap
│       ├── schemas/
│       │   └── zero_gap_contract.py  # Pydantic v2 Models cho Canonical Contract & Coverage Gate
│       ├── parsers/                  # [TẦNG 1: THUẬT TOÁN TẤT ĐỊNH 100% PYTHON - KHÔNG DÙNG LLM]
│       │   ├── srs_decomposer.py     # Tách mệnh đề AND/OR/WHEN thành Atomic REQ_ID
│       │   ├── openapi_bva.py        # Sinh ma trận 8 phân vùng BVA từ OpenAPI (.yaml/.json)
│       │   └── code_ast_parser.py    # Tree-sitter CFG & Cyclomatic Complexity V(G) (Optional)
│       └── engine/                   # [TẦNG 2-4: MULTI-PHASE GENERATOR & COVERAGE GATE]
│           ├── gap_detector.py       # Adaptive 2-Way (Story ↔ OpenAPI) hoặc 3-Way (+ AST)
│           ├── batch_generator.py    # Sinh 2 pha: Skeleton Matrix -> Async Batch Expansion (<=8 TC)
│           └── coverage_gate.py      # Mathematical Gate + Circuit Breaker (Max 2 Retries)
├── frontend/
│   └── src/components/
│       ├── SourceCodeUploader.tsx    # Tùy chọn upload file code (.py, .ts, .java) bật 3-Way Mode
│       ├── TestWorkbench.tsx         # Hiển thị Test Suite + Danh sách điểm nghẽn `gaps_for_qa`
│       └── SuiteAssessment.tsx       # Cho phép QA gán `needs_clarification` / `accepted_risk` / `deferred`
└── skills/                           # Bộ Agent Skills phục vụ AI Coding Assistant trong IDE
```

---

## 2. BỘ 6 QUY TẮC BẮT BUỘC (ZERO-GAP STRICT RULES v2.0)

* **RULE-01 (Atomic Requirement Decomposition):** Mọi câu mô tả trong User Story/AC chứa liên từ điều kiện (`AND`, `OR`, `WHEN`, `IF`, `UNLESS`, `EXCEPT`) phải được tách thành các mệnh đề nguyên tử `REQ-<MODULE>-<NNN>` độc lập trước khi gọi LLM.
* **RULE-02 (Deterministic 8-Partition BVA):** Không để LLM tự suy diễn giá trị biên. Module `openapi_bva.py` tự động tính 8 phân vùng biên (`min - 1`, `min`, `nominal`, `max`, `max + 1`, `null`, `empty`, `wrong_type`) cho từng field trong OpenAPI schema.
* **RULE-03 (Adaptive 2-Way / 3-Way AST Mode):**
  * **Chế độ 2-Way (Mặc định):** Khi chỉ có User Story + OpenAPI, hệ thống kiểm chứng chéo giữa `Atomic REQ_ID` và `OpenAPI BVA Matrix`.
  * **Chế độ 3-Way (Khi có Source Code):** Kích hoạt `code_ast_parser.py` tính chỉ số **Cyclomatic Complexity $V(G)$** và ép số lượng kịch bản nhánh rẽ tối thiểu phải $\ge V(G)$.
* **RULE-04 (Pre-Generation Conflict & Shadow Logic Detection):** Mọi sự lệch pha giữa User Story và OpenAPI (ví dụ: Story quy định tối thiểu 8 ký tự nhưng OpenAPI ghi `minLength: 6`) hoặc nhánh `if/throw` ngầm trong AST đều phải được gắn cờ `SpecConflict` trước khi sinh Test Case.
* **RULE-05 (Two-Phase Async Batch Generation):**
  * **Pha 1 (Skeleton Matrix):** LLM chỉ sinh danh sách khung ID (`Test_Case_ID`, `Target_REQ_ID`, `Target_BVA_ID`, `Target_AST_Branch`).
  * **Pha 2 (Async Batch Expansion):** Chia danh sách Skeleton thành từng lô tối đa **8 Test Cases/batch** và gọi bất đồng bộ (`asyncio.gather`) để điền chi tiết Steps, Payload và Expected Result, triệt tiêu 100% lỗi cắt cụt Output Token.
* **RULE-06 (Mathematical Coverage Gate + Circuit Breaker):**
  * Áp dụng công thức độ phủ có tính đến quyết định của QA (Human-in-the-Loop):
    $$\text{Effective Coverage} = \frac{\vert{}\text{Covered}\vert{} + \vert{}\text{Flagged (}\texttt{needs\_clarification} \cup \texttt{accepted\_risk} \cup \texttt{deferred}\text{)}\vert{}}{\vert{}\text{Total Extracted Obligations}\vert{}} = 100\%$$
  * **Circuit Breaker:** Vòng lặp tự sinh bù (Delta Self-Healing) chỉ chạy tối đa **`MAX_RETRIES = 2`**. Nếu sau 2 lần retry vẫn còn mục chưa phủ được, hệ thống tự động ngắt vòng lặp, gắn trạng thái `needs_clarification` và đẩy vào mảng `gaps_for_qa` trả về giao diện React.

---

## 3. SƠ ĐỒ ĐỐI CHIẾU LUỒNG THỰC THI CŨ VS. MỚI

### 3.1. Luồng Cũ (Single-Pass Generation)
```text
[Story + OpenAPI] ──► [1 Prompt duy nhất gửi LLM] ──► [Trả thẳng ra UI (Dễ sót biên, cụt JSON khi >20 TC)]
```

### 3.2. Luồng Mới (Zero-Gap v2.0 Pipeline)
```text
[Story + OpenAPI + (Optional) AST Code]
       │
       ▼
[1. Deterministic Parsers] ──► Tách Atomic REQ + Tính 8 mốc BVA + Đếm nhánh AST V(G)
       │
       ▼
[2. Gap Detector (2-Way/3-Way)] ──► Bắt lỗi Spec mâu thuẫn & Shadow Logic
       │
       ▼
[3. Two-Phase Async Generator] ──► Pha 1: Lập khung Skeleton 100% ──► Pha 2: Chạy song song các lô <= 8 TC
       │
       ▼
[4. Coverage Gate + Circuit Breaker (Max 2 Retries)]
       ├─ Đạt 100% ──► Trả về Test Suite hoàn chỉnh
       └─ Sau 2 lần Retry vẫn < 100% ──► Đóng gói phần dư vào `gaps_for_qa` gửi lên `SuiteAssessment.tsx`
```

---

## 4. MÃ NGUỒN TỐI ƯU HÓA TÍCH HỢP VÀO `backend/app/`

Dưới đây là mã nguồn Python chuẩn hóa (sử dụng **Pydantic v2**, **Asyncio**, xử lý thuật toán O(N) gọn nhẹ) để đưa trực tiếp vào `backend/app/`.

### 4.1. Schema Hợp đồng Kiểm thử (`backend/app/schemas/zero_gap_contract.py`)
```python
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
    category: str  # Functional | Boundary | Negative | Security
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
```

---

### 4.2. Bộ Bóc tách Yêu cầu Nguyên tử & 8 Phân vùng BVA (`backend/app/parsers/openapi_bva.py`)
```python
import re
from typing import Any, Dict, List
from app.schemas.zero_gap_contract import AtomicRequirement, BVAPartitionItem

SPLIT_PATTERN = re.compile(
    r"\b(?:AND|OR|WHEN|IF|UNLESS|EXCEPT|NHƯNG|HOẶC|NẾU|KHI|TRỪ KHI)\b",
    flags=re.IGNORECASE,
)


def decompose_user_story(raw_story: str, module_prefix: str = "REQ") -> List[AtomicRequirement]:
    """Tách User Story/AC thành các mệnh đề nguyên tử độc lập (RULE-01)."""
    lines = [line.strip(" -•*\t") for line in raw_story.splitlines() if line.strip()]
    atomic_reqs: List[AtomicRequirement] = []
    counter = 1

    for line in lines:
        clauses = [c.strip() for c in SPLIT_PATTERN.split(line) if len(c.strip()) > 5]
        for clause in clauses:
            atomic_reqs.append(
                AtomicRequirement(
                    req_id=f"{module_prefix}-{counter:03d}",
                    clause_text=clause,
                    source_ac=line,
                )
            )
            counter += 1
    return atomic_reqs


def generate_8_partition_bva(openapi_spec: Dict[str, Any]) -> List[BVAPartitionItem]:
    """Sinh ma trận 8 phân vùng biên tất định từ OpenAPI Schema (RULE-02)."""
    bva_items: List[BVAPartitionItem] = []
    paths = openapi_spec.get("paths", {})

    for path, methods in paths.items():
        for method, details in methods.items():
            if method.lower() not in {"post", "put", "patch"}:
                continue
            endpoint_key = f"{method.upper()} {path}"
            schema = (
                details.get("requestBody", {})
                .get("content", {})
                .get("application/json", {})
                .get("schema", {})
            )
            properties = schema.get("properties", {})
            required_fields = set(schema.get("required", []))

            for field_name, rules in properties.items():
                ftype = rules.get("type", "string")
                partitions: Dict[str, tuple[Any, int]] = {}

                if ftype in {"integer", "number"}:
                    low = rules.get("minimum", 0)
                    high = rules.get("maximum", 1000)
                    mid = (low + high) // 2
                    partitions = {
                        "min_minus_1": (low - 1, 422),
                        "min": (low, 200),
                        "nominal": (mid, 200),
                        "max": (high, 200),
                        "max_plus_1": (high + 1, 422),
                        "null": (None, 422 if field_name in required_fields else 200),
                        "empty": ("", 422),
                        "wrong_type": ("INVALID_NUMBER_TYPE", 422),
                    }
                elif ftype == "string":
                    min_len = rules.get("minLength", 1)
                    max_len = rules.get("maxLength", 50)
                    mid_len = max(1, (min_len + max_len) // 2)
                    partitions = {
                        "min_minus_1": ("a" * max(0, min_len - 1), 422 if min_len > 0 else 200),
                        "min": ("a" * min_len, 200),
                        "nominal": ("a" * mid_len, 200),
                        "max": ("a" * max_len, 200),
                        "max_plus_1": ("a" * (max_len + 1), 422),
                        "null": (None, 422 if field_name in required_fields else 200),
                        "empty": ("", 422 if min_len > 0 or field_name in required_fields else 200),
                        "wrong_type": ({"unexpected": "object"}, 422),
                    }

                for p_type, (val, status_code) in partitions.items():
                    bva_items.append(
                        BVAPartitionItem(
                            bva_id=f"BVA-{field_name}-{p_type}",
                            endpoint=endpoint_key,
                            field_path=field_name,
                            partition_type=p_type,
                            test_value=val,
                            expected_http_status=status_code,
                        )
                    )
    return bva_items
```

---

### 4.3. Bộ Đếm Nhánh AST & Cyclomatic Complexity $V(G)$ (`backend/app/parsers/code_ast_parser.py`)
```python
import ast
from typing import List, Tuple
from app.schemas.zero_gap_contract import ASTBranchNode


def extract_python_ast_cfg(source_code: str) -> Tuple[List[ASTBranchNode], int]:
    """
    Trích xuất các nhánh điều khiển (if/for/while/except) và tính Cyclomatic Complexity V(G).
    Hỗ trợ mở rộng sang Tree-sitter cho TS/Java khi cần (RULE-03).
    """
    if not source_code or not source_code.strip():
        return [], 1

    tree = ast.parse(source_code)
    branches: List[ASTBranchNode] = []
    decision_points = 0

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name
            for child in ast.walk(node):
                if isinstance(child, ast.If):
                    decision_points += 1
                    cond_str = ast.unparse(child.test) if hasattr(ast, "unparse") else "if_condition"
                    branches.append(
                        ASTBranchNode(
                            branch_id=f"AST-{func_name}-L{child.lineno}",
                            function_name=func_name,
                            condition_expression=cond_str,
                            line_number=child.lineno,
                        )
                    )
                elif isinstance(child, ast.ExceptHandler):
                    decision_points += 1
                    exc_type = ast.unparse(child.type) if child.type and hasattr(ast, "unparse") else "Exception"
                    branches.append(
                        ASTBranchNode(
                            branch_id=f"AST-{func_name}-EXC-L{child.lineno}",
                            function_name=func_name,
                            condition_expression=f"except {exc_type}",
                            line_number=child.lineno,
                        )
                    )

    cyclomatic_complexity = decision_points + 1
    return branches, cyclomatic_complexity
```

---

### 4.4. Engine Sinh Test 2 Pha Bất Đồng Bộ & Coverage Gate có Circuit Breaker (`backend/app/engine/coverage_gate.py`)
```python
import asyncio
from typing import Callable, List, Set, Tuple
from app.schemas.zero_gap_contract import (
    CanonicalTestContract,
    DetailedTestCase,
    GapForQA,
    ResolutionStatus,
    TestCaseSkeleton,
    ZeroGapSuiteResponse,
)

BATCH_SIZE = 8
MAX_HEALING_RETRIES = 2


def evaluate_missing_obligations(
    contract: CanonicalTestContract,
    test_cases: List[DetailedTestCase],
    flagged_ids: Set[str],
) -> Tuple[Set[str], Set[str], Set[str], float]:
    """Tính toán chính xác các ID còn thiếu và tỷ lệ Effective Coverage (RULE-06)."""
    req_total = {r.req_id for r in contract.requirements}
    bva_total = {b.bva_id for b in contract.bva_matrix}
    ast_total = {a.branch_id for a in contract.ast_branches}

    req_cov = {rid for tc in test_cases for rid in tc.covered_req_ids} | (req_total & flagged_ids)
    bva_cov = {bid for tc in test_cases for bid in tc.covered_bva_ids} | (bva_total & flagged_ids)
    ast_cov = {aid for tc in test_cases for aid in tc.covered_ast_ids} | (ast_total & flagged_ids)

    missing_reqs = req_total - req_cov
    missing_bvas = bva_total - bva_cov
    missing_asts = ast_total - ast_cov

    total_count = len(req_total) + len(bva_total) + len(ast_total)
    if total_count == 0:
        return set(), set(), set(), 100.0

    covered_count = len(req_cov) + len(bva_cov) + len(ast_cov)
    coverage_pct = round((covered_count / total_count) * 100.0, 2)
    return missing_reqs, missing_bvas, missing_asts, coverage_pct


async def execute_zero_gap_pipeline(
    contract: CanonicalTestContract,
    llm_skeleton_fn: Callable[[CanonicalTestContract], asyncio.Future[List[TestCaseSkeleton]]],
    llm_expand_batch_fn: Callable[[List[TestCaseSkeleton], CanonicalTestContract], asyncio.Future[List[DetailedTestCase]]],
    llm_delta_heal_fn: Callable[[Set[str], Set[str], Set[str], CanonicalTestContract], asyncio.Future[List[DetailedTestCase]]],
    existing_flagged_ids: Set[str] | None = None,
) -> ZeroGapSuiteResponse:
    """
    Điều phối luồng Sinh Test 2 Pha + Kiểm chứng Toán học + Circuit Breaker (RULE-05 & RULE-06).
    """
    flagged_ids = existing_flagged_ids or set()

    # PHA 1: Sinh khung Skeleton Matrix (Không tốn token, đảm bảo đủ 100% số lượng)
    skeletons = await llm_skeleton_fn(contract)

    # PHA 2: Chia lô <= 8 Test Cases và chạy song song (Async Batch Expansion)
    batches = [skeletons[i : i + BATCH_SIZE] for i in range(0, len(skeletons), BATCH_SIZE)]
    batch_results = await asyncio.gather(
        *(llm_expand_batch_fn(batch, contract) for batch in batches)
    )
    detailed_cases: List[DetailedTestCase] = [tc for sublist in batch_results for tc in sublist]

    # PHA 3: Mathematical Coverage Gate + Vòng lặp Tự Chữa Lành (Tối đa 2 lần Retry)
    retries = 0
    missing_reqs, missing_bvas, missing_asts, cov_pct = evaluate_missing_obligations(
        contract, detailed_cases, flagged_ids
    )

    while (missing_reqs or missing_bvas or missing_asts) and retries < MAX_HEALING_RETRIES:
        retries += 1
        delta_cases = await llm_delta_heal_fn(missing_reqs, missing_bvas, missing_asts, contract)
        for tc in delta_cases:
            tc.resolution_status = ResolutionStatus.HEALED_BY_DELTA
        detailed_cases.extend(delta_cases)

        missing_reqs, missing_bvas, missing_asts, cov_pct = evaluate_missing_obligations(
            contract, detailed_cases, flagged_ids
        )

    # PHA 4: Circuit Breaker - Chuyển toàn bộ điểm nghẽn còn sót sang `gaps_for_qa` cho UI
    gaps_for_qa: List[GapForQA] = []

    for conflict in contract.spec_conflicts:
        gaps_for_qa.append(
            GapForQA(
                target_id="SPEC-CONFLICT",
                gap_type="SPEC_CONFLICT",
                reason=conflict,
                status=ResolutionStatus.NEEDS_CLARIFICATION,
            )
        )

    for rid in sorted(missing_reqs):
        gaps_for_qa.append(
            GapForQA(
                target_id=rid,
                gap_type="REQ_GAP",
                reason=f"Chưa thể tự động phủ yêu cầu {rid} sau {retries} vòng lặp Self-Healing. Cần QA làm rõ nghiệp vụ.",
            )
        )
        flagged_ids.add(rid)

    for bid in sorted(missing_bvas):
        gaps_for_qa.append(
            GapForQA(
                target_id=bid,
                gap_type="BVA_GAP",
                reason=f"Biên dữ liệu {bid} xung đột với ràng buộc nghiệp vụ hiện tại.",
            )
        )
        flagged_ids.add(bid)

    for aid in sorted(missing_asts):
        gaps_for_qa.append(
            GapForQA(
                target_id=aid,
                gap_type="AST_GAP",
                reason=f"Nhánh code {aid} (Shadow Logic) không có mô tả tương ứng trong User Story.",
            )
        )
        flagged_ids.add(aid)

    # Tính lại Effective Coverage sau khi đẩy các điểm nghẽn sang trạng thái Human-in-the-Loop
    _, _, _, final_effective_cov = evaluate_missing_obligations(
        contract, detailed_cases, flagged_ids
    )

    return ZeroGapSuiteResponse(
        effective_coverage_pct=final_effective_cov,
        verification_mode=contract.mode,
        retries_used=retries,
        test_cases=detailed_cases,
        gaps_for_qa=gaps_for_qa,
    )
```

---

## 5. LỘ TRÌNH TÍCH HỢP VÀO REPO HIỆN TẠI (ACTION CHECKLIST)

1. **Bước 1 (Backend Schemas & Parsers):** Copy `zero_gap_contract.py`, `openapi_bva.py`, và `code_ast_parser.py` vào `backend/app/schemas/` và `backend/app/parsers/`.
2. **Bước 2 (Backend Engine):** Tích hợp `coverage_gate.py` vào `backend/app/engine/` và nối các hàm callback `llm_skeleton_fn`, `llm_expand_batch_fn`, `llm_delta_heal_fn` với LLM Client hiện có của dự án.
3. **Bước 3 (Frontend Workbench):** Hiển thị mảng `gaps_for_qa` trả về từ API lên tab **Coverage & Bằng chứng** trong `TestWorkbench.tsx` và liên kết các nút hành động (`needs_clarification`, `accepted_risk`, `deferred`) trong `SuiteAssessment.tsx` với danh sách `existing_flagged_ids`.