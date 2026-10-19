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
    assert "def test_positive_submission" in test_file.content
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
