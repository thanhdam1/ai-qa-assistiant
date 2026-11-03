import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, RequirementReview, Story, StoryDependency, TestCaseSet
from app.schemas import (
    CoverageEntry,
    CoverageStatus,
    CoverageTargetType,
    ExistingCriterion,
    Priority,
    RequirementObligation,
    RequirementReviewContent,
    TestCase,
    TestCaseSetContent,
    TestCaseType,
    TestStep,
    UpstreamTraceItem,
)
from app.services.dependency_graph import (
    analyze_story_impact,
    extract_upstream_contracts,
    propagate_story_impact,
)
from app.services.prompts import (
    TEST_CASE_PROMPT_VERSION,
    story_payload,
    test_case_input as build_test_case_input,
)
from app.services.workflow import validate_test_suite
from app.errors import AppError


@pytest.fixture
def mem_session():
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    TestingSession = sessionmaker(bind=test_engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(test_engine)


def test_upstream_trace_item_in_test_case():
    """Verify TestCase model supports upstream_traceability with 100% backward compatibility."""
    # Case without upstream_traceability (legacy data compatibility)
    case_legacy = TestCase(
        id="TC-001",
        title="Valid checkout test",
        objective="Verify checkout completes",
        type=TestCaseType.positive,
        basis="requirement",
        priority=Priority.high,
        preconditions=["User is logged in"],
        test_data=["cart_id: 123"],
        steps=[TestStep(order=1, action="Submit checkout", expected_result="Order placed")],
        expected_result="HTTP 200 Order confirmed",
        requirement_traceability=["REQ-01"],
        assumptions=[],
        needs_clarification=False,
    )
    assert case_legacy.upstream_traceability == []

    # Case with upstream_traceability populated
    trace_item = UpstreamTraceItem(
        source_story_id="STORY-CART-01",
        source_story_title="Giỏ hàng",
        source_version=2,
        consumed_fields=["cart.id", "cart.total_amount"],
        bound_rules=["min_order_threshold"],
        contract_reference="AC-01 của STORY-CART-01",
    )
    case_with_trace = TestCase(
        id="TC-002",
        title="Checkout with upstream cart",
        objective="Verify checkout uses cart output",
        type=TestCaseType.positive,
        basis="requirement",
        priority=Priority.high,
        preconditions=["Giỏ hàng hợp lệ từ STORY-CART-01"],
        test_data=["cart_id từ CART-01"],
        steps=[TestStep(order=1, action="Submit checkout", expected_result="Success")],
        expected_result="HTTP 200",
        requirement_traceability=["REQ-02"],
        upstream_traceability=[trace_item],
        assumptions=[],
        needs_clarification=False,
    )
    assert len(case_with_trace.upstream_traceability) == 1
    assert case_with_trace.upstream_traceability[0].source_story_id == "STORY-CART-01"
    assert "cart.id" in case_with_trace.upstream_traceability[0].consumed_fields


def test_story_payload_backward_compatibility():
    """Verify story_payload retains exact fields and only adds upstream_contracts when supplied."""
    dummy_story = Story(
        id="test-story-1",
        title="Test Story",
        description="Description",
        acceptance_criteria=["AC 1", "AC 2"],
        business_context="Context",
        dependencies=["Dep A"],
        language="vi",
        version=1,
    )

    # Legacy call without upstream_contracts
    payload_legacy = story_payload(dummy_story)
    assert "title" in payload_legacy
    assert "acceptance_criteria" in payload_legacy
    assert "upstream_contracts" not in payload_legacy

    # Call with upstream_contracts
    contracts = [{"source_story_id": "UPSTREAM-0", "dependency_type": "precondition"}]
    payload_with_contracts = story_payload(dummy_story, upstream_contracts=contracts)
    assert "upstream_contracts" in payload_with_contracts
    assert payload_with_contracts["upstream_contracts"] == contracts


def test_extract_upstream_contracts(mem_session):
    """Verify extract_upstream_contracts extracts structured contract data from DB."""
    db_session = mem_session
    # 1. Create upstream story (CART)
    cart_story = Story(
        title="Quản lý giỏ hàng Test Upstream",
        description="Cho phép thêm xóa sửa sản phẩm vào giỏ",
        acceptance_criteria=["AC-01: Giỏ hàng tính tổng tiền chính xác", "AC-02: Giỏ hết hạn sau 24h"],
        business_context="Thương mại điện tử",
        dependencies=[],
        version=2,
    )
    db_session.add(cart_story)
    db_session.commit()
    db_session.refresh(cart_story)

    # 2. Create downstream story (CHECKOUT)
    checkout_story = Story(
        title="Thanh toán đơn hàng Test Upstream",
        description="Thanh toán cho các sản phẩm trong giỏ",
        acceptance_criteria=["AC-01: Thanh toán thành công khi giỏ hợp lệ"],
        business_context="Thanh toán",
        dependencies=[],
        version=1,
    )
    db_session.add(checkout_story)
    db_session.commit()
    db_session.refresh(checkout_story)

    # 3. Initially standalone: no upstream contracts
    contracts_empty = extract_upstream_contracts(db_session, checkout_story.id)
    assert contracts_empty == []

    # 4. Create dependency edge with binding contract
    dep = StoryDependency(
        source_story_id=cart_story.id,
        target_story_id=checkout_story.id,
        dependency_type="data_fixture",
        synced_source_version=2,
        target_story_version=1,
        binding_contract={
            "consumed_outputs": ["cart.id", "cart.total_amount"],
            "bound_rules": ["min_order_threshold_50k"],
            "data_mappings": {
                "cart.id": "checkout.cart_id",
                "cart.total_amount": "checkout.payable_amount",
            },
            "usage_preconditions": ["Giỏ hàng phải ở trạng thái active"],
            "confirmed_error_rules": ["Giỏ rỗng bị từ chối với lỗi HTTP 400"],
        },
        impact_status="synced",
    )
    db_session.add(dep)
    db_session.commit()

    # 5. Extract contracts
    contracts = extract_upstream_contracts(db_session, checkout_story.id)
    assert len(contracts) == 1
    c = contracts[0]
    assert c["source_story_id"] == cart_story.id
    assert c["source_story_title"] == "Quản lý giỏ hàng Test Upstream"
    assert c["source_version"] == 2
    assert c["dependency_type"] == "data_fixture"
    assert "cart.id" in c["consumed_outputs"]
    assert "min_order_threshold_50k" in c["bound_rules"]
    assert len(c["data_mappings"]) == 2
    assert c["usage_preconditions"] == ["Giỏ hàng phải ở trạng thái active"]
    assert c["confirmed_error_rules"] == ["Giỏ rỗng bị từ chối với lỗi HTTP 400"]


def test_test_case_prompt_upstream_guardrails():
    """Verify test_case_input includes Section 11 upstream contract guardrails."""
    assert TEST_CASE_PROMPT_VERSION == "testcase-v12"
    dummy_story = Story(
        id="story-checkout",
        title="Thanh toán",
        description="Thanh toán đơn hàng",
        acceptance_criteria=["AC-01: Thanh toán thành công"],
        dependencies=[],
        version=1,
    )
    dummy_review = RequirementReviewContent(
        language="vi",
        business_summary="Thanh toán đơn hàng",
        existing_acceptance_criteria=[
            ExistingCriterion(
                id="REQ-01",
                source_reference="AC-01",
                criterion="Thanh toán thành công",
                obligations=[RequirementObligation(id="OBL-01", text="Thanh toán hợp lệ")],
            )
        ],
        missing_acceptance_criteria=[],
        ambiguities_and_conflicts=[],
        stakeholder_questions=[],
        edge_cases=[],
        assumptions=[],
        risks=[],
    )
    upstream_contract = [
        {
            "source_story_id": "CART-01",
            "source_story_title": "Giỏ hàng",
            "source_version": 2,
            "dependency_type": "data_fixture",
            "consumed_outputs": ["cart.id", "cart.total_amount"],
        }
    ]

    messages = build_test_case_input(dummy_story, dummy_review, upstream_contracts=upstream_contract)
    instructions = messages[0]["content"]

    # Verify key Phase 2 prompt guardrails
    assert "11. UPSTREAM CONTRACT & INTERFACE VERIFICATION" in instructions
    assert "Do NOT test upstream's internal logic" in instructions
    assert "Base error assertions strictly on confirmed contract rules" in instructions
    assert "Never invent HTTP error codes" in instructions
    assert "upstream_traceability" in instructions

    # Verify upstream_contracts payload is rendered in prompt user content
    user_content = messages[1]["content"]
    assert '"source_story_id": "CART-01"' in user_content
    assert '"cart.id"' in user_content


def test_validate_test_suite_upstream_traceability():
    """Verify validate_test_suite validates upstream_traceability appropriately."""
    dummy_review = RequirementReviewContent(
        language="vi",
        business_summary="Summary",
        existing_acceptance_criteria=[
            ExistingCriterion(
                id="REQ-01",
                source_reference="AC-01",
                criterion="Thanh toán thành công",
                obligations=[RequirementObligation(id="OBL-01", text="Thanh toán hợp lệ")],
            )
        ],
        missing_acceptance_criteria=[],
        ambiguities_and_conflicts=[],
        stakeholder_questions=[],
        edge_cases=[],
        assumptions=[],
        risks=[],
    )

    # Valid test case with upstream_traceability
    valid_case = TestCase(
        id="TC-001",
        title="Valid checkout test",
        objective="Verify checkout",
        type=TestCaseType.positive,
        basis="requirement",
        priority=Priority.high,
        preconditions=["User is logged in"],
        test_data=["cart_id"],
        steps=[TestStep(order=1, action="Submit", expected_result="Success")],
        expected_result="HTTP 200",
        requirement_traceability=["REQ-01", "OBL-01"],
        upstream_traceability=[
            UpstreamTraceItem(
                source_story_id="CART-01",
                source_story_title="Giỏ hàng",
                source_version=2,
                consumed_fields=["cart.id"],
            )
        ],
        assumptions=[],
        needs_clarification=False,
    )

    suite = TestCaseSetContent(
        language="vi",
        coverage_summary="Coverage summary",
        test_cases=[valid_case],
        coverage_matrix=[
            CoverageEntry(target_type=CoverageTargetType.category, target_id="positive", status=CoverageStatus.covered, test_case_ids=["TC-001"], explanation="Positive case"),
            CoverageEntry(target_type=CoverageTargetType.category, target_id="negative", status=CoverageStatus.needs_clarification, test_case_ids=[], explanation="Negative case"),
            CoverageEntry(target_type=CoverageTargetType.category, target_id="boundary", status=CoverageStatus.needs_clarification, test_case_ids=[], explanation="Boundary case"),
            CoverageEntry(target_type=CoverageTargetType.category, target_id="integration", status=CoverageStatus.needs_clarification, test_case_ids=[], explanation="Integration case"),
            CoverageEntry(target_type=CoverageTargetType.requirement_obligation, target_id="OBL-01", status=CoverageStatus.needs_clarification, test_case_ids=["TC-001"], explanation="Obligation verification pending"),
        ],
    )

    # Should pass without error
    validate_test_suite(suite, dummy_review, None, None)

    # Invalid case with whitespace/empty source_story_id in upstream_traceability
    invalid_trace = UpstreamTraceItem(source_story_id="   ", source_version=1)
    invalid_case = valid_case.model_copy(update={"upstream_traceability": [invalid_trace]})
    invalid_suite = suite.model_copy(update={"test_cases": [invalid_case]})

    with pytest.raises(AppError) as exc_info:
        validate_test_suite(invalid_suite, dummy_review, None, None)
    assert exc_info.value.code == "invalid_upstream_traceability"


def test_propagate_story_impact_granular_traceability(mem_session):
    """Verify propagate_story_impact isolates affected test cases using upstream_traceability (Zero-False-Alarm)."""
    db_session = mem_session

    # 1. Upstream Story (CART)
    cart = Story(
        title="Quản lý giỏ hàng",
        description="Cho phép quản lý giỏ hàng",
        acceptance_criteria=["AC-01: Cung cấp cart_id để thanh toán", "AC-02: Tính tổng tiền cart_total"],
        dependencies=[],
        version=1,
    )
    db_session.add(cart)
    db_session.commit()
    db_session.refresh(cart)

    # 2. Downstream Story (CHECKOUT)
    checkout = Story(
        title="Thanh toán đơn hàng",
        description="Thực hiện thanh toán",
        acceptance_criteria=["AC-01: Thanh toán thành công"],
        dependencies=[],
        version=1,
    )
    db_session.add(checkout)
    db_session.commit()
    db_session.refresh(checkout)

    # 3. Dependency Edge with consumed_outputs
    dep = StoryDependency(
        source_story_id=cart.id,
        target_story_id=checkout.id,
        dependency_type="data_fixture",
        synced_source_version=1,
        target_story_version=1,
        binding_contract={
            "consumed_outputs": ["cart_id", "cart_total"],
            "bound_rules": ["min_order_threshold"],
        },
        impact_status="synced",
    )
    db_session.add(dep)
    db_session.commit()

    # 4. Downstream TestCaseSet with 3 cases:
    # TC-001: traces to cart consuming "cart_id"
    # TC-002: traces to cart consuming "unrelated_field"
    # TC-003: local test case without upstream_traceability
    tc1 = {
        "id": "TC-001",
        "title": "Checkout with cart_id",
        "objective": "Verify checkout with cart_id",
        "type": "positive",
        "preconditions": ["User has cart"],
        "test_data": ["cart_id: 123"],
        "expected_result": "Success",
        "requirement_traceability": ["REQ-01"],
        "upstream_traceability": [
            {
                "source_story_id": cart.id,
                "source_story_title": cart.title,
                "source_version": 1,
                "consumed_fields": ["cart_id"],
            }
        ],
    }
    tc2 = {
        "id": "TC-002",
        "title": "Checkout with shipping coupon",
        "objective": "Verify coupon discount",
        "type": "positive",
        "preconditions": ["Coupon active"],
        "test_data": ["coupon_code"],
        "expected_result": "Discount applied",
        "requirement_traceability": ["REQ-01"],
        "upstream_traceability": [
            {
                "source_story_id": cart.id,
                "source_story_title": cart.title,
                "source_version": 1,
                "consumed_fields": ["unrelated_field"],
            }
        ],
    }
    tc3 = {
        "id": "TC-003",
        "title": "Local UI button validation",
        "objective": "Check button color",
        "type": "positive",
        "preconditions": [],
        "test_data": [],
        "expected_result": "Button is green",
        "requirement_traceability": ["REQ-01"],
        "upstream_traceability": [],
    }

    review = RequirementReview(
        story_id=checkout.id,
        story_version=1,
        ai_original={},
        content={"business_summary": "Thanh toán"},
        idempotency_key="test-key-review-impact",
        model_name="test-model",
        prompt_version="test-prompt-v1",
        status="approved",
    )
    db_session.add(review)
    db_session.commit()
    db_session.refresh(review)

    test_set = TestCaseSet(
        story_id=checkout.id,
        review_id=review.id,
        story_version=1,
        idempotency_key="test-key-set-impact",
        model_name="test-model",
        prompt_version="test-prompt-v1",
        ai_original={},
        content={"test_cases": [tc1, tc2, tc3]},
    )
    db_session.add(test_set)
    db_session.commit()

    # 5. Upstream CART changes: cart_id logic modified
    old_state = {"acceptance_criteria": cart.acceptance_criteria}
    cart.version = 2
    cart.acceptance_criteria = ["AC-01: Thay đổi format cart_id sang UUIDv4", "AC-02: Tính tổng tiền cart_total"]
    db_session.commit()

    # 6. Propagate Impact
    impacted_deps = propagate_story_impact(
        db_session,
        cart,
        old_state,
        {"acceptance_criteria": cart.acceptance_criteria},
    )

    assert len(impacted_deps) == 1
    d = impacted_deps[0]
    assert d.impact_status == "suspect_stale"

    # CRUCIAL INVARIANT: Only TC-001 (which consumes cart_id) is marked impacted!
    # TC-002 (unrelated_field) and TC-003 (local) MUST NOT be falsely flagged.
    assert "TC-001" in d.impacted_case_ids
    assert "TC-002" not in d.impacted_case_ids
    assert "TC-003" not in d.impacted_case_ids

    # 7. Verify analyze_story_impact reports exact field info
    report = analyze_story_impact(db_session, checkout.id)
    assert report.has_impacted_dependencies is True
    assert len(report.upstream_impacts) == 1
    cases_reported = report.upstream_impacts[0].impacted_cases
    assert len(cases_reported) == 1
    assert cases_reported[0].case_id == "TC-001"
    assert "cart_id" in cases_reported[0].reason


