import io
import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import APITimeoutError, RateLimitError

from app.config import Settings
from app.engine.coverage_gate import run_zero_gap_pipeline
from app.engine.gap_detector import detect_gaps_and_conflicts
from app.errors import AIProviderError
from app.parsers.code_ast_parser import extract_python_ast_cfg
from app.parsers.openapi_bva import generate_8_partition_bva
from app.parsers.srs_decomposer import decompose_user_story
from app.schemas import (
    ApiContractReviewContent,
    ApiOperationSummary,
    RequirementReviewContent,
)
from app.schemas.zero_gap_contract import (
    ASTBranchNode,
    AtomicRequirement,
    BVAPartitionItem,
    CanonicalTestContract,
)
from app.services.ai import OpenAIProvider
from app.services.export import zero_gap_suite_excel


def test_stream_1_story_review_edit_approve(client):
    """Luồng 1: Tạo Story -> AI Review -> QA Chỉnh sửa & Duyệt."""
    # 1. Tạo Story mới
    story_resp = client.post(
        "/api/stories",
        json={
            "title": "Thêm sản phẩm vào giỏ hàng",
            "description": "Là khách hàng, tôi muốn thêm sản phẩm vào giỏ để chuẩn bị thanh toán.",
            "acceptance_criteria": [
                "Sản phẩm còn hàng được thêm vào giỏ hàng thành công.",
            ],
            "business_context": "Thương mại điện tử",
            "dependencies": ["Inventory Service"],
            "language": "vi",
        },
    )
    assert story_resp.status_code == 201, story_resp.text
    story = story_resp.json()
    story_id = story["id"]
    assert story["version"] == 1

    # 2. Sinh AI Review với Idempotency-Key
    headers = {"Idempotency-Key": f"review-stream1-{story_id}"}
    review_resp = client.post(f"/api/stories/{story_id}/requirement-reviews", headers=headers)
    assert review_resp.status_code == 201, review_resp.text
    review = review_resp.json()
    review_id = review["id"]
    assert review["status"] == "draft"

    # Chặn sinh testcase khi review chưa duyệt
    blocked = client.post(
        f"/api/stories/{story_id}/test-case-sets",
        headers={"Idempotency-Key": f"test-stream1-{story_id}"},
        json={"review_id": review_id},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "review_not_approved"

    # 3. QA chỉnh sửa nội dung review
    new_content = review["content"]
    new_content["business_summary"] = "Người dùng thêm sản phẩm vào giỏ hàng có kiểm tra tồn kho."
    edit_resp = client.patch(
        f"/api/requirement-reviews/{review_id}",
        json={"content": new_content},
    )
    assert edit_resp.status_code == 200, edit_resp.text

    # 4. QA Phê duyệt review
    approve_resp = client.post(f"/api/requirement-reviews/{review_id}/approve")
    assert approve_resp.status_code == 200, approve_resp.text
    assert approve_resp.json()["status"] == "approved"
    assert approve_resp.json()["approved_at"] is not None


def test_stream_2_openapi_contract_review_approve(client):
    """Luồng 2: Upload OpenAPI -> Review Contract -> Duyệt."""
    # Tạo Story
    story_resp = client.post(
        "/api/stories",
        json={
            "title": "API Giỏ hàng",
            "description": "Quản lý giỏ hàng qua REST API",
            "acceptance_criteria": ["POST /cart/items thêm sản phẩm"],
            "business_context": "Cart API",
            "dependencies": [],
            "language": "vi",
        },
    )
    story_id = story_resp.json()["id"]

    # 1. Upload file đặc tả OpenAPI
    openapi_yaml = """
openapi: 3.0.3
info:
  title: Cart Service API
  version: 1.0.0
paths:
  /cart/items:
    post:
      operationId: addCartItem
      summary: Thêm sản phẩm vào giỏ hàng
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [product_id, quantity]
              properties:
                product_id:
                  type: string
                quantity:
                  type: integer
                  minimum: 1
                  maximum: 99
      responses:
        '200':
          description: Thêm thành công
        '400':
          description: Yêu cầu không hợp lệ
        '422':
          description: Lỗi dữ liệu
"""
    files = {"file": ("cart-openapi.yaml", openapi_yaml.encode("utf-8"), "application/x-yaml")}
    upload_resp = client.post(f"/api/stories/{story_id}/api-specifications", files=files)
    assert upload_resp.status_code == 201, upload_resp.text
    spec = upload_resp.json()
    spec_id = spec["id"]
    assert spec["stale"] is False
    assert len(spec["operations"]) >= 1

    # 2. Sinh AI Contract Review
    headers = {"Idempotency-Key": f"api-review-{spec_id}"}
    contract_review_resp = client.post(
        f"/api/api-specifications/{spec_id}/contract-reviews",
        headers=headers,
    )
    assert contract_review_resp.status_code == 201, contract_review_resp.text
    contract_review = contract_review_resp.json()
    contract_review_id = contract_review["id"]
    assert contract_review["status"] == "draft"

    # 3. QA Phê duyệt Contract Review
    approve_resp = client.post(f"/api/api-contract-reviews/{contract_review_id}/approve")
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "approved"


def test_stream_3_generate_tests_coverage_and_acceptance(client):
    """Luồng 3: Sinh testcase -> Kiểm tra Assertion và Coverage -> Bàn giao."""
    # Tạo story và approve review
    story = client.post(
        "/api/stories",
        json={
            "title": "Đăng ký thành viên",
            "description": "Khách hàng đăng ký tài khoản mới",
            "acceptance_criteria": ["Đăng ký thành công với email hợp lệ"],
            "business_context": "Auth",
            "dependencies": [],
            "language": "vi",
        },
    ).json()
    story_id = story["id"]

    review = client.post(
        f"/api/stories/{story_id}/requirement-reviews",
        headers={"Idempotency-Key": "test-stream3-rev"},
    ).json()
    client.post(f"/api/requirement-reviews/{review['id']}/approve")

    # 1. Sinh bộ Test Case
    suite_resp = client.post(
        f"/api/stories/{story_id}/test-case-sets",
        headers={"Idempotency-Key": "test-stream3-suite"},
        json={"review_id": review["id"]},
    )
    assert suite_resp.status_code == 201, suite_resp.text
    suite = suite_resp.json()
    suite_id = suite["id"]

    # 2. Kiểm tra đủ 4 phân nhóm
    case_types = {c["type"] for c in suite["content"]["test_cases"]}
    assert {"positive", "negative", "boundary", "integration"}.issubset(case_types)

    # 3. Phê duyệt nội dung kịch bản
    approve_content = client.post(f"/api/test-case-sets/{suite_id}/approve")
    assert approve_content.status_code == 200
    assert approve_content.json()["review_status"] == "approved"
    assert approve_content.json()["coverage_acceptance_status"] == "pending"

    # 4. Kiểm tra Gate: Không thể Accept Coverage khi chưa quyết định hết gap
    refused = client.post(
        f"/api/test-case-sets/{suite_id}/coverage-accept",
        json={"accepted_by": "QA Lead"},
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "coverage_decisions_incomplete"

    # 5. QA đưa ra Coverage Decisions cho toàn bộ các mục
    matrix = [m for m in suite["content"]["coverage_matrix"] if m["target_type"] != "category"]
    for item in matrix:
        decision = client.put(
            f"/api/test-case-sets/{suite_id}/coverage-decisions",
            json={
                "target_type": item["target_type"],
                "target_id": item["target_id"],
                "disposition": "blocked",
                "decided_by": "QA Lead",
                "reason": "Chờ xác nhận từ Business Analyst",
            },
        )
        assert decision.status_code == 200, decision.text

    # 6. Chấp thuận độ phủ (Accept Coverage) thành công
    accepted = client.post(
        f"/api/test-case-sets/{suite_id}/coverage-accept",
        json={"accepted_by": "QA Lead"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["coverage_acceptance_status"] == "accepted"


def test_stream_4_stale_detection_on_story_update(client):
    """Luồng 4: Sửa story/spec -> Xác nhận kết quả phụ thuộc bị đánh dấu stale."""
    # Tạo story và approve review
    story = client.post(
        "/api/stories",
        json={
            "title": "Thanh toán",
            "description": "Mô tả gốc v1",
            "acceptance_criteria": ["Thanh toán qua thẻ"],
            "business_context": "Payment",
            "dependencies": [],
            "language": "vi",
        },
    ).json()
    story_id = story["id"]

    review = client.post(
        f"/api/stories/{story_id}/requirement-reviews",
        headers={"Idempotency-Key": "stale-rev-1"},
    ).json()
    client.post(f"/api/requirement-reviews/{review['id']}/approve")

    suite = client.post(
        f"/api/stories/{story_id}/test-case-sets",
        headers={"Idempotency-Key": "stale-suite-1"},
        json={"review_id": review["id"]},
    ).json()

    # 1. Sửa Story -> Story version tăng lên 2
    update_resp = client.patch(
        f"/api/stories/{story_id}",
        json={"description": "Mô tả mới v2 đã cập nhật thêm quy tắc chiết khấu."},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["version"] == 2

    # 2. Kiểm tra các artifact cũ bị đánh dấu STALE
    workspace = client.get(f"/api/stories/{story_id}").json()
    assert workspace["reviews"][0]["stale"] is True
    assert workspace["test_case_sets"][0]["stale"] is True

    # 3. Chặn hành động duyệt trên artifact STALE
    blocked_approve = client.post(f"/api/test-case-sets/{suite['id']}/approve")
    assert blocked_approve.status_code == 409
    assert blocked_approve.json()["error"]["code"] == "stale_version"

    # Chặn sinh testcase từ review STALE
    blocked_gen = client.post(
        f"/api/stories/{story_id}/test-case-sets",
        headers={"Idempotency-Key": "stale-suite-2"},
        json={"review_id": review["id"]},
    )
    assert blocked_gen.status_code == 409
    assert blocked_gen.json()["error"]["code"] == "stale_version"


@pytest.mark.asyncio
async def test_stream_5_ai_provider_error_quota_and_timeout():
    """Luồng 5: Kiểm tra lỗi provider, hết quota và request bị timeout."""
    def test_settings(**kwargs):
        defaults = {
            "database_url": "sqlite+pysqlite://",
            "openai_api_key": "test-key",
            "openai_model": "gpt-4o",
            "ai_max_retries": 2,
        }
        return Settings(_env_file=None, **(defaults | kwargs))

    # 1. Thiếu API Key -> Báo lỗi ngay trước khi gọi mạng
    provider_no_key = OpenAIProvider(test_settings(openai_api_key=""))
    with pytest.raises(AIProviderError) as no_key_err:
        await provider_no_key._parse([], RequirementReviewContent)
    assert "not configured" in str(no_key_err.value)

    # 2. Timeout -> Đánh dấu retryable = True
    provider_timeout = OpenAIProvider(test_settings())
    async def fake_timeout(**_kwargs):
        raise APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))

    provider_timeout.client.responses.parse = fake_timeout
    with pytest.raises(AIProviderError) as timeout_err:
        await provider_timeout._parse([], RequirementReviewContent)
    assert timeout_err.value.details.get("retryable") is True

    # 3. Hết Quota (429 Insufficient Quota) -> Đánh dấu retryable = False (không lãng phí retry vô ích)
    provider_quota = OpenAIProvider(test_settings())
    async def fake_quota(**_kwargs):
        resp = httpx.Response(
            429,
            request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
            json={"error": {"message": "You exceeded your current quota.", "type": "insufficient_quota", "code": "credit_balance_exhausted"}},
        )
        raise RateLimitError("Insufficient quota", response=resp, body=resp.json())

    provider_quota.client.responses.parse = fake_quota
    with pytest.raises(AIProviderError) as quota_err:
        await provider_quota._parse([], RequirementReviewContent)
    assert quota_err.value.details.get("retryable") is False


def test_stream_6_zero_gap_benchmark_scoring_and_export():
    """Luồng 6: Chấm testcase bằng bộ tình huống chuẩn để đo phần thiếu và kỳ vọng sai."""
    # 1. Phân tách SRS Atomic Requirements
    story_text = """
    Khi khách hàng thêm sản phẩm có số lượng hợp lệ (1 <= quantity <= 10) VÀ tồn kho đủ THÌ thêm thành công.
    NẾU số lượng vượt quá tồn kho THÌ báo lỗi OUT_OF_STOCK (422).
    """
    atomic_reqs = decompose_user_story(story_text, module_prefix="REQ-CART")
    assert len(atomic_reqs) >= 2
    assert all(r.req_id.startswith("REQ-CART-") for r in atomic_reqs)

    # 2. Sinh 8 phân vùng BVA cho trường quantity
    openapi_spec = {
        "paths": {
            "/api/cart/items": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["quantity"],
                                    "properties": {
                                        "quantity": {"type": "integer", "minimum": 1, "maximum": 10},
                                    },
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    bvas = generate_8_partition_bva(openapi_spec)
    assert len(bvas) >= 8
    partition_types = {b.partition_type for b in bvas}
    assert {"min", "min_minus_1", "max", "max_plus_1", "nominal", "null", "wrong_type"}.issubset(partition_types)

    # 3. Phân tích AST CFG của mã nguồn thực tế
    source_code = """
def add_to_cart(product_id: str, quantity: int, stock: int, is_vip: bool):
    if quantity <= 0:
        raise ValueError("Invalid quantity")
    if quantity > stock:
        return {"status": 422, "code": "OUT_OF_STOCK"}
    if is_vip:
        discount = 0.1
    else:
        discount = 0.0
    return {"status": 200, "discount": discount}
"""
    branches, complexity = extract_python_ast_cfg(source_code)
    assert complexity >= 3
    assert len(branches) >= 3

    # 4. Kiểm toán phát hiện phần thiếu (Shadow Logic / Gaps) và kỳ vọng sai (Spec Conflicts)
    shadow_branches = [
        ASTBranchNode(
            branch_id="AST-B-VIP",
            function_name="add_to_cart",
            condition_expression="is_vip == True and user_balance_exceeded",
            line_number=8,
        )
    ]
    detected_gaps = detect_gaps_and_conflicts(atomic_reqs, bvas, shadow_branches)
    assert len(detected_gaps) >= 1
    assert any("Shadow Logic" in g for g in detected_gaps)

    # 5. Chạy Zero-Gap Pipeline: Vòng lặp đền bù đạt 100% độ phủ thực tế
    contract = CanonicalTestContract(
        mode="3-way",
        requirements=atomic_reqs,
        bva_matrix=bvas,
        ast_branches=branches,
        cyclomatic_complexity=complexity,
    )
    suite_response = run_zero_gap_pipeline(contract)
    assert suite_response.effective_coverage_pct == 100.0
    assert len(suite_response.test_cases) >= 8

    # 6. Xuất file Excel chuẩn ISO 29119-3 và kiểm tra định dạng
    excel_bytes = zero_gap_suite_excel(suite_response, "cart-story-001")
    assert isinstance(excel_bytes, bytes)
    # Header của file zip/xlsx luôn bắt đầu bằng 'PK\x03\x04'
    assert excel_bytes.startswith(b"PK\x03\x04")
    assert len(excel_bytes) > 5000  # Đầy đủ 3 sheet và style
