def create_story(client):
    response = client.post(
        "/api/stories",
        json={
            "title": "Đăng nhập",
            "description": "Là người dùng, tôi muốn đăng nhập.",
            "acceptance_criteria": ["Email và mật khẩu đúng thì đăng nhập thành công"],
            "business_context": "Cổng khách hàng",
            "dependencies": ["Identity service"],
            "language": "auto",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_human_review_workflow_and_idempotency(client):
    story = create_story(client)
    headers = {"Idempotency-Key": "review-request-001"}
    first = client.post(f"/api/stories/{story['id']}/requirement-reviews", headers=headers)
    second = client.post(f"/api/stories/{story['id']}/requirement-reviews", headers=headers)
    assert first.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    review = first.json()
    blocked = client.post(
        f"/api/stories/{story['id']}/test-case-sets",
        headers={"Idempotency-Key": "tests-request-001"},
        json={"review_id": review["id"]},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "review_not_approved"

    approved = client.post(f"/api/requirement-reviews/{review['id']}/approve")
    assert approved.status_code == 200
    generated = client.post(
        f"/api/stories/{story['id']}/test-case-sets",
        headers={"Idempotency-Key": "tests-request-001"},
        json={"review_id": review["id"]},
    )
    assert generated.status_code == 201
    assert {case["type"] for case in generated.json()["content"]["test_cases"]} == {
        "positive",
        "negative",
        "boundary",
        "integration",
    }
    assert client.post(f"/api/test-case-sets/{generated.json()['id']}/approve").status_code == 200


def test_story_update_marks_history_stale(client):
    story = create_story(client)
    review = client.post(
        f"/api/stories/{story['id']}/requirement-reviews",
        headers={"Idempotency-Key": "review-stale-001"},
    ).json()
    assert client.post(f"/api/requirement-reviews/{review['id']}/approve").status_code == 200
    update = client.patch(f"/api/stories/{story['id']}", json={"description": "Updated behavior"})
    assert update.json()["version"] == 2
    workspace = client.get(f"/api/stories/{story['id']}").json()
    assert workspace["reviews"][0]["stale"] is True
    blocked = client.post(
        f"/api/stories/{story['id']}/test-case-sets",
        headers={"Idempotency-Key": "tests-stale-001"},
        json={"review_id": review["id"]},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "stale_version"


def test_export_json_and_csv(client):
    story = create_story(client)
    review = client.post(
        f"/api/stories/{story['id']}/requirement-reviews",
        headers={"Idempotency-Key": "export-review-001"},
    ).json()
    assert (
        client.get(f"/api/requirement-reviews/{review['id']}/export?format=json")
        .headers["content-type"]
        .startswith("application/json")
    )
    csv_response = client.get(f"/api/requirement-reviews/{review['id']}/export?format=csv")
    assert csv_response.status_code == 200
    assert csv_response.content.startswith(b"\xef\xbb\xbf")
