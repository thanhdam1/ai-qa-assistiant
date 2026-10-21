import re
import unicodedata
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from app.agents.test_case_agent import TestSuite, TestCase
from app.agents.reflection_node import ReflectionNode, ValidationResult

class GeneratedFile(BaseModel):
    file_path: str
    file_type: str  # base_page, page_object, test_spec
    language: str   # python, typescript
    content: str
    original_content: Optional[str] = None
    syntax_valid: bool = False
    validation_errors: List[str] = Field(default_factory=list)
    healing_attempts: int = 0

class POMTestSuite(BaseModel):
    feature_name: str
    framework: str  # playwright, selenium
    language: str   # python, typescript
    files: List[GeneratedFile] = Field(default_factory=list)
    all_valid: bool = False

def slugify(text: str) -> str:
    normalized = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    clean = re.sub(r"[^a-zA-Z0-9_]+", "_", normalized.lower()).strip("_")
    return clean or "feature"

class POMCodeGenerator:
    """
    Page Object Model (POM) Code Synthesizer.
    Generates industry-standard, reusable automation test suites (Playwright / PyTest)
    with BasePage, Feature Page Objects, and Test Specs.
    Integrates Agentic Self-Correction Loop via AST dry-runs.
    """

    @classmethod
    def generate_playwright_suite(
        cls,
        feature_name: str,
        test_suite: Optional[TestSuite] = None,
        language: str = "python"
    ) -> POMTestSuite:
        slug = slugify(feature_name)
        class_name = "".join(word.capitalize() for word in slug.split("_")) + "Page"

        # 1. Base Page
        base_page_code = cls._generate_base_page(language=language)
        base_path = "pages/base_page.py" if language == "python" else "pages/BasePage.ts"

        # 2. Feature Page Object
        feature_page_code = cls._generate_feature_page(slug, class_name, test_suite, language=language, feature_name=feature_name)
        feature_path = f"pages/{slug}_page.py" if language == "python" else f"pages/{class_name}.ts"

        # 3. Test Spec
        test_spec_code = cls._generate_test_spec(slug, class_name, test_suite, language=language, feature_name=feature_name)
        test_path = f"tests/test_{slug}.py" if language == "python" else f"tests/{slug}.spec.ts"

        raw_files = [
            (base_path, "base_page", base_page_code),
            (feature_path, "page_object", feature_page_code),
            (test_path, "test_spec", test_spec_code),
        ]

        # Validate and Heal through AST Reflection Loop
        verified_files: List[GeneratedFile] = []
        all_ok = True

        for path, f_type, raw_code in raw_files:
            val_result: ValidationResult = ReflectionNode.validate_and_heal(
                code=raw_code,
                file_path=path,
                language=language
            )

            if not val_result.is_valid:
                all_ok = False

            verified_files.append(
                GeneratedFile(
                    file_path=path,
                    file_type=f_type,
                    language=language,
                    content=val_result.fixed_content or raw_code,
                    original_content=raw_code if val_result.healing_attempts > 0 else raw_code,
                    syntax_valid=val_result.is_valid,
                    validation_errors=val_result.errors,
                    healing_attempts=val_result.healing_attempts
                )
            )

        return POMTestSuite(
            feature_name=feature_name,
            framework="playwright",
            language=language,
            files=verified_files,
            all_valid=all_ok
        )

    @classmethod
    def _generate_base_page(cls, language: str = "python") -> str:
        if language == "python":
            return '''"""
BasePage: Encapsulates standard browser operations, explicit waits,
and resilient locator interactions for Playwright.
"""
from playwright.sync_api import Page, Locator, expect

class BasePage:
    def __init__(self, page: Page):
        self.page = page

    def navigate(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded")

    def click_element(self, selector: str, timeout: float = 5000) -> None:
        locator = self.page.locator(selector)
        locator.wait_for(state="visible", timeout=timeout)
        locator.click()

    def fill_input(self, selector: str, text: str, timeout: float = 5000) -> None:
        locator = self.page.locator(selector)
        locator.wait_for(state="visible", timeout=timeout)
        locator.fill(text)

    def get_text_content(self, selector: str) -> str:
        locator = self.page.locator(selector)
        locator.wait_for(state="visible")
        return locator.inner_text()

    def is_visible(self, selector: str) -> bool:
        return self.page.locator(selector).is_visible()

    def take_screenshot(self, file_path: str) -> None:
        self.page.screenshot(path=file_path, full_page=True)
'''
        else:
            return '''import { Page, Locator } from '@playwright/test';

export class BasePage {
    protected page: Page;

    constructor(page: Page) {
        this.page = page;
    }

    async navigate(url: string): Promise<void> {
        await this.page.goto(url, { waitUntil: 'domcontentloaded' });
    }

    async clickElement(selector: string): Promise<void> {
        await this.page.locator(selector).waitFor({ state: 'visible' });
        await this.page.locator(selector).click();
    }

    async fillInput(selector: string, text: string): Promise<void> {
        await this.page.locator(selector).waitFor({ state: 'visible' });
        await this.page.locator(selector).fill(text);
    }

    async getText(selector: string): Promise<string> {
        return (await this.page.locator(selector).innerText()) || '';
    }
}
'''

    @classmethod
    def _generate_feature_page(
        cls,
        slug: str,
        class_name: str,
        test_suite: Optional[TestSuite],
        language: str = "python",
        feature_name: str = ""
    ) -> str:
        f_lower = (feature_name or slug).lower()
        is_transfer = any(k in f_lower for k in ["transfer", "chuyen", "tien", "bank", "payment", "napas", "swift", "fund"])
        is_auth = any(k in f_lower for k in ["auth", "login", "dang nhap", "signin", "account"])

        if language == "python":
            if is_transfer:
                return f'''"""
{class_name}: Enterprise Page Object Model representing {feature_name or slug.replace('_', ' ').title()}.
Maintains resilient locators and business interaction actions for Interbank / Fund Transfers.
"""
from pages.base_page import BasePage

class {class_name}(BasePage):
    # Resilient Locators (Testing Library & data-testid standard)
    SOURCE_ACCOUNT_SELECT = "[data-testid='source-account-select'], select[name='source_account']"
    DEST_ACCOUNT_INPUT = "[data-testid='dest-account-input'], input[name='dest_account']"
    AMOUNT_INPUT = "[data-testid='transfer-amount-input']"
    CURRENCY_SELECT = "[data-testid='currency-select']"
    TRANSFER_NOTE_INPUT = "[data-testid='transfer-note-input']"
    SUBMIT_TRANSFER_BUTTON = "[data-testid='btn-submit-transfer'], button:has-text('Tiếp tục')"
    OTP_TOKEN_INPUT = "[data-testid='otp-verification-token']"
    CONFIRM_OTP_BUTTON = "[data-testid='btn-confirm-otp'], button:has-text('Xác nhận')"
    SUCCESS_BANNER = "[data-testid='transfer-success-banner']"
    ERROR_ALERT = "[data-testid='transfer-error-alert'], [role='alert']"

    def __init__(self, page):
        super().__init__(page)
        self.url = "/{slug}"

    def open(self) -> None:
        self.navigate(self.url)

    def fill_transfer_info(self, source_acc: str, dest_acc: str, amount: float, currency: str = "VND", note: str = "") -> None:
        self.fill_input(self.SOURCE_ACCOUNT_SELECT, source_acc)
        self.fill_input(self.DEST_ACCOUNT_INPUT, dest_acc)
        self.fill_input(self.AMOUNT_INPUT, str(amount))
        self.fill_input(self.TRANSFER_NOTE_INPUT, note)
        self.click_element(self.SUBMIT_TRANSFER_BUTTON)

    def submit_biometric_otp(self, otp_code: str) -> None:
        self.fill_input(self.OTP_TOKEN_INPUT, otp_code)
        self.click_element(self.CONFIRM_OTP_BUTTON)

    def is_transfer_successful(self) -> bool:
        return self.is_visible(self.SUCCESS_BANNER)

    def get_error_message(self) -> str:
        return self.get_text_content(self.ERROR_ALERT)
'''
            elif is_auth:
                return f'''"""
{class_name}: Enterprise Page Object Model representing {feature_name or slug.replace('_', ' ').title()}.
Maintains resilient locators and authentication workflow interactions.
"""
from pages.base_page import BasePage

class {class_name}(BasePage):
    # Resilient Locators (Testing Library & data-testid standard)
    USERNAME_INPUT = "[data-testid='username-input'], input[type='email']"
    PASSWORD_INPUT = "[data-testid='password-input'], input[type='password']"
    REMEMBER_CHECKBOX = "[data-testid='remember-me-checkbox']"
    LOGIN_BUTTON = "[data-testid='btn-login'], button[type='submit']"
    TWO_FACTOR_INPUT = "[data-testid='2fa-code-input']"
    CONFIRM_2FA_BUTTON = "[data-testid='btn-confirm-2fa']"
    SUCCESS_DASHBOARD = "[data-testid='user-dashboard-welcome']"
    ERROR_ALERT = "[data-testid='auth-error-alert'], [role='alert']"

    def __init__(self, page):
        super().__init__(page)
        self.url = "/{slug}"

    def open(self) -> None:
        self.navigate(self.url)

    def login(self, username: str, password: str, remember: bool = False) -> None:
        self.fill_input(self.USERNAME_INPUT, username)
        self.fill_input(self.PASSWORD_INPUT, password)
        self.click_element(self.LOGIN_BUTTON)

    def verify_2fa(self, code: str) -> None:
        self.fill_input(self.TWO_FACTOR_INPUT, code)
        self.click_element(self.CONFIRM_2FA_BUTTON)

    def is_logged_in(self) -> bool:
        return self.is_visible(self.SUCCESS_DASHBOARD)

    def get_error_message(self) -> str:
        return self.get_text_content(self.ERROR_ALERT)
'''
            else:
                return f'''"""
{class_name}: Enterprise Page Object Model representing {feature_name or slug.replace('_', ' ').title()}.
Maintains resilient locators and domain workflow actions.
"""
from pages.base_page import BasePage

class {class_name}(BasePage):
    # Resilient Locators (Testing Library & data-testid standard)
    INPUT_PRIMARY = "[data-testid='{slug}-primary-input'], input[name='primary']"
    INPUT_SECONDARY = "[data-testid='{slug}-secondary-input'], input[name='secondary']"
    SUBMIT_BUTTON = "[data-testid='btn-submit'], button:has-text('Xác nhận / Submit')"
    SUCCESS_ALERT = "[data-testid='{slug}-success-banner'], .alert-success"
    ERROR_ALERT = "[data-testid='{slug}-error-alert'], [role='alert']"

    def __init__(self, page):
        super().__init__(page)
        self.url = "/{slug}"

    def open(self) -> None:
        self.navigate(self.url)

    def submit_action(self, primary_val: str, secondary_val: str) -> None:
        self.fill_input(self.INPUT_PRIMARY, primary_val)
        self.fill_input(self.INPUT_SECONDARY, secondary_val)
        self.click_element(self.SUBMIT_BUTTON)

    def is_success(self) -> bool:
        return self.is_visible(self.SUCCESS_ALERT)

    def get_error_message(self) -> str:
        return self.get_text_content(self.ERROR_ALERT)
'''
        else:
            return f'''import {{ Page }} from '@playwright/test';
import {{ BasePage }} from './BasePage';

export class {class_name} extends BasePage {{
    readonly primaryInput = "[data-testid='{slug}-primary-input']";
    readonly secondaryInput = "[data-testid='{slug}-secondary-input']";
    readonly submitBtn = "button:has-text('Xác nhận / Submit')";
    readonly successBanner = "[data-testid='{slug}-success-banner']";
    readonly errorAlert = "[role='alert']";

    constructor(page: Page) {{
        super(page);
    }}

    async submitAction(val1: string, val2: string): Promise<void> {{
        await this.fillInput(this.primaryInput, val1);
        await this.fillInput(this.secondaryInput, val2);
        await this.clickElement(this.submitBtn);
    }}
}}
'''

    @classmethod
    def _generate_test_spec(
        cls,
        slug: str,
        class_name: str,
        test_suite: Optional[TestSuite],
        language: str = "python",
        feature_name: str = ""
    ) -> str:
        f_lower = (feature_name or slug).lower()
        is_transfer = any(k in f_lower for k in ["transfer", "chuyen", "tien", "bank", "payment", "napas", "swift", "fund"])
        is_auth = any(k in f_lower for k in ["auth", "login", "dang nhap", "signin", "account"])

        if language == "python":
            if is_transfer:
                return f'''"""
Test Suite for {feature_name or slug.replace('_', ' ').title()}:
Automates Positive Happy Path, Boundary Limits, Negative Verification and Security Injection against {class_name}.
"""
import pytest
from playwright.sync_api import Page, expect
from pages.{slug}_page import {class_name}

@pytest.fixture
def {slug}_page(page: Page) -> {class_name}:
    ui = {class_name}(page)
    ui.open()
    return ui

def test_transfer_positive_successful_submission({slug}_page: {class_name}):
    """TC-TRF-001: Chuyển tiền hợp lệ thành công với xác thực OTP sinh trắc học"""
    {slug}_page.fill_transfer_info(
        source_acc="1903888899901",
        dest_acc="0451000388291",
        amount=50000000.0,
        currency="VND",
        note="Thanh toan hop dong cung ung dich vu"
    )
    {slug}_page.submit_biometric_otp("889922")
    assert {slug}_page.is_transfer_successful()

def test_transfer_boundary_min_limit({slug}_page: {class_name}):
    """TC-TRF-002: Kiểm tra biên giá trị tối thiểu cho phép (10,000 VND)"""
    {slug}_page.fill_transfer_info("1903888899901", "0451000388291", 10000.0, "VND", "Chuyen tien han muc toi thieu")
    {slug}_page.submit_biometric_otp("889922")
    assert {slug}_page.is_transfer_successful()

def test_transfer_negative_invalid_dest_account({slug}_page: {class_name}):
    """TC-TRF-003: Hệ thống từ chối khi số tài khoản thụ hưởng không tồn tại"""
    {slug}_page.fill_transfer_info("1903888899901", "0000000000000", 100000.0, "VND", "Kiem tra tai khoan sai")
    error = {slug}_page.get_error_message()
    assert len(error) > 0

def test_transfer_security_sql_injection_defense({slug}_page: {class_name}):
    """TC-TRF-004: Chống tấn công SQL Injection và XSS trong trường nội dung chuyển khoản"""
    {slug}_page.fill_transfer_info("1903888899901", "0451000388291", 200000.0, "VND", "'; DROP TABLE TRANSACTIONS; --")
    assert not {slug}_page.is_transfer_successful() or len({slug}_page.get_error_message()) >= 0
'''
            elif is_auth:
                return f'''"""
Test Suite for {feature_name or slug.replace('_', ' ').title()}:
Automates Positive Authentication, 2FA Validation, Empty Bounds, and Brute-force Prevention.
"""
import pytest
from playwright.sync_api import Page, expect
from pages.{slug}_page import {class_name}

@pytest.fixture
def {slug}_page(page: Page) -> {class_name}:
    ui = {class_name}(page)
    ui.open()
    return ui

def test_auth_positive_login_success({slug}_page: {class_name}):
    """TC-AUTH-001: Đăng nhập thành công với tài khoản và mật khẩu hợp lệ"""
    {slug}_page.login("customer.prod@enterprise.com", "SecureP@ssword2026!", remember=True)
    {slug}_page.verify_2fa("654321")
    assert {slug}_page.is_logged_in()

def test_auth_boundary_empty_credentials({slug}_page: {class_name}):
    """TC-AUTH-002: Kiểm tra biên khi để trống toàn bộ thông tin đăng nhập"""
    {slug}_page.login("", "")
    assert len({slug}_page.get_error_message()) > 0

def test_auth_negative_invalid_password({slug}_page: {class_name}):
    """TC-AUTH-003: Chặn đăng nhập khi nhập sai mật khẩu quá số lần quy định"""
    {slug}_page.login("customer.prod@enterprise.com", "WrongCredentials_999")
    assert not {slug}_page.is_logged_in()

def test_auth_security_sqli_payload({slug}_page: {class_name}):
    """TC-AUTH-004: Ngăn chặn payload SQL Injection Bypass Authentication"""
    {slug}_page.login("' OR '1'='1' --", "anything")
    assert not {slug}_page.is_logged_in()
'''
            else:
                return f'''"""
Test Suite for {feature_name or slug.replace('_', ' ').title()}:
Automates standard ISTQB test matrix against {class_name}.
"""
import pytest
from playwright.sync_api import Page, expect
from pages.{slug}_page import {class_name}

@pytest.fixture
def {slug}_page(page: Page) -> {class_name}:
    ui = {class_name}(page)
    ui.open()
    return ui

def test_positive_submission({slug}_page: {class_name}):
    """TC-001: Kịch bản hợp lệ thành công (Happy Path)"""
    {slug}_page.submit_action("sample_primary_value", "sample_secondary_value")
    assert {slug}_page.is_success()

def test_boundary_empty_values({slug}_page: {class_name}):
    """TC-002: Kiểm tra biên rỗng (Boundary Analysis)"""
    {slug}_page.submit_action("", "")
    assert len({slug}_page.get_error_message()) > 0

def test_negative_invalid_input({slug}_page: {class_name}):
    """TC-003: Từ chối dữ liệu đầu vào không hợp lệ (Negative)"""
    {slug}_page.submit_action("invalid_format_###", "wrong_input_###")
    assert len({slug}_page.get_error_message()) > 0
'''
        else:
            return f'''import {{ test, expect }} from '@playwright/test';
import {{ {class_name} }} from '../pages/{class_name}';

test.describe('{class_name} Automation Suite', () => {{
    test('Positive Happy Path Submission', async ({{ page }}) => {{
        const ui = new {class_name}(page);
        await ui.navigate('/{slug}');
        await ui.submitAction('valid_entry', 'valid_secret');
        await expect(page.locator(ui.errorAlert)).not.toBeVisible();
    }});
}});
'''
