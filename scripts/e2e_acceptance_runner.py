"""
Bộ kịch bản chạy nghiệm thu tự động toàn bộ 6 Luồng Nghiệp Vụ Cốt Lõi (E2E Verification Matrix)
Chạy trực tiếp bằng lệnh: python scripts/e2e_acceptance_runner.py
"""
import io
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Đảm bảo đường dẫn import backend/app
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

os.environ["DATABASE_URL"] = "sqlite+pysqlite://"
os.environ["OPENAI_API_KEY"] = "test-key"

from fastapi.testclient import TestClient
from app.database import Base, engine, get_db, SessionLocal
from app.main import app
from app.services.ai import get_ai_provider
from app.schemas import (
    RequirementReviewContent,
    ExistingCriterion,
    RequirementObligation,
    ReviewItem,
    TestCaseSetContent,
    TestCase,
    TestStep,
    ApiContractReviewContent,
    ApiOperationSummary,
)
from app.schemas.zero_gap_contract import (
    AtomicRequirement,
    BVAPartitionItem,
    ASTBranchNode,
    CanonicalTestContract,
)
from app.engine.coverage_gate import run_zero_gap_pipeline
from app.engine.gap_detector import detect_gaps_and_conflicts
from app.parsers.openapi_bva import generate_8_partition_bva
from app.parsers.srs_decomposer import decompose_user_story
from app.parsers.code_ast_parser import extract_python_ast_cfg
from app.services.export import zero_gap_suite_excel
from app.config import Settings
from app.services.ai import OpenAIProvider
from app.errors import AIProviderError
import httpx
from openai import APITimeoutError, RateLimitError
import asyncio

GREEN = "\033[92m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"
CYAN = "\033[96m"


class AcceptanceAI:
    model_name = "test-ai-model"

    async def review_requirements(self, story):
        return RequirementReviewContent(
            language="vi",
            business_summary=f"Tóm tắt nghiệp vụ cho {story.title}",
            existing_acceptance_criteria=[
                ExistingCriterion(
                    id="AC-001",
                    criterion="Sản phẩm còn hàng được thêm thành công",
                    source_reference="AC 1",
                    obligations=[
                        RequirementObligation(id="OBL-001", text="Kiểm tra tồn kho")
                    ]
                )
            ],
            missing_acceptance_criteria=[],
            ambiguities_and_conflicts=[],
            stakeholder_questions=[],
            edge_cases=[],
            assumptions=[],
            risks=[],
        )

    async def review_api_contract(self, story, specification):
        ops = [
            ApiOperationSummary(
                operation_id=op["operation_id"],
                method=op["method"],
                path=op["path"],
                summary=op.get("summary", ""),
            )
            for op in specification.operations
        ]
        return ApiContractReviewContent(
            language="vi",
            summary="API contract review đạt chuẩn",
            operations=ops,
            findings=[],
        )

    async def generate_test_cases(self, story, review, api_review=None, specification=None):
        cases = []
        for idx, kind in enumerate(("positive", "negative", "boundary", "integration"), 1):
            cases.append(
                TestCase(
                    id=f"TC-{idx:03}",
                    title=f"Kịch bản kiểm thử {kind}",
                    objective=f"Xác minh luồng {kind}",
                    type=kind,
                    priority="high",
                    preconditions=["Điều kiện ban đầu thỏa mãn"],
                    test_data=["product_id: PRD-01", "quantity: 2"],
                    steps=[TestStep(order=1, action="Gửi request thêm giỏ", expected_result="Ghi nhận thành công")],
                    expected_result="Hệ thống phản hồi thành công và cập nhật giỏ hàng",
                    requirement_traceability=["AC-001"],
                    assumptions=[],
                    needs_clarification=False,
                )
            )
        return TestCaseSetContent(
            language="vi",
            coverage_summary="Bao phủ 4 phân loại test chuẩn",
            test_cases=cases,
        )


def setup_client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    def db_override():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_ai_provider] = lambda: AcceptanceAI()
    return TestClient(app)


