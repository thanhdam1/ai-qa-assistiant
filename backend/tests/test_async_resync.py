import pytest
from app.database import SessionLocal
from app.models import Story, StoryDependency, TestCaseSet, AsyncJob
from app.services.resync_engine import process_resync_job, trigger_resync_job


def create_story(client, title: str, ac_list: list[str]) -> dict:
    resp = client.post(
        "/api/stories",
        json={
            "title": title,
            "description": f"Mô tả cho {title}",
            "acceptance_criteria": ac_list,
            "business_context": "E2E Testing Context",
            "dependencies": [],
            "language": "vi",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def setup_cart_and_voucher_suite(client):
    cart = create_story(client, "Cart Upstream", ["Giới hạn giỏ hàng 10 sản phẩm", "Tổng tiền"])
    voucher = create_story(client, "Voucher Downstream", ["Áp mã voucher theo ngưỡng giỏ hàng"])

    # Tạo liên kết dependency
    dep_resp = client.post(
        f"/api/stories/{cart['id']}/dependencies",
        json={
            "target_story_id": voucher["id"],
            "dependency_type": "data_fixture",
            "binding_contract": {
                "consumed_outputs": ["cart_total"],
                "bound_rules": ["cart_limit"],
            },
        },
    )
    assert dep_resp.status_code == 201

    # Sinh review & approve
    rev = client.post(
        f"/api/stories/{voucher['id']}/requirement-reviews",
        headers={"Idempotency-Key": f"rev-{voucher['id']}"},
    ).json()
    client.post(f"/api/requirement-reviews/{rev['id']}/approve")

    # Sinh test case set
    suite = client.post(
        f"/api/stories/{voucher['id']}/test-case-sets",
        headers={"Idempotency-Key": f"suite-{voucher['id']}"},
        json={"review_id": rev["id"]},
    ).json()

    return cart, voucher, suite


def test_resync_api_returns_202_accepted(client):
    """AC-5: Gọi API re-sync phản hồi ngay lập tức với mã 202 Accepted và job_id."""
    cart, voucher, suite = setup_cart_and_voucher_suite(client)

    resp = client.post(f"/api/stories/{voucher['id']}/re-sync-dependencies")
    assert resp.status_code == 202, resp.text
    data = resp.json()
    assert "job_id" in data
    assert data["status"] in ["processing", "completed"]

    # Tra cứu tiến trình qua GET /api/jobs/{job_id}
    job_resp = client.get(f"/api/jobs/{data['job_id']}")
    assert job_resp.status_code == 200
    job_data = job_resp.json()
    assert job_data["id"] == data["job_id"]
    assert job_data["job_type"] == "story_dependency_resync"


def test_3_way_merge_auto_updates_pure_ai_case(client):
    """Kiểm chứng Test Case do AI sinh thuần túy (is_customized: false) được tự động đồng bộ."""
    cart, voucher, suite = setup_cart_and_voucher_suite(client)

    # Đảm bảo TC-002 có liên quan tới cart_limit và là do AI sinh thuần túy
    content = suite["content"]
    content["test_cases"][1]["title"] = "Kiểm tra cart_limit của giỏ hàng"
    content["test_cases"][1]["objective"] = "Kiểm tra cart_limit"
    content["test_cases"][1]["test_data"] = ["cart_limit = 10"]
    content["test_cases"][1]["is_customized"] = False
    patch_resp = client.patch(f"/api/test-case-sets/{suite['id']}", json={"content": content})
    assert patch_resp.status_code == 200

    # Đồng bộ ai_original để mô phỏng TC-002 do AI sinh ban đầu (chưa qua QA sửa tay)
    with SessionLocal() as db:
        ts = db.get(TestCaseSet, suite["id"])
        ts.ai_original = patch_resp.json()["content"]
        db.commit()

    # Cập nhật Story Cart (đổi cart_limit từ 10 thành 20)
    client.patch(
        f"/api/stories/{cart['id']}",
        json={"acceptance_criteria": ["Giới hạn giỏ hàng cart_limit đổi từ 10 thành 20 sản phẩm"]},
    )

    # Đảm bảo Story Voucher bị đánh dấu suspect_stale
    report = client.get(f"/api/stories/{voucher['id']}/impact-analysis").json()
    assert report["has_impacted_dependencies"] is True

    # Kích hoạt Re-sync (TestClient chạy BackgroundTasks tự động)
    resync_resp = client.post(f"/api/stories/{voucher['id']}/re-sync-dependencies")
    assert resync_resp.status_code == 202
    job_id = resync_resp.json()["job_id"]

    # Kiểm tra job kết quả
    job_resp = client.get(f"/api/jobs/{job_id}").json()
    assert job_resp["status"] == "completed"
    assert "TC-002" in job_resp["result"]["updated_cases"]

    # Kiểm tra test case đã được tự động cập nhật
    updated_suite = client.get(f"/api/stories/{voucher['id']}").json()["test_case_sets"][0]
    tc_002 = next(c for c in updated_suite["content"]["test_cases"] if c["id"] == "TC-002")
    assert any("Upstream synced" in p for p in tc_002["preconditions"])

    # Kiểm tra dependency đã chuyển về trạng thái 'synced'
    tree = client.get(f"/api/stories/{voucher['id']}/dependency-tree").json()
    assert tree["upstream"][0]["impact_status"] == "synced"


def test_3_way_merge_preserves_100_percent_qa_customization(client):
    """AC-6: Bảo toàn 100% chỉnh sửa thủ công của QA khi re-sync."""
    cart, voucher, suite = setup_cart_and_voucher_suite(client)

    # QA sửa thủ công TC-002 với assertion / expected_result đặc thù
    custom_expected = "QA MANUAL ASSERTION: Mã lỗi phải là ERR_VOUCHER_CART_LIMIT_EXCEEDED (Do QA chỉ định)"
    content = suite["content"]
    content["test_cases"][1]["title"] = "Kiểm tra cart_limit của giỏ hàng"
    content["test_cases"][1]["objective"] = "Kiểm tra cart_limit"
    content["test_cases"][1]["expected_result"] = custom_expected
    content["test_cases"][1]["is_customized"] = True
    patch_resp = client.patch(f"/api/test-case-sets/{suite['id']}", json={"content": content})
    assert patch_resp.status_code == 200

    # Cập nhật Story Cart (đổi cart_limit)
    client.patch(
        f"/api/stories/{cart['id']}",
        json={"acceptance_criteria": ["Giới hạn giỏ hàng cart_limit đổi từ 10 thành 25 sản phẩm"]},
    )

    # Re-sync (TestClient chạy BackgroundTasks tự động)
    resync_resp = client.post(f"/api/stories/{voucher['id']}/re-sync-dependencies")
    job_id = resync_resp.json()["job_id"]

    job_data = client.get(f"/api/jobs/{job_id}").json()
    assert job_data["status"] == "completed"
    assert "TC-002" in job_data["result"]["preserved_cases"]

    # Kiểm tra có Side-by-Side Merge Conflict Proposal
    conflicts = job_data["result"]["conflicts"]
    assert len(conflicts) > 0
    conflict_tc2 = next(c for c in conflicts if c["case_id"] == "TC-002")
    assert conflict_tc2["qa_version"]["expected_result"] == custom_expected
    assert "[Synced" in conflict_tc2["ai_proposal"]["expected_result"]

    # Kiểm tra quan trọng nhất: QA Assertion KHÔNG HỀ BỊ GHI ĐÈ!
    updated_suite = client.get(f"/api/stories/{voucher['id']}").json()["test_case_sets"][0]
    tc_002 = next(c for c in updated_suite["content"]["test_cases"] if c["id"] == "TC-002")
    assert tc_002["expected_result"] == custom_expected


def test_optimistic_concurrency_failure_when_upstream_changes(client):
    """Optimistic Locking: Báo lỗi an toàn nếu Story cha bị sửa tiếp trong lúc Worker đang chạy."""
    cart, voucher, suite = setup_cart_and_voucher_suite(client)

    # Đánh dấu TC-002
    content = suite["content"]
    content["test_cases"][1]["title"] = "Kiểm tra cart_limit của giỏ hàng"
    patch_resp = client.patch(f"/api/test-case-sets/{suite['id']}", json={"content": content})
    assert patch_resp.status_code == 200

    client.patch(
        f"/api/stories/{cart['id']}",
        json={"acceptance_criteria": ["cart_limit đổi thành 20"]},
    )

    # Khởi tạo job chạy nền (background_tasks=None để tách riêng pha trigger và worker)
    with SessionLocal() as db:
        job = trigger_resync_job(db, voucher["id"], background_tasks=None)
        job_id = job.id

    # Giả lập trước khi worker kết thúc commit, Story cha lại bị sửa tiếp lên version 3
    client.patch(
        f"/api/stories/{cart['id']}",
        json={"acceptance_criteria": ["cart_limit đổi thành 30 (concurrent update)"]},
    )

    # Giờ worker mới chạy để đối soát và commit
    process_resync_job(job_id, voucher["id"])

    # Job phải bị FAILED do xung đột phiên bản đồng thời
    job_status = client.get(f"/api/jobs/{job_id}").json()
    assert job_status["status"] == "failed"
    assert "Upstream story updated concurrently" in job_status["error_message"]


def test_resolve_merge_conflict_endpoints(client):
    """Kiểm chứng endpoint QA chủ động giải quyết Merge Conflict (keep_qa hoặc apply_ai)."""
    cart, voucher, suite = setup_cart_and_voucher_suite(client)

    # QA xác nhận giữ lại chỉnh sửa của mình
    resp_keep = client.post(
        f"/api/stories/{voucher['id']}/resolve-conflict",
        json={"case_id": "TC-002", "action": "keep_qa"},
    )
    assert resp_keep.status_code == 200
    assert resp_keep.json()["action"] == "keep_qa"

    # QA xác nhận nhận đề xuất của AI
    resp_ai = client.post(
        f"/api/stories/{voucher['id']}/resolve-conflict",
        json={"case_id": "TC-002", "action": "apply_ai"},
    )
    assert resp_ai.status_code == 200
    assert resp_ai.json()["action"] == "apply_ai"
