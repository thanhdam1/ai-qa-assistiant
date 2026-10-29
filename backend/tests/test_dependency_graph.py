import pytest
from app.database import Base, engine


def create_story_helper(client, title: str) -> dict:
    resp = client.post(
        "/api/stories",
        json={
            "title": title,
            "description": f"Mô tả cho {title}",
            "acceptance_criteria": [f"Tiêu chí cho {title}"],
            "business_context": "E2E Journey Testing",
            "dependencies": [],
            "language": "vi",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_add_valid_dependency(client):
    auth = create_story_helper(client, "Story A: Auth & Identity")
    cart = create_story_helper(client, "Story B: Shopping Cart")

    dep_resp = client.post(
        f"/api/stories/{auth['id']}/dependencies",
        json={
            "target_story_id": cart["id"],
            "dependency_type": "precondition",
            "binding_contract": {
                "consumed_outputs": ["user_token", "customer_id"],
                "bound_rules": ["authenticated_customer_required"],
            },
        },
    )
    assert dep_resp.status_code == 201, dep_resp.text
    dep = dep_resp.json()
    assert dep["source_story_id"] == auth["id"]
    assert dep["target_story_id"] == cart["id"]
    assert dep["dependency_type"] == "precondition"
    assert dep["synced_source_version"] == 1
    assert dep["impact_status"] == "synced"
    assert "user_token" in dep["binding_contract"]["consumed_outputs"]


def test_self_dependency_rejected(client):
    story = create_story_helper(client, "Story Self")
    resp = client.post(
        f"/api/stories/{story['id']}/dependencies",
        json={"target_story_id": story["id"]},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_dependency"


def test_two_node_cycle_rejected(client):
    auth = create_story_helper(client, "Auth")
    cart = create_story_helper(client, "Cart")

    # Auth -> Cart
    ok = client.post(
        f"/api/stories/{auth['id']}/dependencies",
        json={"target_story_id": cart["id"]},
    )
    assert ok.status_code == 201

    # Cart -> Auth (Chu trình 2 đỉnh)
    cycle = client.post(
        f"/api/stories/{cart['id']}/dependencies",
        json={"target_story_id": auth["id"]},
    )
    assert cycle.status_code == 409
    assert cycle.json()["error"]["code"] == "cyclic_dependency_detected"


def test_three_node_cycle_rejected(client):
    a = create_story_helper(client, "Node A")
    b = create_story_helper(client, "Node B")
    c = create_story_helper(client, "Node C")

    # A -> B -> C
    assert client.post(f"/api/stories/{a['id']}/dependencies", json={"target_story_id": b["id"]}).status_code == 201
    assert client.post(f"/api/stories/{b['id']}/dependencies", json={"target_story_id": c["id"]}).status_code == 201

    # C -> A (Chu trình 3 đỉnh)
    cycle = client.post(f"/api/stories/{c['id']}/dependencies", json={"target_story_id": a["id"]})
    assert cycle.status_code == 409
    assert cycle.json()["error"]["code"] == "cyclic_dependency_detected"


def test_five_node_e2e_journey_chain_and_deep_cycle(client):
    """Kiểm thử chuỗi 5 Story chuẩn E2E: Auth -> Cart -> Voucher -> Checkout -> Inventory."""
    auth = create_story_helper(client, "1. Auth & Identity")
    cart = create_story_helper(client, "2. Shopping Cart")
    voucher = create_story_helper(client, "3. Promotion Voucher")
    checkout = create_story_helper(client, "4. Payment Checkout")
    inventory = create_story_helper(client, "5. Warehouse Inventory")

    # Thiết lập chuỗi 5 cấp
    assert client.post(f"/api/stories/{auth['id']}/dependencies", json={"target_story_id": cart["id"]}).status_code == 201
    assert client.post(f"/api/stories/{cart['id']}/dependencies", json={"target_story_id": voucher["id"]}).status_code == 201
    assert client.post(f"/api/stories/{voucher['id']}/dependencies", json={"target_story_id": checkout["id"]}).status_code == 201
    assert client.post(f"/api/stories/{checkout['id']}/dependencies", json={"target_story_id": inventory["id"]}).status_code == 201

    # Kiểm tra chu trình sâu 5 cấp: Inventory -> Auth (bị chặn 409)
    cycle_5 = client.post(f"/api/stories/{inventory['id']}/dependencies", json={"target_story_id": auth["id"]})
    assert cycle_5.status_code == 409
    assert cycle_5.json()["error"]["code"] == "cyclic_dependency_detected"

    # Kiểm tra chu trình nhánh giữa: Checkout -> Cart (bị chặn 409)
    cycle_mid = client.post(f"/api/stories/{checkout['id']}/dependencies", json={"target_story_id": cart["id"]})
    assert cycle_mid.status_code == 409
    assert cycle_mid.json()["error"]["code"] == "cyclic_dependency_detected"


def test_dependency_tree_traversal(client):
    auth = create_story_helper(client, "Tree Auth")
    cart = create_story_helper(client, "Tree Cart")
    voucher = create_story_helper(client, "Tree Voucher")
    checkout = create_story_helper(client, "Tree Checkout")

    client.post(f"/api/stories/{auth['id']}/dependencies", json={"target_story_id": cart["id"]})
    client.post(f"/api/stories/{cart['id']}/dependencies", json={"target_story_id": voucher["id"]})
    client.post(f"/api/stories/{voucher['id']}/dependencies", json={"target_story_id": checkout["id"]})

    # Lấy tree cho Cart (ở giữa)
    tree_resp = client.get(f"/api/stories/{cart['id']}/dependency-tree")
    assert tree_resp.status_code == 200
    tree = tree_resp.json()

    # Upstream: Phải có Auth
    up_ids = [node["id"] for node in tree["upstream"]]
    assert auth["id"] in up_ids

    # Downstream: Phải có Voucher và Checkout (toàn diện không bị cắt cụt)
    down_ids = [node["id"] for node in tree["downstream"]]
    assert voucher["id"] in down_ids
    assert checkout["id"] in down_ids

    # Kiểm tra tham số max_depth = 1: Downstream chỉ chứa Voucher
    bounded_resp = client.get(f"/api/stories/{cart['id']}/dependency-tree?max_depth=1")
    assert bounded_resp.status_code == 200
    bounded_down_ids = [node["id"] for node in bounded_resp.json()["downstream"]]
    assert voucher["id"] in bounded_down_ids
    assert checkout["id"] not in bounded_down_ids


def test_remove_dependency(client):
    a = create_story_helper(client, "Del A")
    b = create_story_helper(client, "Del B")

    client.post(f"/api/stories/{a['id']}/dependencies", json={"target_story_id": b["id"]})
    # Xóa liên kết
    del_resp = client.delete(f"/api/stories/{a['id']}/dependencies/{b['id']}")
    assert del_resp.status_code == 204

    # Kiểm tra lại tree của A: Downstream rỗng
    tree = client.get(f"/api/stories/{a['id']}/dependency-tree").json()
    assert len(tree["downstream"]) == 0


def test_duplicate_dependency_updates_contract(client):
    a = create_story_helper(client, "Dup A")
    b = create_story_helper(client, "Dup B")

    first = client.post(
        f"/api/stories/{a['id']}/dependencies",
        json={"target_story_id": b["id"], "binding_contract": {"consumed_outputs": ["token_v1"]}},
    ).json()

    second = client.post(
        f"/api/stories/{a['id']}/dependencies",
        json={"target_story_id": b["id"], "binding_contract": {"consumed_outputs": ["token_v2"]}},
    ).json()

    assert first["id"] == second["id"]
    assert "token_v2" in second["binding_contract"]["consumed_outputs"]


def test_story_workspace_contains_dependencies(client):
    a = create_story_helper(client, "WS A")
    b = create_story_helper(client, "WS B")

    client.post(f"/api/stories/{a['id']}/dependencies", json={"target_story_id": b["id"]})

    ws_a = client.get(f"/api/stories/{a['id']}").json()
    assert len(ws_a["downstream_dependencies"]) == 1
    assert ws_a["downstream_dependencies"][0]["target_story_id"] == b["id"]

    ws_b = client.get(f"/api/stories/{b['id']}").json()
    assert len(ws_b["upstream_dependencies"]) == 1
    assert ws_b["upstream_dependencies"][0]["source_story_id"] == a["id"]
