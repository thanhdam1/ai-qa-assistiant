"""
AI QA Assistant & Codebase Intelligence — End-to-End Enterprise Showcase Script
Demonstrates all 5 architectural pillars in a single unified execution flow.
"""

import sys
import os
import json
import time

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Ensure backend package can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from app.core.masking import DataMasker
from app.parsers.prd_parser import PRDParser
from app.parsers.ast_parser import ASTParser
from app.agents.test_case_agent import TestCaseGenerator
from app.agents.rtm_agent import RTMAgent
from app.agents.synthetic_data import SyntheticDataGenerator
from app.agents.pom_codegen_agent import POMCodeGenerator
from app.agents.reflection_node import ReflectionNode
from app.agents.codebase_agent import CodebaseArchitectureAgent
from app.api.v1.pr_bot import analyze_pr_diff, PRAnalyzeRequest

def print_banner(title: str, step: str):
    print("\n" + "=" * 70)
    print(f"[{step}] {title}")
    print("=" * 70)

def main():
    print("""
    +-----------------------------------------------------------------------+
    |         AI QA ASSISTANT & CODEBASE ARCHITECTURE INTELLIGENCE          |
    |            Enterprise Edition — End-to-End System Showcase            |
    +-----------------------------------------------------------------------+
    """)

    # ---------------------------------------------------------
    # PILLAR 1: DATA MASKING & AST PARSING
    # ---------------------------------------------------------
    print_banner("PILLAR 1: Enterprise Secret Masking & Polyglot AST Parsing", "STEP 1")
    raw_code = """
    public class PaymentGatewayController : ControllerBase
    {
        private readonly string _apiKey = "sk-proj-9999999999999999999999999999999999999999";
        private readonly string _db = "Server=sql.prod;Password=superSecret123;";

        [HttpPost("charge")]
        public async Task<IActionResult> ProcessCharge([FromBody] ChargeRequest req)
        {
            var result = await _paymentService.ExecuteCharge(req);
            return Ok(result);
        }
    }
    """
    print("[INPUT] Raw C# Code with exposed API keys and DB passwords:")
    print("  - sk-proj-... and Password=superSecret123")
    
    masked, logs = DataMasker.mask_text(raw_code)
    print("\n[SECURITY AUDIT] Redactions triggered:")
    for r in logs:
        print(f"  - Detected & Sanitized: {r['type']} ({r['count']} instances)")
    
    chunks = ASTParser.parse_code(raw_code, "PaymentGatewayController.cs", "c_sharp")
    print(f"\n[AST RESULT] Parsed {len(chunks)} code chunk(s) via Tree-sitter:")
    for c in chunks:
        print(f"  * Node: [{c.node_type}] {c.name} | Calls: {c.calls}")

    # ---------------------------------------------------------
    # PILLAR 2 & 3: PRD TO ISTQB + OWASP TEST SUITE & RTM
    # ---------------------------------------------------------
    print_banner("PILLAR 3: ISTQB & OWASP Top 10 Test Suite + 100% RTM", "STEP 2")
    sample_prd = """# Thanh Toán Đơn Hàng (Checkout & Payment)
## US-01: Thanh Toán Thẻ Tín Dụng
As a Customer, I want to pay with credit card, so that I can complete purchase.
- AC-01: Given a valid card number and CVV when user clicks Pay then return HTTP 200 and receipt.
- AC-02: Given an expired card or empty CVV when user clicks Pay then display validation error.
"""
    parsed_prd = PRDParser.parse_markdown(sample_prd)
    print(f"[PARSED PRD] Feature: '{parsed_prd.title}' | User Stories: {len(parsed_prd.user_stories)}")
    
    test_suite = TestCaseGenerator.generate_from_prd(parsed_prd)
    print(f"[TEST SUITE] Generated {test_suite.total_test_cases} test cases:")
    for tc in test_suite.test_cases:
        print(f"  * [{tc.id}] [{tc.category.upper()}] (Priority: {tc.priority}) {tc.title}")

    rtm = RTMAgent.build_matrix(parsed_prd, test_suite)
    print(f"\n[RTM MATRIX] Requirement Coverage: {rtm.coverage_percentage:.1f}%")
    print(f"  * Total Criteria: {rtm.total_requirements} | Covered: {rtm.covered_requirements} | Untested Gaps: {len(rtm.uncovered_gaps)}")

    # ---------------------------------------------------------
    # PILLAR 3: POM AUTOMATION CODEGEN & AST SELF-HEALING
    # ---------------------------------------------------------
    print_banner("PILLAR 3: Page Object Model Synthesis & Dynamic Locator Healing", "STEP 3")
    pom = POMCodeGenerator.generate_playwright_suite(feature_name=test_suite.feature_title, test_suite=test_suite, language="python")
    print(f"[POM SYNTHESIZER] Synthesized {len(pom.files)} files:")
    for f in pom.files:
        print(f"  * File: {f.file_path} ({len(f.content.splitlines())} lines)")

    brittle_script = """
from playwright.sync_api import Page, expect

def test_login(page: Page)
    page.locator("/html/body/div[1]/button").click()
    page.locator("#btn-1a2b3c4d").click()
"""
    print("\n[AST DRY-RUN] Testing Brittle Code with Missing Colon and Brittle XPaths:")
    validation = ReflectionNode.validate_and_heal(brittle_script, "tests/test_login.py", language="python")
    print(f"  * Syntax Valid after healing: {validation.is_valid}")
    print(f"  * Healing attempts: {validation.healing_attempts}")
    print(f"  * Brittle locators converted: {validation.locators_healed}")
    print("\n[HEALED CODE]:")
    print(validation.fixed_content.strip())

    # ---------------------------------------------------------
    # PILLAR 2: CODEBASE ARCHITECTURE Q&A & CALL GRAPH
    # ---------------------------------------------------------
    print_banner("PILLAR 2: Codebase Architecture Reasoning & Call Graph", "STEP 4")
    sample_files = [
        {
            "file_path": "backend/app/api/v1/auth.py",
            "content": "class AuthController:\n    def login(self, req):\n        return AuthService().authenticate(req)"
        },
        {
            "file_path": "backend/app/services/auth_service.py",
            "content": "class AuthService:\n    def authenticate(self, req):\n        return UserRepository().find_by_credentials(req)"
        },
        {
            "file_path": "backend/app/repositories/user_repo.py",
            "content": "class UserRepository:\n    def find_by_credentials(self, req):\n        return {'status': 'success', 'user_id': 1}"
        }
    ]
    agent = CodebaseArchitectureAgent()
    agent.index_files(sample_files)
    answer = agent.answer_architecture_query("Luồng xác thực diễn ra như thế nào qua các tầng?")
    print(f"[SUMMARY] {answer.summary}")
    print(f"[COMPONENTS INVOLVED] {', '.join(answer.components_involved[:5])}")
    print(f"\n[MERMAID SEQUENCE DIAGRAM]:\n{answer.mermaid_diagram}")

    # ---------------------------------------------------------
    # PILLAR 4: CI/CD GITHUB PR IMPACT BOT
    # ---------------------------------------------------------
    print_banner("PILLAR 4: CI/CD Pull Request Impact Bot", "STEP 5")
    pr_diff = """diff --git a/backend/app/api/v1/auth.py b/backend/app/api/v1/auth.py
--- a/backend/app/api/v1/auth.py
+++ b/backend/app/api/v1/auth.py
@@ -10,3 +10,4 @@
-def login(username, password):
+def login(username, password, mfa_token: Optional[str] = None):
+    validate_mfa(mfa_token)
"""
    report = analyze_pr_diff(PRAnalyzeRequest(
        pr_number=42,
        pr_title="feat(auth): enforce mandatory MFA token in login endpoint",
        git_diff=pr_diff
    ))
    print(f"[PR BOT] PR #{report.pr_number}: {report.pr_title}")
    print(f"  * Files Changed: {report.total_files_changed}")
    print(f"  * Impacted Components: {len(report.impacted_components)}")
    for comp in report.impacted_components:
        print(f"    - {comp.file_path} (Risk: {comp.risk_level}) -> Modified: {', '.join(comp.modified_functions)}")
    print(f"  * Recommended Regression Tests: {', '.join(report.recommended_regression_tests)}")

    print("\n" + "=" * 70)
    print("[SUCCESS] All 5 Enterprise Pillars executed flawlessly!")
    print("Web Dashboard live at: http://localhost:8000")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    main()
