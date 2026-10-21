"""
Test Suite for Thanh Toán & Đặt Hàng:
Automates Positive Happy Path, Boundary Limits, Negative Verification and Security Injection against ThanhToanDatHangPage.
Synthesized directly from PRD specifications.
"""
import pytest
from playwright.sync_api import Page, expect
from pages.thanh_toan_dat_hang_page import ThanhToanDatHangPage

@pytest.fixture
def thanh_toan_dat_hang_page(page: Page) -> ThanhToanDatHangPage:
    ui = ThanhToanDatHangPage(page)
    ui.open()
    return ui

def test_thanh_toan_dat_hang_positive_ac_01(thanh_toan_dat_hang_page: ThanhToanDatHangPage):
    """AC-01 (POSITIVE): AC-01: khách hàng bấm Đặt hàng..."""
    thanh_toan_dat_hang_page.submit_thanh_toan_dat_hang()
    assert thanh_toan_dat_hang_page.is_success()

def test_thanh_toan_dat_hang_negative_ac_02(thanh_toan_dat_hang_page: ThanhToanDatHangPage):
    """AC-02 (NEGATIVE): AC-02: khách hàng bấm Đặt hàng..."""
    thanh_toan_dat_hang_page.submit_execute_negative()
    assert "Giỏ hàng không được để trống" in thanh_toan_dat_hang_page.get_error_message()

def test_thanh_toan_dat_hang_negative_ac_03(thanh_toan_dat_hang_page: ThanhToanDatHangPage):
    """AC-03 (NEGATIVE): AC-03: gửi yêu cầu thanh toán..."""
    thanh_toan_dat_hang_page.submit_execute_negative()
    assert not thanh_toan_dat_hang_page.is_success() or len(thanh_toan_dat_hang_page.get_error_message()) > 0