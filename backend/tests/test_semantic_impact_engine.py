import pytest
from app.database import Base, engine


def create_story_with_ac(client, title: str, ac_list: list[str]) -> dict:
    resp = client.post(
        "/api/stories",
        json={
            "title": title,
            "description": f"Mô tả cho {title}",
            "acceptance_criteria": ac_list,
            "business_context": "E2E Testing",
            "dependencies": [],
            "language": "vi",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_zero_false_alarm_when_delta_does_not_touch_contract(client):
    """AC-2: Triệt tiêu báo động giả khi thay đổi ở Story cha không liên quan tới hợp đồng ràng buộc."""
    cart = create_story_with_ac(client, "Cart Story", ["Số lượng sản phẩm từ 1 đến 10", "Tổng tiền hợp lệ"])
    voucher = create_story_with_ac(client, "Voucher Story", ["Áp dụng mã giảm giá theo ngưỡng tối thiểu"])

    # Tạo liên kết có ràng buộc cụ thể
    dep_resp = client.post(
        f"/api/stories/{cart['id']}/dependencies",
        json={
            "target_story_id": voucher["id"],
            "dependency_type": "data_fixture",
            "binding_contract": {
                "consumed_outputs": ["total_amount", "cart_id"],
                "bound_rules": ["min_order_threshold"],
            },
        },
    )
    assert dep_resp.status_code == 201
    dep_id = dep_resp.json()["id"]

    # Cập nhật Story Cart với nội dung HOÀN TOÀN KHÔNG LIÊN QUAN tới hợp đồng
    update_resp = client.patch(
        f"/api/stories/{cart['id']}",
        json={"description": "Thêm hiệu ứng hoạt họa hiển thị icon giỏ hàng màu xanh"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["version"] == 2

    # Kiểm tra trạng thái liên kết: Vẫn giữ 'synced', KHÔNG bị gắn cờ suspect_stale!
    tree = client.get(f"/api/stories/{cart['id']}/dependency-tree").json()
    downstream_node = tree["downstream"][0]
    assert downstream_node["impact_status"] == "synced"
    assert downstream_node["impacted_case_ids"] == []

    # API Impact Analysis cũng xác nhận không có tác động
    impact_report = client.get(f"/api/stories/{voucher['id']}/impact-analysis").json()
    assert impact_report["has_impacted_dependencies"] is False


def test_semantic_impact_triggered_when_contract_intersected(client):
    """Kiểm tra kích hoạt suspect_stale khi thay đổi ở Story cha va chạm vào binding contract."""
    cart = create_story_with_ac(client, "Cart Story", ["Số lượng từ 1 đến 10", "Giá trị đơn hàng"])
    voucher = create_story_with_ac(client, "Voucher Story", ["Áp dụng mã giảm"])

    client.post(
        f"/api/stories/{cart['id']}/dependencies",
        json={
            "target_story_id": voucher["id"],
            "dependency_type": "data_fixture",
            "binding_contract": {
                "consumed_outputs": ["total_amount"],
                "bound_rules": ["min_order_threshold"],
            },
        },
    )

    # Cập nhật Story Cart chạm đúng vào quy tắc min_order_threshold và total_amount
    update_resp = client.patch(
        f"/api/stories/{cart['id']}",
        json={
            "acceptance_criteria": [
                "Số lượng từ 1 đến 10",
                "Đơn hàng phải đạt total_amount thỏa mãn min_order_threshold tối thiểu 1.000.000 VND",
            ]
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["version"] == 2

    # Trạng thái chuyển sang 'suspect_stale'
    tree = client.get(f"/api/stories/{cart['id']}/dependency-tree").json()
    downstream_node = tree["downstream"][0]
    assert downstream_node["impact_status"] == "suspect_stale"
    assert downstream_node["stale_reason"] is not None
    assert "total_amount" in str(downstream_node["stale_reason"]) or "min_order_threshold" in str(downstream_node["stale_reason"])


def test_granular_test_case_invalidation(client):
    """AC-4: Khoanh vùng chính xác các Test Case bị ảnh hưởng, không đánh đồng toàn bộ test case."""
    cart = create_story_with_ac(client, "Cart Granular", ["Quản lý giỏ hàng"])
    voucher = create_story_with_ac(client, "Voucher Granular", ["Kiểm tra mã giảm giá"])

    # Liên kết ràng buộc
    client.post(
        f"/api/stories/{cart['id']}/dependencies",
        json={
            "target_story_id": voucher["id"],
            "dependency_type": "data_fixture",
            "binding_contract": {
                "consumed_outputs": ["total_amount"],
                "bound_rules": ["min_order_threshold"],
            },
        },
    )

    # Sinh và approve review cho Voucher
    rev = client.post(
        f"/api/stories/{voucher['id']}/requirement-reviews",
        headers={"Idempotency-Key": f"rev-voucher-{voucher['id']}"},
    ).json()
    client.post(f"/api/requirement-reviews/{rev['id']}/approve")

    # Giả lập bộ test case cho Voucher với 3 test cases khác biệt
    # TC-001: Không liên quan
    # TC-002: Chứa total_amount và min_order_threshold
    # TC-003: Không liên quan
    suite = client.post(
        f"/api/stories/{voucher['id']}/test-case-sets",
        headers={"Idempotency-Key": f"suite-voucher-{voucher['id']}"},
        json={"review_id": rev["id"]},
    ).json()

    # Cập nhật nội dung suite: TC-002 liên quan đến min_order_threshold và total_amount
    content = suite["content"]
    content["test_cases"][1]["title"] = "Áp voucher khi chưa đạt min_order_threshold của total_amount"
    content["test_cases"][1]["objective"] = "Kiểm tra giới hạn min_order_threshold"
    content["test_cases"][1]["expected_result"] = "Báo lỗi do chưa đạt min_order_threshold"
    content["test_cases"][1]["test_data"] = ["total_amount: 500000"]
    patch_resp = client.patch(f"/api/test-case-sets/{suite['id']}", json={"content": content})
    assert patch_resp.status_code == 200, patch_resp.text

    # Cập nhật Story Cart chạm vào min_order_threshold
    client.patch(
        f"/api/stories/{cart['id']}",
        json={"acceptance_criteria": ["Thay đổi quy tắc min_order_threshold của giỏ hàng"]},
    )

    # Kiểm tra: CHỈ DUY NHẤT TC-002 bị gắn cờ, TC-001 và TC-003 an toàn!
    report = client.get(f"/api/stories/{voucher['id']}/impact-analysis").json()
    assert report["has_impacted_dependencies"] is True
    upstream = report["upstream_impacts"][0]
    assert upstream["impact_status"] == "suspect_stale"
    assert "TC-002" in upstream["impacted_case_ids"]
    assert "TC-001" not in upstream["impacted_case_ids"]
    assert "TC-003" not in upstream["impacted_case_ids"]

    # Kiểm tra chi tiết case_details
    impacted_case_ids = [c["case_id"] for c in upstream["impacted_cases"]]
    assert "TC-002" in impacted_case_ids


def test_full_transitive_closure_across_five_stories(client):
    """AC-3: Duyệt toàn vẹn chuỗi 5 Story không giới hạn độ sâu (No Depth=3 truncation)."""
    auth = create_story_with_ac(client, "1. Auth", ["Xác thực"])
    cart = create_story_with_ac(client, "2. Cart", ["Giỏ hàng"])
    voucher = create_story_with_ac(client, "3. Voucher", ["Mã giảm"])
    checkout = create_story_with_ac(client, "4. Checkout", ["Thanh toán"])
    inventory = create_story_with_ac(client, "5. Inventory", ["Kho"])

    # Xây dựng chuỗi 5 cấp: Auth -> Cart -> Voucher -> Checkout -> Inventory
    client.post(f"/api/stories/{auth['id']}/dependencies", json={"target_story_id": cart["id"]})
    client.post(f"/api/stories/{cart['id']}/dependencies", json={"target_story_id": voucher["id"]})
    client.post(f"/api/stories/{voucher['id']}/dependencies", json={"target_story_id": checkout["id"]})
    client.post(f"/api/stories/{checkout['id']}/dependencies", json={"target_story_id": inventory["id"]})

    # Cập nhật Auth (Node đầu chuỗi)
    client.patch(
        f"/api/stories/{auth['id']}",
        json={"description": "Nâng cấp cơ chế xác thực đa yếu tố MFA bắt buộc"},
    )

    # Kiểm tra Node cuối chuỗi (Inventory ở khoảng cách Depth = 4): Phải được nhận biết tác động!
    inv_report = client.get(f"/api/stories/{inventory['id']}/impact-analysis").json()
    assert inv_report["has_impacted_dependencies"] is True
    upstream_source_ids = [item["source_story_id"] for item in inv_report["upstream_impacts"]]
    assert checkout["id"] in upstream_source_ids
