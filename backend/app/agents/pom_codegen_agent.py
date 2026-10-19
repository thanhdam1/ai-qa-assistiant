import re
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
        slug = re.sub(r"[^a-zA-Z0-9_]+", "_", feature_name.lower()).strip("_")
        class_name = "".join(word.capitalize() for word in slug.split("_")) + "Page"

        # 1. Base Page
        base_page_code = cls._generate_base_page(language=language)
        base_path = "pages/base_page.py" if language == "python" else "pages/BasePage.ts"

        # 2. Feature Page Object
        feature_page_code = cls._generate_feature_page(slug, class_name, test_suite, language=language)
        feature_path = f"pages/{slug}_page.py" if language == "python" else f"pages/{class_name}.ts"

        # 3. Test Spec
        test_spec_code = cls._generate_test_spec(slug, class_name, test_suite, language=language)
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
    def _generate_feature_page(cls, slug: str, class_name: str, test_suite: Optional[TestSuite], language: str = "python") -> str:
        if language == "python":
            return f'''"""
{class_name}: Page Object Model representing the {slug.replace('_', ' ').title()} UI interface.
Maintains resilient locators and business interaction actions.
"""
from pages.base_page import BasePage

class {class_name}(BasePage):
    # Locators (Prefers data-testid, falls back to semantic CSS/ID)
    INPUT_PRIMARY = "[data-testid='input-primary'], #primary-input, input[name='primary']"
    INPUT_SECONDARY = "[data-testid='input-secondary'], #secondary-input, input[name='secondary']"
    BUTTON_SUBMIT = "[data-testid='btn-submit'], button[type='submit'], #btn-submit"
    MESSAGE_SUCCESS = "[data-testid='msg-success'], .alert-success"
    MESSAGE_ERROR = "[data-testid='msg-error'], .alert-danger, .error-message"

    def __init__(self, page):
        super().__init__(page)
        self.url = "/{slug}"

    def open(self) -> None:
        self.navigate(self.url)

    def submit_form(self, primary_val: str, secondary_val: str) -> None:
        self.fill_input(self.INPUT_PRIMARY, primary_val)
        self.fill_input(self.INPUT_SECONDARY, secondary_val)
        self.click_element(self.BUTTON_SUBMIT)

    def get_error_alert(self) -> str:
        return self.get_text_content(self.MESSAGE_ERROR)

    def get_success_alert(self) -> str:
        return self.get_text_content(self.MESSAGE_SUCCESS)
'''
        else:
            return f'''import {{ Page }} from '@playwright/test';
import {{ BasePage }} from './BasePage';

export class {class_name} extends BasePage {{
    readonly primaryInput = "[data-testid='input-primary']";
    readonly secondaryInput = "[data-testid='input-secondary']";
    readonly submitBtn = "[data-testid='btn-submit']";
    readonly errorAlert = "[data-testid='msg-error']";

    constructor(page: Page) {{
        super(page);
    }}

    async submitForm(val1: string, val2: string): Promise<void> {{
        await this.fillInput(this.primaryInput, val1);
        await this.fillInput(this.secondaryInput, val2);
        await this.clickElement(this.submitBtn);
    }}
}}
'''

    @classmethod
    def _generate_test_spec(cls, slug: str, class_name: str, test_suite: Optional[TestSuite], language: str = "python") -> str:
        if language == "python":
            code = f'''"""
Test Suite for {slug.replace('_', ' ').title()}: Executes automated tests against {class_name}.
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
    """TC-001: Verify valid form submission (Happy Path)"""
    {slug}_page.submit_form("valid_user@example.com", "ValidSecret123!")
    assert {slug}_page.is_visible({class_name}.MESSAGE_SUCCESS)

def test_boundary_empty_values({slug}_page: {class_name}):
    """TC-002: Verify boundary check on empty inputs"""
    {slug}_page.submit_form("", "")
    assert {slug}_page.is_visible({class_name}.MESSAGE_ERROR)

def test_negative_invalid_input({slug}_page: {class_name}):
    """TC-003: Verify rejection of invalid credentials"""
    {slug}_page.submit_form("invalid_format", "wrong_pass")
    error_msg = {slug}_page.get_error_alert()
    assert len(error_msg) > 0
'''
            return code
        else:
            return f'''import {{ test, expect }} from '@playwright/test';
import {{ {class_name} }} from '../pages/{class_name}';

test.describe('{class_name} Automation Suite', () => {{
    test('Positive Happy Path Submission', async ({{ page }}) => {{
        const ui = new {class_name}(page);
        await ui.navigate('/{slug}');
        await ui.submitForm('test@example.com', 'Secret123!');
        await expect(page.locator(ui.errorAlert)).not.toBeVisible();
    }});
}});
'''
