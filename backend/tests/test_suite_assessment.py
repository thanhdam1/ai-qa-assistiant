from test_workflow_api import create_story


def generated_suite(client):
    story = create_story(client)
    review = client.post(
        f"/api/stories/{story['id']}/requirement-reviews",
        headers={"Idempotency-Key": "assessment-review-001"},
    ).json()
    assert client.post(f"/api/requirement-reviews/{review['id']}/approve").status_code == 200
    suite_response = client.post(
        f"/api/stories/{story['id']}/test-case-sets",
        headers={"Idempotency-Key": "assessment-suite-001"},
        json={"review_id": review["id"]},
    )
    assert suite_response.status_code == 201, suite_response.text
    return story, suite_response.json()


def test_content_approval_does_not_accept_coverage(client):
    _, suite = generated_suite(client)
    suite_id = suite["id"]
    approved = client.post(f"/api/test-case-sets/{suite_id}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["review_status"] == "approved"
    assert approved.json()["coverage_acceptance_status"] == "pending"
    assert approved.json()["execution_readiness"] == "not_assessed"
    refused = client.post(
        f"/api/test-case-sets/{suite_id}/coverage-accept", json={"accepted_by": "QA A"}
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "coverage_decisions_incomplete"
    assert refused.json()["error"]["details"]["missing"]


def test_gap_decisions_are_not_covered_and_invalidate_on_edit(client):
    _, suite = generated_suite(client)
    suite_id = suite["id"]
    assert client.post(f"/api/test-case-sets/{suite_id}/approve").status_code == 200
    targets = [item for item in suite["content"]["coverage_matrix"] if item["target_type"] != "category"]
    assert targets
    for target in targets:
        decision = client.put(
            f"/api/test-case-sets/{suite_id}/coverage-decisions",
            json={"target_type": target["target_type"], "target_id": target["target_id"],
                  "disposition": "blocked", "decided_by": "QA A", "reason": "Business rule unresolved"},
        )
        assert decision.status_code == 200, decision.text
    accepted = client.post(
        f"/api/test-case-sets/{suite_id}/coverage-accept", json={"accepted_by": "QA A"}
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["coverage_acceptance_status"] == "accepted"
    assert accepted.json()["coverage_status"] == "unsubstantiated"
    changed = client.patch(
        f"/api/test-case-sets/{suite_id}", json={"content": suite["content"]}
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["content_version"] == suite["content_version"] + 1
    assert changed.json()["coverage_acceptance_status"] == "pending"
    assert changed.json()["coverage_decisions"] == []


def test_high_risk_cannot_be_self_accepted(client):
    _, suite = generated_suite(client)
    risk = next(item for item in suite["content"]["coverage_matrix"] if item["target_type"] == "risk")
    response = client.put(
        f"/api/test-case-sets/{suite['id']}/coverage-decisions",
        json={"target_type": "risk", "target_id": risk["target_id"],
              "disposition": "accepted_risk", "decided_by": "QA A", "reason": "Accepting it"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "risk_acceptance_requires_authority"


def test_case_readiness_is_independent(client):
    _, suite = generated_suite(client)
    case = next(item for item in suite["content"]["test_cases"] if not item["needs_clarification"])
    response = client.put(
        f"/api/test-case-sets/{suite['id']}/cases/{case['id']}/readiness",
        json={"assessed_by": "QA A", "environment_ready": True,
              "test_data_ready": True, "verification_ready": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["execution_readiness"] == "partial"
    assert response.json()["coverage_acceptance_status"] == "pending"


def test_confirmed_coverage_requires_exact_assertion(client):
    _, suite = generated_suite(client)
    suite_id = suite["id"]
    content = suite["content"]
    case = next(item for item in content["test_cases"] if not item["needs_clarification"])
    row = next(item for item in content["coverage_matrix"] if item["target_type"] == "requirement_obligation")
    case["requirement_traceability"] = list(set([*case["requirement_traceability"], row["target_id"]]))
    row.update({"status": "covered", "test_case_ids": [case["id"]], "unverified_aspects": [],
                "assertion_evidence": [{"test_case_id": case["id"], "assertion": case["expected_result"],
                                        "verifies_business_outcome": True}]})
    edited = client.patch(f"/api/test-case-sets/{suite_id}", json={"content": content})
    assert edited.status_code == 200, edited.text
    assert edited.json()["coverage_status"] == "partial"
    assert edited.json()["qa_confirmed_target_count"] == 0
    bad = client.put(
        f"/api/test-case-sets/{suite_id}/coverage-decisions",
        json={"target_type": row["target_type"], "target_id": row["target_id"],
              "disposition": "confirmed", "decided_by": "QA A",
              "assertion_case_id": case["id"], "assertion": "Made-up expected result"},
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "coverage_evidence_unconfirmed"
    good = client.put(
        f"/api/test-case-sets/{suite_id}/coverage-decisions",
        json={"target_type": row["target_type"], "target_id": row["target_id"],
              "disposition": "confirmed", "decided_by": "QA A",
              "assertion_case_id": case["id"], "assertion": case["expected_result"]},
    )
    assert good.status_code == 200, good.text
    assert good.json()["coverage_status"] == "partial"
    assert good.json()["qa_confirmed_target_count"] == 1


def test_source_change_invalidates_assessment(client):
    story, suite = generated_suite(client)
    row = next(item for item in suite["content"]["coverage_matrix"] if item["target_type"] != "category")
    decided = client.put(
        f"/api/test-case-sets/{suite['id']}/coverage-decisions",
        json={"target_type": row["target_type"], "target_id": row["target_id"],
              "disposition": "blocked", "decided_by": "QA A", "reason": "Waiting for BA"},
    )
    assert decided.status_code == 200
    assert client.patch(f"/api/stories/{story['id']}", json={"description": "Updated"}).status_code == 200
    workspace = client.get(f"/api/stories/{story['id']}").json()
    current = next(item for item in workspace["test_case_sets"] if item["id"] == suite["id"])
    assert current["stale"] is True
    assert current["coverage_acceptance_status"] == "pending"
    assert client.post(
        f"/api/test-case-sets/{suite['id']}/coverage-accept", json={"accepted_by": "QA A"}
    ).status_code == 409
