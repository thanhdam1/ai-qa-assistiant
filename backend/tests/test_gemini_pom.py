import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from app.core.gemini_pom_client import GeminiPOMGenerator, GeminiPOMResponse
from app.agents.pom_codegen_agent import POMCodeGenerator
from app.api.v1.qa_assistant import generate_pom_scripts, GeneratePOMRequest

def test_gemini_convert_to_semantic_spec():
    sample_gemini_json = {
        "class_name": "FurnitureCartCheckoutPage",
        "feature_slug": "furniture_cart_checkout",
        "locators": {
            "VOUCHER_INPUT": "[data-testid='voucher-code-input']",
            "BTN_APPLY_VOUCHER": "[data-testid='btn-apply-voucher']",
            "QUANTITY_INPUT": "[data-testid='item-quantity-input']",
            "TOTAL_PRICE_DISPLAY": "[data-testid='order-total-display']",
            "SUCCESS_BANNER": "[data-testid='order-success-banner']",
            "ERROR_ALERT": "[data-testid='order-error-alert']"
        },
        "actions": [
            {
                "method_name": "apply_voucher",
                "description": "Applies a discount voucher to the furniture order.",
                "params": [{"name": "voucher_code", "type": "str", "default": "NOITHATVIP2026"}],
                "steps": [
                    "self.fill_input(self.VOUCHER_INPUT, str(voucher_code))",
                    "self.click_element(self.BTN_APPLY_VOUCHER)"
                ]
            },
            {
                "method_name": "update_item_quantity",
                "description": "Updates item quantity in shopping cart.",
                "params": [{"name": "quantity", "type": "int", "default": "1"}],
                "steps": [
                    "self.fill_input(self.QUANTITY_INPUT, str(quantity))"
                ]
            }
        ],
        "positive_tests": [
            {
                "test_id": "TC-POS-01",
                "category": "positive",
                "title": "Apply valid voucher successfully",
                "given": "Cart has items",
                "when": "User enters valid voucher",
                "then": "Discount applied",
                "action_call": "page.apply_voucher(voucher_code='NOITHATVIP2026')",
                "assertions": ["assert page.is_success()"]
            }
        ],
        "boundary_tests": [
            {
                "test_id": "TC-BVA-01",
                "category": "boundary",
                "title": "Minimum order amount boundary",
                "given": "Order reaches minimum threshold",
                "when": "Voucher applied",
                "then": "Accepted",
                "action_call": "page.apply_voucher(voucher_code='MIN_LIMIT')",
                "assertions": ["assert page.is_success()"]
            }
        ],
        "negative_tests": [
            {
                "test_id": "TC-NEG-01",
                "category": "negative",
                "title": "Expired voucher rejection",
                "given": "Voucher expired in 2025",
                "when": "User submits expired voucher",
                "then": "Error alert displayed",
                "action_call": "page.apply_voucher(voucher_code='EXPIRED_2025')",
                "assertions": ["assert not page.is_success()", "assert 'hết hạn' in page.get_error_message()"],
                "expected_error": "Mã voucher đã hết hạn"
            }
        ],
        "security_tests": [
            {
                "test_id": "TC-SEC-01",
                "title": "Negative Quantity Tampering",
                "attack_vector": "negative_quantity",
                "description": "Attempt to submit negative quantity -5 to reduce cart price",
                "action_call": "page.update_item_quantity(quantity=-5)",
                "assertions": [
                    "assert not page.is_success()",
                    "assert len(page.get_error_message()) > 0"
                ]
            },
            {
                "test_id": "TC-SEC-02",
                "title": "Voucher Code Brute-force & Rate Limiting",
                "attack_vector": "voucher_bruteforce",
                "description": "Rapid submissions of generated voucher combinations",
                "action_call": "page.apply_voucher(voucher_code='BRUTE_FORCE_PAYLOAD')",
                "assertions": [
                    "assert not page.is_success() or len(page.get_error_message()) >= 0"
                ]
            },
            {
                "test_id": "TC-SEC-03",
                "title": "Price Tampering & Parameter Manipulation",
                "attack_vector": "price_tampering",
                "description": "Client-side total modification before checkout",
                "action_call": "page.apply_voucher(voucher_code='TAMPER_PAYLOAD')",
                "assertions": [
                    "assert not page.is_success() or len(page.get_error_message()) >= 0"
                ]
            },
            {
                "test_id": "TC-SEC-04",
                "title": "Insecure Direct Object Reference (IDOR)",
                "attack_vector": "idor",
                "description": "Manipulating order ID to view another customer's order",
                "action_call": "page.apply_voucher(voucher_code='ORD-99999')",
                "assertions": [
                    "assert not page.is_success() or len(page.get_error_message()) >= 0"
                ]
            }
        ]
    }

    spec = GeminiPOMGenerator._convert_to_semantic_spec(sample_gemini_json, "Furniture Cart Checkout")
    assert spec.class_name == "FurnitureCartCheckoutPage"
    assert spec.slug == "furniture_cart_checkout"
    assert "VOUCHER_INPUT" in spec.locators
    assert len(spec.actions) == 2
    assert spec.actions[0].method_name == "apply_voucher"
    assert spec.actions[1].method_name == "update_item_quantity"

    # Verify security criteria
    security_criteria = [c for c in spec.criteria if c.category == "security"]
    assert len(security_criteria) == 4
    assert any("NEGATIVE_QUANTITY" in c.title for c in security_criteria)
    assert any("VOUCHER_BRUTEFORCE" in c.title for c in security_criteria)
    assert any("PRICE_TAMPERING" in c.title for c in security_criteria)
    assert any("IDOR" in c.title for c in security_criteria)

