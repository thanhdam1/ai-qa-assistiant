import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.agents.reflection_node import ReflectionNode
from app.agents.pom_codegen_agent import POMCodeGenerator
from app.api.v1.qa_assistant import generate_pom_scripts, GeneratePOMRequest

def test_reflection_node_syntax_validation():
    valid_code = """
def calculate_discount(price, rate):
    if rate > 0:
        return price * (1 - rate)
    return price
"""
    is_valid, errors = ReflectionNode.validate_code_syntax(valid_code, "python")
    assert is_valid is True
    assert len(errors) == 0

    broken_code = """
def broken_function(a, b)
    return a + b
"""
    is_valid, errors = ReflectionNode.validate_code_syntax(broken_code, "python")
    assert is_valid is False
    assert len(errors) > 0
    assert "SyntaxError" in errors[0]

def test_reflection_node_self_healing():
    # Broken function missing colon
    broken_code = """def solve_math(x, y)
    return x * y
"""
    result = ReflectionNode.validate_and_heal(broken_code, "math_helper.py", language="python")
    assert result.is_valid is True
    assert result.healing_attempts >= 1
    assert "def solve_math(x, y):" in result.fixed_content

def test_pom_codegen_playwright_python():
    suite = POMCodeGenerator.generate_playwright_suite("User Checkout", language="python")
    
    assert suite.feature_name == "User Checkout"
    assert suite.framework == "playwright"
    assert suite.language == "python"
    assert len(suite.files) == 3
    assert suite.all_valid is True

    # Check BasePage
    base_file = next(f for f in suite.files if f.file_type == "base_page")
    assert "class BasePage:" in base_file.content
    assert base_file.syntax_valid is True

    # Check Feature Page Object
    page_file = next(f for f in suite.files if f.file_type == "page_object")
    assert "class UserCheckoutPage(BasePage):" in page_file.content
    assert "data-testid" in page_file.content
    assert page_file.syntax_valid is True

    # Check Test Spec
    test_file = next(f for f in suite.files if f.file_type == "test_spec")
    assert "test_user_checkout" in test_file.content or "test_positive" in test_file.content
    assert test_file.syntax_valid is True

def test_pom_codegen_playwright_typescript():
    suite = POMCodeGenerator.generate_playwright_suite("User Login", language="typescript")
    assert len(suite.files) == 3
    assert suite.language == "typescript"
    assert any("export class UserLoginPage" in f.content for f in suite.files)

def test_generate_pom_scripts_api():
    req = GeneratePOMRequest(feature_name="Shopping Cart", language="python")
    res = generate_pom_scripts(req)
    assert res.all_valid is True
    assert len(res.files) == 3

def test_pom_codegen_enterprise_modular_python():
    suite = POMCodeGenerator.generate_playwright_suite(
        "Chuyển Khoản Liên Ngân Hàng",
        language="python",
        suite_type="enterprise_modular"
    )
    assert suite.suite_type == "enterprise_modular"
    assert len(suite.files) == 7
    assert suite.all_valid is True

    # Ensure all file paths and types are distinct
    file_types = [f.file_type for f in suite.files]
    assert file_types == [
        "base_page",
        "page_object",
        "fixture_config",
        "test_positive",
        "test_boundary",
        "test_negative",
        "test_security"
    ]

    # Verify each file has unique and valid content
    contents = [f.content for f in suite.files]
    assert len(set(contents)) == 7  # All 7 contents are completely distinct!

    # Check fixture config
    conftest_file = next(f for f in suite.files if f.file_type == "fixture_config")
    assert "pytest_runtest_makereport" in conftest_file.content
    assert conftest_file.file_path == "tests/conftest.py"
    assert conftest_file.syntax_valid is True

    # Check positive spec
    pos_file = next(f for f in suite.files if f.file_type == "test_positive")
    assert "test_chuyen_khoan_lien_ngan_hang_positive" in pos_file.content
    assert pos_file.syntax_valid is True

    # Check boundary spec
    bva_file = next(f for f in suite.files if f.file_type == "test_boundary")
    assert "test_chuyen_khoan_lien_ngan_hang_boundary" in bva_file.content
    assert bva_file.syntax_valid is True

    # Check negative spec
    neg_file = next(f for f in suite.files if f.file_type == "test_negative")
    assert "test_chuyen_khoan_lien_ngan_hang_negative" in neg_file.content
    assert neg_file.syntax_valid is True

    # Check security spec
    sec_file = next(f for f in suite.files if f.file_type == "test_security")
    assert "test_chuyen_khoan_lien_ngan_hang_security" in sec_file.content
    assert sec_file.syntax_valid is True

def test_pom_codegen_enterprise_modular_typescript():
    suite = POMCodeGenerator.generate_playwright_suite(
        "User Checkout",
        language="typescript",
        suite_type="enterprise_modular"
    )
    assert suite.suite_type == "enterprise_modular"
    assert len(suite.files) == 7
    assert suite.language == "typescript"
    assert any(f.file_path == "tests/fixtures.ts" for f in suite.files)
    assert any(f.file_type == "test_security" for f in suite.files)