def run_acceptance_suite():
    print(f"\n{BOLD}{CYAN}================================================================================")
    print("       AI QA ASSISTANT - BỘ KIỂM THỬ NGHIỆM THU 6 LUỒNG CỐT LÕI (E2E)")
    print(f"================================================================================{RESET}\n")

    client = setup_client()
    passed_count = 0

    # --------------------------------------------------------------------------
    # LUỒNG 1: Tạo Story -> AI Review -> QA Chỉnh sửa & Duyệt
    # --------------------------------------------------------------------------
    try:
        story = client.post("/api/stories", json={
            "title": "Thêm sản phẩm vào giỏ hàng",
            "description": "Là khách hàng, tôi muốn thêm sản phẩm vào giỏ để thanh toán.",
            "acceptance_criteria": ["Sản phẩm còn hàng được thêm thành công."],
            "business_context": "E-Commerce",
            "dependencies": ["Inventory"],
            "language": "vi",
        }).json()
        story_id = story["id"]

        review = client.post(f"/api/stories/{story_id}/requirement-reviews", headers={"Idempotency-Key": f"rev-{story_id}"}).json()
        assert review["status"] == "draft"

        # Chặn sinh test khi review chưa duyệt
        blocked = client.post(f"/api/stories/{story_id}/test-case-sets", headers={"Idempotency-Key": f"ts-{story_id}"}, json={"review_id": review["id"]})
        assert blocked.status_code == 409

        # Sửa review & Phê duyệt
        review_content = review["content"]
        review_content["business_summary"] = "Tóm tắt đã được QA hiệu đính."
        client.patch(f"/api/requirement-reviews/{review['id']}", json={"content": review_content})
        approved = client.post(f"/api/requirement-reviews/{review['id']}/approve")
        assert approved.status_code == 200 and approved.json()["status"] == "approved"

        print(f"[{GREEN}✔ PASS{RESET}] {BOLD}Luồng 1:{RESET} Tạo Story ➔ AI Review ➔ QA Chỉnh sửa ➔ Phê duyệt Review")
        passed_count += 1
    except Exception as exc:
        print(f"[{RED}✘ FAIL{RESET}] {BOLD}Luồng 1:{RESET} {exc}")

    # --------------------------------------------------------------------------
    # LUỒNG 2: Upload OpenAPI -> Review Contract -> Duyệt
    # --------------------------------------------------------------------------
    try:
        openapi_yaml = """
openapi: 3.0.3
info:
  title: Cart API
  version: 1.0.0
paths:
  /cart/items:
    post:
      operationId: addCartItem
      summary: Thêm giỏ hàng
      responses:
        '200':
          description: OK
"""
        files = {"file": ("cart.yaml", openapi_yaml.encode("utf-8"), "application/x-yaml")}
        spec = client.post(f"/api/stories/{story_id}/api-specifications", files=files).json()
        spec_id = spec["id"]

        contract_review = client.post(f"/api/api-specifications/{spec_id}/contract-reviews", headers={"Idempotency-Key": f"cr-{spec_id}"}).json()
        approved_cr = client.post(f"/api/api-contract-reviews/{contract_review['id']}/approve")
        assert approved_cr.status_code == 200 and approved_cr.json()["status"] == "approved"

        print(f"[{GREEN}✔ PASS{RESET}] {BOLD}Luồng 2:{RESET} Upload OpenAPI Spec ➔ Kiểm toán Hợp đồng API ➔ Duyệt Contract")
        passed_count += 1
    except Exception as exc:
        print(f"[{RED}✘ FAIL{RESET}] {BOLD}Luồng 2:{RESET} {exc}")

    # --------------------------------------------------------------------------
    # LUỒNG 3: Sinh Testcase -> Kiểm tra Assertion và Coverage -> Bàn giao
    # --------------------------------------------------------------------------
    try:
        suite = client.post(
            f"/api/stories/{story_id}/test-case-sets",
            headers={"Idempotency-Key": f"suite-{story_id}"},
            json={
                "review_id": review["id"],
                "api_contract_review_id": contract_review["id"],
            },
        ).json()
        suite_id = suite["id"]

        # Kiểm tra đủ 4 loại
        case_types = {c["type"] for c in suite["content"]["test_cases"]}
        assert {"positive", "negative", "boundary", "integration"}.issubset(case_types)

        # Duyệt kịch bản
        client.post(f"/api/test-case-sets/{suite_id}/approve")

        # Đưa ra Coverage Decisions và Accept Coverage
        matrix = [m for m in suite["content"]["coverage_matrix"] if m["target_type"] != "category"]
        for item in matrix:
            client.put(f"/api/test-case-sets/{suite_id}/coverage-decisions", json={
                "target_type": item["target_type"],
                "target_id": item["target_id"],
                "disposition": "blocked",
                "decided_by": "QA Lead",
                "reason": "Chờ xác nhận logic bổ sung",
            })
        accepted = client.post(f"/api/test-case-sets/{suite_id}/coverage-accept", json={"accepted_by": "QA Lead"})
        assert accepted.status_code == 200 and accepted.json()["coverage_acceptance_status"] == "accepted"

        print(f"[{GREEN}✔ PASS{RESET}] {BOLD}Luồng 3:{RESET} Sinh Testcase ➔ Kiểm tra 4 Loại ➔ Assertion Evidence ➔ Chấp thuận Độ phủ")
        passed_count += 1
    except Exception as exc:
        print(f"[{RED}✘ FAIL{RESET}] {BOLD}Luồng 3:{RESET} {exc}")

    # --------------------------------------------------------------------------
    # LUỒNG 4: Sửa Story/Spec -> Xác nhận kết quả phụ thuộc bị đánh dấu Stale
    # --------------------------------------------------------------------------
    try:
        update_resp = client.patch(f"/api/stories/{story_id}", json={"description": "Mô tả mới v2 đã cập nhật thêm quy tắc chiết khấu."}).json()
        assert update_resp["version"] == 2

        workspace = client.get(f"/api/stories/{story_id}").json()
        assert workspace["reviews"][0]["stale"] is True
        assert workspace["test_case_sets"][0]["stale"] is True
        assert workspace["api_contract_reviews"][0]["stale"] is True

        # Chặn duyệt trên bản stale
        blocked_approve = client.post(f"/api/test-case-sets/{suite_id}/approve")
        assert blocked_approve.status_code == 409 and blocked_approve.json()["error"]["code"] == "stale_version"

        print(f"[{GREEN}✔ PASS{RESET}] {BOLD}Luồng 4:{RESET} Sửa Story v1➔v2 ➔ Tự động gắn cờ STALE ➔ Chặn thao tác lỗi thời (409)")
        passed_count += 1
    except Exception as exc:
        print(f"[{RED}✘ FAIL{RESET}] {BOLD}Luồng 4:{RESET} {exc}")

    # --------------------------------------------------------------------------
    # LUỒNG 5: Kiểm tra Lỗi Provider, Hết Quota (429) và Request Timeout
    # --------------------------------------------------------------------------
    async def test_provider_resilience():
        cfg = Settings(_env_file=None, database_url="sqlite+pysqlite://", openai_api_key="test-key", openai_model="gpt-4o", ai_max_retries=2)

        # 1. Thiếu key
        p_no_key = OpenAIProvider(Settings(_env_file=None, database_url="sqlite+pysqlite://", openai_api_key=""))
        try:
            await p_no_key._parse([], RequirementReviewContent)
            assert False, "Should raise AIProviderError"
        except AIProviderError as err:
            assert "not configured" in str(err)

        # 2. Timeout (retryable)
        p_timeout = OpenAIProvider(cfg)
        async def fake_to(**_): raise APITimeoutError(request=httpx.Request("POST", "http://ai"))
        p_timeout.client.responses.parse = fake_to
        try:
            await p_timeout._parse([], RequirementReviewContent)
            assert False, "Should raise AIProviderError"
        except AIProviderError as err:
            assert err.details.get("retryable") is True

        # 3. Quota exhausted (not retryable)
        p_quota = OpenAIProvider(cfg)
        async def fake_q(**_):
            resp = httpx.Response(429, request=httpx.Request("POST", "http://ai"), json={"error": {"code": "credit_balance_exhausted"}})
            raise RateLimitError("No quota", response=resp, body=resp.json())
        p_quota.client.responses.parse = fake_q
        try:
            await p_quota._parse([], RequirementReviewContent)
            assert False, "Should raise AIProviderError"
        except AIProviderError as err:
            assert err.details.get("retryable") is False

    try:
        asyncio.run(test_provider_resilience())
        print(f"[{GREEN}✔ PASS{RESET}] {BOLD}Luồng 5:{RESET} Bắt lỗi Provider: Thiếu Key ➔ Timeout (Retryable) ➔ Hết Quota (Non-retryable)")
        passed_count += 1
    except Exception as exc:
        print(f"[{RED}✘ FAIL{RESET}] {BOLD}Luồng 5:{RESET} {exc}")

    # --------------------------------------------------------------------------
    # LUỒNG 6: Chấm Testcase bằng Zero-Gap Benchmark & Xuất Excel ISO
    # --------------------------------------------------------------------------
    try:
        reqs = decompose_user_story("Khi thêm sản phẩm hợp lệ THÌ thành công. NẾU hết hàng THÌ báo lỗi 422.", "REQ-CART")
        spec_dict = {"paths": {"/cart": {"post": {"requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"qty": {"type": "integer", "minimum": 1, "maximum": 10}}}}}}}}}}
        bvas = generate_8_partition_bva(spec_dict)
        branches, complexity = extract_python_ast_cfg("def add(qty, stock):\n    if qty <= 0: raise ValueError()\n    if qty > stock: return 422\n    return 200\n")

        # Phát hiện Shadow logic & conflicts
        shadow = [ASTBranchNode(branch_id="B-SHADOW", function_name="add", condition_expression="hidden_vip_discount == True", line_number=4)]
        gaps = detect_gaps_and_conflicts(reqs, bvas, shadow)
        assert any("Shadow Logic" in g for g in gaps)

        # Chạy Zero-Gap Canonical Pipeline
        contract = CanonicalTestContract(mode="3-way", requirements=reqs, bva_matrix=bvas, ast_branches=branches, cyclomatic_complexity=complexity)
        res = run_zero_gap_pipeline(contract)
        assert res.effective_coverage_pct == 100.0

        # Xuất file Excel ISO 29119-3
        excel_bytes = zero_gap_suite_excel(res, "Cart Module")
        assert excel_bytes.startswith(b"PK\x03\x04") and len(excel_bytes) > 5000

        print(f"[{GREEN}✔ PASS{RESET}] {BOLD}Luồng 6:{RESET} Zero-Gap Benchmark ➔ Bắt Shadow Logic ➔ Độ phủ 100% ➔ Xuất Excel ISO 29119-3")
        passed_count += 1
    except Exception as exc:
        print(f"[{RED}✘ FAIL{RESET}] {BOLD}Luồng 6:{RESET} {exc}")

    # --------------------------------------------------------------------------
    # TỔNG KẾT
    # --------------------------------------------------------------------------
    print(f"\n{BOLD}{CYAN}--------------------------------------------------------------------------------{RESET}")
    if passed_count == 6:
        print(f"{BOLD}{GREEN}✔ TẤT CẢ 6/6 LUỒNG NGHIỆP VỤ ĐẠT CHUẨN XUẤT SẮC 100%! HỆ THỐNG SẴN SÀNG TRIỂN KHAI.{RESET}")
    else:
        print(f"{BOLD}{RED}✘ CÓ {6 - passed_count} LUỒNG CHƯA ĐẠT CHUẨN. VUI LÒNG KIỂM TRA LẠI.{RESET}")
    print(f"{BOLD}{CYAN}================================================================================{RESET}\n")


if __name__ == "__main__":
    run_acceptance_suite()
