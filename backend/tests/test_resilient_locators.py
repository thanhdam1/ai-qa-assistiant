import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.agents.reflection_node import ReflectionNode
from app.api.v1.qa_assistant import synthesize_locators_endpoint, ResilientLocatorRequest

def test_synthesize_resilient_locators_hierarchy():
    # Test case 1: Element with data-testid (Highest Priority Level 1)
    locs1 = ReflectionNode.synthesize_resilient_locator(
        element_tag="button",
        attributes={"data-testid": "checkout-btn", "id": "btn-xyz", "role": "button"},
        inner_text="Proceed to Checkout"
    )
    assert len(locs1) >= 2
    assert locs1[0].priority_level == 1
    assert locs1[0].locator_code == 'page.get_by_test_id("checkout-btn")'

    # Test case 2: Element with role and accessible text (Priority Level 2)
    locs2 = ReflectionNode.synthesize_resilient_locator(
        element_tag="button",
        attributes={"type": "button"},
        inner_text="Submit Order"
    )
    assert any(l.priority_level == 2 for l in locs2)
    assert any('page.get_by_role("button", name="Submit Order")' in l.locator_code for l in locs2)

    # Test case 3: Element with placeholder (Priority Level 4)
    locs3 = ReflectionNode.synthesize_resilient_locator(
        element_tag="input",
        attributes={"type": "text", "placeholder": "Enter promo code"}
    )
    assert any(l.priority_level == 4 for l in locs3)
    assert any('page.get_by_placeholder("Enter promo code")' in l.locator_code for l in locs3)

def test_multi_turn_reflection_turn_history():
    broken_code = """def test_example(page)
    x = 1
"""
    result = ReflectionNode.validate_and_heal(broken_code, "test.py", language="python", max_retries=2)
    assert result.is_valid is True
    assert result.healing_attempts >= 1
    assert len(result.turn_history) >= 1

def test_resilient_locators_api_endpoint():
    res = synthesize_locators_endpoint(ResilientLocatorRequest(
        element_tag="button",
        attributes={"data-testid": "pay-now-btn", "role": "button"},
        inner_text="Pay Now"
    ))
    assert isinstance(res, list)
    assert len(res) >= 2
    assert res[0].locator_type == "test_id"
