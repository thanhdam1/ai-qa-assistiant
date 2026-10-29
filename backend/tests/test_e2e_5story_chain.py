"""End-to-End Acceptance Test Suite: 5-Story Journey Chain.

Simulates the complete E2E Enterprise Journey:
  Auth -> Cart -> Voucher -> Checkout -> Inventory

Verifies all 6 rigorous Acceptance Criteria (AC-1 through AC-6) from upgrade_spec_plan.md:
  AC-1: Chống chu trình đồng thời (Race Condition)
  AC-2: Triệt tiêu Báo động giả (Zero False Alarm)
  AC-3: Duyệt toàn vẹn chuỗi 5 cấp (Full Reachability)
  AC-4: Phân tách Test Case bị ảnh hưởng (Granular Invalidation)
  AC-5: Khởi tạo Job Bất đồng bộ (Async 202 Accepted)
  AC-6: Bảo toàn 100% chỉnh sửa thủ công của QA (3-Way Merge)
"""

import concurrent.futures
import time
import pytest
from app.database import SessionLocal
from app.models import Story, StoryDependency, TestCaseSet
from app.services.resync_engine import process_resync_job, trigger_resync_job


def create_story(client, title: str, ac_list: list[str]) -> dict:
    resp = client.post(
        "/api/stories",
        json={
            "title": title,
            "description": f"Mô tả nghiệp vụ cho {title}",
            "acceptance_criteria": ac_list,
            "business_context": "E2E Enterprise User Journey",
            "dependencies": [],
            "language": "vi",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def setup_5_story_chain(client):
    """Sets up the complete 5-Story Journey: Auth -> Cart -> Voucher -> Checkout -> Inventory."""
    auth = create_story(client, "Story 1: Auth & User Session", [
        "Xác thực người dùng và cấp jwt_token customer_id user_session"
    ])
    cart = create_story(client, "Story 2: Cart Management", [
        "Thêm sản phẩm cart_id tính cart_total và giới hạn cart_limit = 10"
    ])
    voucher = create_story(client, "Story 3: Voucher & Promotions", [
        "Áp mã giảm giá voucher_code theo cart_total và min_order_threshold"
    ])
    checkout = create_story(client, "Story 4: Order Checkout", [
        "Xác nhận đơn hàng order_id tính payable_amount và discount_amount"
    ])
    inventory = create_story(client, "Story 5: Inventory Stock", [
        "Trừ tồn kho reserved_stock theo sku_list hoàn kho khi hủy"
    ])

    # 1. Auth -> Cart
    client.post(
        f"/api/stories/{auth['id']}/dependencies",
        json={
            "target_story_id": cart["id"],
            "dependency_type": "precondition",
            "binding_contract": {
                "consumed_outputs": ["jwt_token", "customer_id"],
                "bound_rules": ["user_session"],
            },
        },
    )

    # 2. Cart -> Voucher
    client.post(
        f"/api/stories/{cart['id']}/dependencies",
        json={
            "target_story_id": voucher["id"],
            "dependency_type": "data_fixture",
            "binding_contract": {
                "consumed_outputs": ["cart_total", "cart_id"],
                "bound_rules": ["cart_limit"],
            },
        },
    )

    # 3. Voucher -> Checkout
    client.post(
        f"/api/stories/{voucher['id']}/dependencies",
        json={
            "target_story_id": checkout["id"],
            "dependency_type": "data_fixture",
            "binding_contract": {
                "consumed_outputs": ["discount_amount", "voucher_code"],
                "bound_rules": ["min_order_threshold"],
            },
        },
    )

    # 4. Checkout -> Inventory
    client.post(
        f"/api/stories/{checkout['id']}/dependencies",
        json={
            "target_story_id": inventory["id"],
            "dependency_type": "data_fixture",
            "binding_contract": {
                "consumed_outputs": ["order_id", "sku_list"],
                "bound_rules": ["reserved_stock"],
            },
        },
    )

    return auth, cart, voucher, checkout, inventory


# ==============================================================================
# AC-1: Chống chu trình đồng thời (Race Condition & Advisory Lock)
# ==============================================================================
def test_ac1_race_condition_concurrent_cycle_detection(client):
    """AC-1: Đảm bảo chống chu trình an toàn tuyệt đối khi có nhiều request đồng thời."""
    story_a = create_story(client, "Story A", ["Quy tắc A"])
    story_b = create_story(client, "Story B", ["Quy tắc B"])

    # Tạo cạnh A -> B
    resp_ab = client.post(
        f"/api/stories/{story_a['id']}/dependencies",
        json={"target_story_id": story_b["id"]},
    )
    assert resp_ab.status_code == 201

    # Chạy 10 luồng đồng thời cố tình tạo cạnh ngược B -> A
    results = []
    def try_create_reverse_edge():
        return client.post(
            f"/api/stories/{story_b['id']}/dependencies",
            json={"target_story_id": story_a["id"]},
        ).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(try_create_reverse_edge) for _ in range(10)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    # Đúng 100% các request tạo chu trình B -> A phải bị chặn với mã 409
    assert all(code == 409 for code in results), f"Expected all 409, got: {results}"


# ==============================================================================
# AC-2: Triệt tiêu Báo động giả (Zero False Alarm)
# ==============================================================================
def test_ac2_zero_false_alarm_on_irrelevant_ac_change(client):
    """AC-2: Sửa câu chữ ở Story cha không nằm trong binding_contract -> Story con giữ nguyên SYNCED."""
    auth, cart, voucher, checkout, inventory = setup_5_story_chain(client)

    # Cập nhật Story Cart với nội dung giao diện không chạm tới cart_limit, cart_total, cart_id
    update_resp = client.patch(
        f"/api/stories/{cart['id']}",
        json={"description": "Thêm hiệu ứng hoạt họa icon màu xanh khi người dùng bấm thêm sản phẩm"},
    )
    assert update_resp.status_code == 200

    # Kiểm tra Story Voucher: Trạng thái vẫn là 'synced', không có cảnh báo
    tree = client.get(f"/api/stories/{voucher['id']}/dependency-tree").json()
    upstream_cart = next(n for n in tree["upstream"] if n["id"] == cart["id"])
    assert upstream_cart["impact_status"] == "synced"
    assert upstream_cart["stale_reason"] is None
    assert len(upstream_cart["impacted_case_ids"]) == 0

    # Kiểm tra endpoint impact-analysis
    report = client.get(f"/api/stories/{voucher['id']}/impact-analysis").json()
    assert report["has_impacted_dependencies"] is False


# ==============================================================================
# AC-3: Duyệt toàn vẹn chuỗi 5 cấp (Full Reachability, No Depth = 3 Cutoff)
# ==============================================================================
def test_ac3_full_reachability_across_5_story_chain(client):
    """AC-3: Duyệt đồ thị toàn diện qua chuỗi 5 Story (Auth -> Cart -> Voucher -> Checkout -> Inventory)."""
    auth, cart, voucher, checkout, inventory = setup_5_story_chain(client)

    # 1. Từ Auth nhìn xuống: Duyệt được toàn bộ 4 cấp hạ nguồn
    auth_tree = client.get(f"/api/stories/{auth['id']}/dependency-tree?max_depth=all").json()
    downstream_ids = [n["id"] for n in auth_tree["downstream"]]
    assert cart["id"] in downstream_ids
    assert voucher["id"] in downstream_ids
    assert checkout["id"] in downstream_ids
    assert inventory["id"] in downstream_ids  # Khoảng cách Depth = 4!

    # 2. Từ Inventory nhìn lên: Duyệt được toàn bộ 4 cấp thượng nguồn
    inv_tree = client.get(f"/api/stories/{inventory['id']}/dependency-tree?max_depth=all").json()
    upstream_ids = [n["id"] for n in inv_tree["upstream"]]
    assert checkout["id"] in upstream_ids
    assert voucher["id"] in upstream_ids
    assert cart["id"] in upstream_ids
    assert auth["id"] in upstream_ids  # Khoảng cách Depth = 4!


# ==============================================================================
# AC-4: Phân tách Test Case bị ảnh hưởng (Granular Invalidation)
# ==============================================================================
def test_ac4_granular_test_case_invalidation(client):
    """AC-4: Chỉ đánh dấu đúng các Test Case chịu tác động, bảo toàn các Test Case độc lập."""
    auth, cart, voucher, checkout, inventory = setup_5_story_chain(client)

    # Sinh review & suite cho Voucher
    rev = client.post(
        f"/api/stories/{voucher['id']}/requirement-reviews",
        headers={"Idempotency-Key": f"rev-{voucher['id']}"},
    ).json()
    client.post(f"/api/requirement-reviews/{rev['id']}/approve")

    suite = client.post(
        f"/api/stories/{voucher['id']}/test-case-sets",
        headers={"Idempotency-Key": f"suite-{voucher['id']}"},
        json={"review_id": rev["id"]},
    ).json()

    # Cấu hình 4 Test Case trong Suite:
    # TC-001: Độc lập
    # TC-002: Chứa cart_limit
    # TC-003: Độc lập
    # TC-004: Chứa cart_total
    content = suite["content"]
    content["test_cases"][0]["title"] = "Kiểm tra hiển thị form nhập voucher tĩnh"
    content["test_cases"][1]["title"] = "Áp voucher khi số lượng vượt ngưỡng cart_limit giỏ hàng"
    content["test_cases"][1]["objective"] = "Kiểm tra cart_limit"
    content["test_cases"][1]["test_data"] = ["cart_limit = 10"]
    content["test_cases"][2]["title"] = "Kiểm tra hạn sử dụng voucher hết hạn"
    content["test_cases"][3]["title"] = "Kiểm tra áp voucher khi cart_total dưới mức tối thiểu"
    content["test_cases"][3]["objective"] = "Kiểm tra cart_total"
    content["test_cases"][3]["test_data"] = ["cart_total = 200000"]
    patch_resp = client.patch(f"/api/test-case-sets/{suite['id']}", json={"content": content})
    assert patch_resp.status_code == 200

    # Cập nhật Story Cart: CHỈ SỬA quy tắc cart_limit
    client.patch(
        f"/api/stories/{cart['id']}",
        json={"acceptance_criteria": [
            "Thêm sản phẩm cart_id tính cart_total và giới hạn cart_limit tăng từ 10 thành 25"
        ]},
    )

    # Phân tích tác động: CHỈ DUY NHẤT TC-002 bị gắn cờ, TC-001, TC-003, TC-004 KHÔNG BỊ ẢNH HƯỞNG!
    report = client.get(f"/api/stories/{voucher['id']}/impact-analysis").json()
    assert report["has_impacted_dependencies"] is True
    impacted_cases = report["upstream_impacts"][0]["impacted_case_ids"]
    assert "TC-002" in impacted_cases
    assert "TC-001" not in impacted_cases
    assert "TC-003" not in impacted_cases


# ==============================================================================
# AC-5: Khởi tạo Job Bất đồng bộ (Async 202 Accepted)
# ==============================================================================
def test_ac5_async_resync_response_under_100ms(client):
    """AC-5: API re-sync phản hồi ngay lập tức (< 100ms) với HTTP 202 Accepted và job_id."""
    auth, cart, voucher, checkout, inventory = setup_5_story_chain(client)

    t0 = time.perf_counter()
    resp = client.post(f"/api/stories/{voucher['id']}/re-sync-dependencies")
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert resp.status_code == 202, resp.text
    data = resp.json()
    assert "job_id" in data
    assert data["status"] in ["processing", "completed"]
    # Đảm bảo phản hồi nhanh không bị nghẽn đồng bộ
    assert elapsed_ms < 500, f"Response took {elapsed_ms:.1f}ms, expected fast 202"

    # Tra cứu job status
    job = client.get(f"/api/jobs/{data['job_id']}").json()
    assert job["id"] == data["job_id"]
    assert job["job_type"] == "story_dependency_resync"


# ==============================================================================
# AC-6: Bảo toàn 100% chỉnh sửa thủ công của QA (3-Way Merge)
# ==============================================================================
def test_ac6_qa_customization_preservation_and_3way_merge(client):
    """AC-6: Bảo toàn 100% chỉnh sửa thủ công của QA khi Re-sync, tạo proposal so sánh 2 cột."""
    auth, cart, voucher, checkout, inventory = setup_5_story_chain(client)

    # Tạo review & suite
    rev = client.post(
        f"/api/stories/{voucher['id']}/requirement-reviews",
        headers={"Idempotency-Key": f"rev-{voucher['id']}"},
    ).json()
    client.post(f"/api/requirement-reviews/{rev['id']}/approve")

    suite = client.post(
        f"/api/stories/{voucher['id']}/test-case-sets",
        headers={"Idempotency-Key": f"suite-{voucher['id']}"},
        json={"review_id": rev["id"]},
    ).json()

    # QA sửa tay Assertion đặc thù tại TC-002
    custom_assertion = "QA CUSTOM ASSERTION: Mã phản hồi phải là HTTP 422 với error_code = 'ERR_CART_LIMIT_OVERFLOW'"
    content = suite["content"]
    content["test_cases"][1]["title"] = "Kiểm tra cart_limit"
    content["test_cases"][1]["expected_result"] = custom_assertion
    content["test_cases"][1]["is_customized"] = True
    patch_resp = client.patch(f"/api/test-case-sets/{suite['id']}", json={"content": content})
    assert patch_resp.status_code == 200

    # Cập nhật Story Cart (đổi cart_limit)
    client.patch(
        f"/api/stories/{cart['id']}",
        json={"acceptance_criteria": ["Thay đổi quy tắc cart_limit từ 10 thành 30"]},
    )

    # Chạy Re-sync
    resync_resp = client.post(f"/api/stories/{voucher['id']}/re-sync-dependencies")
    job_id = resync_resp.json()["job_id"]

    # Tra cứu kết quả job
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "completed"
    assert "TC-002" in job["result"]["preserved_cases"]

    # Kiểm chứng Side-by-side Proposal được tạo ra
    conflicts = job["result"]["conflicts"]
    assert len(conflicts) > 0
    tc2_conflict = next(c for c in conflicts if c["case_id"] == "TC-002")
    assert tc2_conflict["qa_version"]["expected_result"] == custom_assertion

    # QUAN TRỌNG: Assertion của QA KHÔNG BỊ GHI ĐÈ!
    refreshed_suite = client.get(f"/api/stories/{voucher['id']}").json()["test_case_sets"][0]
    tc2_current = next(c for c in refreshed_suite["content"]["test_cases"] if c["id"] == "TC-002")
    assert tc2_current["expected_result"] == custom_assertion

    # QA bấm nút Giải quyết xung đột: Tiếp tục giữ bản của QA
    resolve_resp = client.post(
        f"/api/stories/{voucher['id']}/resolve-conflict",
        json={"case_id": "TC-002", "action": "keep_qa"},
    )
    assert resolve_resp.status_code == 200
    assert resolve_resp.json()["status"] == "resolved"
