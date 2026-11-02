import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Story, StoryDependency
from app.schemas import TestCase, UpstreamTraceItem, TestCaseType, Priority, TestStep
from app.services.dependency_graph import extract_upstream_contracts
from app.services.prompts import story_payload


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