def test_pom_codegen_with_gemini_and_real_dom():
    dom_snippet = """
    <div class="furniture-order-form">
      <input data-testid="real-voucher-input" name="voucher_code" placeholder="Mã giảm giá">
      <button data-testid="real-btn-apply" class="btn-checkout">Áp Dụng</button>
      <input data-testid="real-deposit-rate" name="deposit_percent" value="30%">
      <div data-testid="real-success-banner" class="alert-success">Thành công</div>
    </div>
    """
    prd_text = """
    # Đặt Hàng & Voucher Nội Thất
    - Given giỏ hàng ghế gỗ When khách hàng nhập voucher 'NOITHATVIP' và bấm 'Áp Dụng' Then thành công.
    - Given giỏ hàng rỗng When khách hàng bấm 'Áp Dụng' Then báo lỗi 'Giỏ hàng rỗng'.
    """

    # Generates with fallback to rule-based parser incorporating DOM
    suite = POMCodeGenerator.generate_playwright_suite(
        feature_name="Voucher Nội Thất DOM",
        language="python",
        suite_type="enterprise_modular",
        prd_content=prd_text,
        dom_content=dom_snippet,
        use_gemini=False  # Test deterministic fallback path
    )

    assert suite.all_valid is True
    assert len(suite.files) == 7

    page_file = next(f for f in suite.files if f.file_type == "page_object")
    assert "class VoucherNoiThatDomPage" in page_file.content
    assert page_file.syntax_valid is True

    sec_file = next(f for f in suite.files if f.file_type == "test_security")
    assert sec_file.syntax_valid is True

def test_api_generate_pom_with_dom_and_gemini_flags():
    req = GeneratePOMRequest(
        feature_name="Voucher & Đặt Cọc 30%",
        language="python",
        suite_type="enterprise_modular",
        prd_content="Given don hang When khach hang nhap voucher 'VIP2026' Then thanh cong",
        dom_content="<input data-testid='vip-voucher'>",
        use_gemini=False
    )
    res = generate_pom_scripts(req)
    assert res.all_valid is True
    assert len(res.files) == 7
    assert res.suite_type == "enterprise_modular"