def test_generate_pom_scripts_api_modular():
    req = GeneratePOMRequest(
        feature_name="Xác Thực Đăng Nhập",
        language="python",
        suite_type="enterprise_modular"
    )
    res = generate_pom_scripts(req)
    assert res.all_valid is True
    assert len(res.files) == 7
    assert res.suite_type == "enterprise_modular"

def test_pom_codegen_furniture_voucher_real_prd():
    prd_voucher = """
# Tính năng Áp Dụng Voucher Cho Web Bán Đồ Nội Thất
### Acceptance Criteria:
- Given giỏ hàng có bàn ghế gỗ sồi '25,000,000 VND' When khách hàng nhập mã voucher 'NOITHAT2026' và chọn phương thức áp dụng 'Giảm 10%' và bấm 'Áp dụng voucher' Then hệ thống xác nhận giảm giá thành công.
- Given giỏ hàng rỗng When khách hàng bấm 'Áp dụng voucher' Then hệ thống chặn và báo lỗi 'Mã voucher không áp dụng cho giỏ hàng rỗng'.
- Given mã voucher hết hạn When khách hàng nhập mã voucher 'EXPIRED_2025' và bấm 'Áp dụng voucher' Then hệ thống từ chối và báo lỗi 'Mã voucher đã hết hạn'.
- Given payload SQLi When khách hàng nhập mã voucher "'; DROP TABLE VOUCHERS; --" và bấm 'Áp dụng voucher' Then hệ thống ngăn chặn an toàn.
"""
    suite = POMCodeGenerator.generate_playwright_suite(
        feature_name="Áp Dụng Voucher Nội Thất",
        language="python",
        suite_type="enterprise_modular",
        prd_content=prd_voucher
    )
    assert suite.all_valid is True
    assert len(suite.files) == 7

    # Check Page Object has extracted fields and action
    page_file = next(f for f in suite.files if f.file_type == "page_object")
    assert "ma_voucher" in page_file.content
    assert "btn-ap_dung_voucher" in page_file.content
    assert "submit_ap_dung_voucher" in page_file.content

    # Check Positive Test uses extracted sample value
    pos_file = next(f for f in suite.files if f.file_type == "test_positive")
    assert "NOITHAT2026" in pos_file.content

    # Check Negative Test checks expected error message
    neg_file = next(f for f in suite.files if f.file_type == "test_negative")
    assert "Mã voucher đã hết hạn" in neg_file.content or "giỏ hàng rỗng" in neg_file.content

def test_pom_codegen_furniture_deposit_30_percent_real_prd():
    prd_deposit = """
# Tính năng Đặt Cọc 30% Đơn Hàng Nội Thất
### Acceptance Criteria:
- Given đơn hàng sofa da '30,000,000 VND' When khách hàng chọn phương thức đặt cọc '30%' và nhập số tiền cọc '9,000,000 VND' và bấm 'Xác nhận đặt cọc' Then hệ thống xác nhận thanh toán cọc thành công.
- Given số tiền cọc nhỏ hơn 30% When khách hàng sửa số tiền cọc '5,000,000 VND' và bấm 'Xác nhận đặt cọc' Then hệ thống báo lỗi 'Số tiền cọc tối thiểu là 30%'.
"""
    suite = POMCodeGenerator.generate_playwright_suite(
        feature_name="Đặt Cọc 30% Đơn Hàng",
        language="python",
        suite_type="standard_3tier",
        prd_content=prd_deposit
    )
    assert suite.all_valid is True
    assert len(suite.files) == 3

    page_file = next(f for f in suite.files if f.file_type == "page_object")
    assert "phuong_thuc_dat_coc" in page_file.content or "so_tien_coc" in page_file.content
    assert "btn-xac_nhan_dat_coc" in page_file.content

    test_file = next(f for f in suite.files if f.file_type == "test_spec")
    assert "9,000,000 VND" in test_file.content or "30%" in test_file.content

def test_pom_codegen_furniture_shipping_fee_real_prd():
    prd_shipping = """
# Tính năng Tính Phí Vận Chuyển Hàng Nội Thất Cồng Kềnh
### Acceptance Criteria:
- Given địa chỉ giao hàng When khách hàng chọn tỉnh thành 'TP.HCM' và nhập trọng lượng hàng '45 kg' và bấm 'Tính phí vận chuyển' Then hệ thống hiển thị phí vận chuyển '150,000 VND'.
- Given địa chỉ giao hàng ngoại tỉnh When khách hàng chọn tỉnh thành 'Đồng Nai' và bấm 'Tính phí vận chuyển' Then hệ thống hiển thị phí vận chuyển '350,000 VND'.
"""
    suite = POMCodeGenerator.generate_playwright_suite(
        feature_name="Tính Phí Vận Chuyển Nội Thất",
        language="python",
        suite_type="standard_3tier",
        prd_content=prd_shipping
    )
    assert suite.all_valid is True
    assert len(suite.files) == 3

    page_file = next(f for f in suite.files if f.file_type == "page_object")
    assert "tinh_thanh" in page_file.content
    assert "btn-tinh_phi_van_chuyen" in page_file.content

    test_file = next(f for f in suite.files if f.file_type == "test_spec")
    assert "TP.HCM" in test_file.content or "45 kg" in test_file.content
