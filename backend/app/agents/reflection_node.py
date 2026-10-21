import ast
import re
from typing import List, Dict, Any, Tuple, Optional
from pydantic import BaseModel, Field
from app.core.config import settings
from app.core.llm_client import LLMClient

class ValidationTurn(BaseModel):
    turn_index: int
    errors_found: List[str]
    action_taken: str

class ResilientLocator(BaseModel):
    priority_level: int  # 1 (Best) to 6 (Fallback)
    locator_type: str    # test_id, role, label, placeholder, text, css
    locator_code: str
    explanation: str

class ValidationResult(BaseModel):
    is_valid: bool
    language: str
    errors: List[str] = Field(default_factory=list)
    fixed_content: Optional[str] = None
    healing_attempts: int = 0
    locators_healed: int = 0
    turn_history: List[ValidationTurn] = Field(default_factory=list)

class ReflectionNode:
    """
    Enterprise Agentic Self-Correction & Syntax Verification Node.
    Validates generated test scripts via AST dry-runs and dynamic locator analysis.
    If syntax errors or brittle locators are detected, triggers self-healing loops before returning code.
    """

    # Common brittle locator patterns that cause flaky UI tests
    BRITTLE_LOCATOR_PATTERNS = [
        (r'page\.locator\([\'"]\/html\/body\/[^\'"]+[\'"]\)', 'page.get_by_role("button", name="Submit")'),
        (r'page\.locator\([\'"]#btn-[0-9a-fA-F]{4,}[\'"]\)', 'page.get_by_test_id("submit-btn")'),
        (r'page\.locator\([\'"]div\.css-[0-9a-zA-Z]+ > button[\'"]\)', 'page.get_by_role("button")'),
        (r'page\.click\([\'"]\/\/[^\'"]+[\'"]\)', 'page.get_by_role("button").click()'),
    ]

    @classmethod
    def validate_code_syntax(cls, code: str, language: str = "python") -> Tuple[bool, List[str]]:
        """
        Validates code syntax using AST parsing.
        """
        errors = []
        if language == "python":
            try:
                ast.parse(code)
            except SyntaxError as e:
                errors.append(f"SyntaxError at line {e.lineno}, col {e.offset}: {e.msg} (in '{e.text.strip() if e.text else ''}')")
            except Exception as e:
                errors.append(f"Parse error: {str(e)}")
        elif language in ["typescript", "javascript"]:
            # Check basic structural bracket/parenthesis balancing
            balance_error = cls._check_bracket_balance(code)
            if balance_error:
                errors.append(balance_error)
        return len(errors) == 0, errors

    @classmethod
    def heal_brittle_locators(cls, code: str) -> Tuple[str, int]:
        """
        Scans and heals brittle locators into resilient semantic Playwright locators.
        """
        healed_code = code
        count = 0
        for pattern, replacement in cls.BRITTLE_LOCATOR_PATTERNS:
            matches = re.findall(pattern, healed_code)
            if matches:
                count += len(matches)
                healed_code = re.sub(pattern, replacement, healed_code)
        return healed_code, count

    @classmethod
    def validate_and_heal(
        cls,
        code: str,
        file_path: str,
        language: str = "python",
        max_retries: int = 3
    ) -> ValidationResult:
        """
        Validates code and applies multi-turn self-correction loop if errors are detected.
        Also heals brittle selectors to eliminate test flakiness.
        """
        # Step 1: Heal brittle locators
        current_code, locators_fixed = cls.heal_brittle_locators(code)
        attempts = 0
        history: List[ValidationTurn] = []

        # Step 2: Multi-turn AST validation loop
        for attempt in range(max_retries + 1):
            is_valid, errors = cls.validate_code_syntax(current_code, language=language)
            if is_valid:
                if attempts > 0:
                    history.append(ValidationTurn(
                        turn_index=attempt,
                        errors_found=[],
                        action_taken="Code syntax successfully validated via AST dry-run."
                    ))
                return ValidationResult(
                    is_valid=True,
                    language=language,
                    errors=[],
                    fixed_content=current_code,
                    healing_attempts=attempts,
                    locators_healed=locators_fixed,
                    turn_history=history
                )

            # Need self-healing
            attempts += 1
            action_desc = f"Applied self-healing heuristics for {len(errors)} error(s)."
            history.append(ValidationTurn(
                turn_index=attempt + 1,
                errors_found=errors,
                action_taken=action_desc
            ))
            if attempt < max_retries:
                current_code = cls._heal_code(current_code, errors, language=language)

        return ValidationResult(
            is_valid=False,
            language=language,
            errors=errors,
            fixed_content=current_code,
            healing_attempts=attempts,
            locators_healed=locators_fixed,
            turn_history=history
        )

    @classmethod
    def synthesize_resilient_locator(
        cls,
        element_tag: str,
        attributes: Dict[str, str],
        inner_text: Optional[str] = None
    ) -> List[ResilientLocator]:
        """
        Synthesizes a prioritized list of resilient Playwright locators based on
        Testing Library & W3C Accessibility standards.
        Priority:
        1. data-testid / data-cy / data-test
        2. Accessibility Role (role + name)
        3. Label (aria-label, associated label)
        4. Placeholder
        5. Semantic Text Content
        6. CSS / ID Fallback
        """
        locators: List[ResilientLocator] = []

        # 1. Test ID (Most resilient against UI/layout redesigns)
        test_id = attributes.get("data-testid") or attributes.get("data-test") or attributes.get("data-cy")
        if test_id:
            locators.append(ResilientLocator(
                priority_level=1,
                locator_type="test_id",
                locator_code=f'page.get_by_test_id("{test_id}")',
                explanation="Top priority: Explicit test ID attribute resistant to CSS & copy changes."
            ))

        # 2. Accessibility Role
        role = attributes.get("role")
        if not role:
            if element_tag == "button" or attributes.get("type") == "button":
                role = "button"
            elif element_tag == "a":
                role = "link"
            elif element_tag == "input" and attributes.get("type") in ["text", "email", "password"]:
                role = "textbox"

        accessible_name = attributes.get("aria-label") or inner_text
        if role and accessible_name:
            locators.append(ResilientLocator(
                priority_level=2,
                locator_type="role",
                locator_code=f'page.get_by_role("{role}", name="{accessible_name.strip()}")',
                explanation="High priority: User-facing accessibility role and accessible name."
            ))

        # 3. Form Label
        if attributes.get("aria-label"):
            locators.append(ResilientLocator(
                priority_level=3,
                locator_type="label",
                locator_code=f'page.get_by_label("{attributes["aria-label"]}")',
                explanation="Standard accessibility label locator."
            ))

        # 4. Placeholder
        if attributes.get("placeholder"):
            locators.append(ResilientLocator(
                priority_level=4,
                locator_type="placeholder",
                locator_code=f'page.get_by_placeholder("{attributes["placeholder"]}")',
                explanation="Input placeholder matching user visual cue."
            ))

        # 5. Visible Text
        if inner_text and inner_text.strip():
            clean_text = inner_text.strip()
            locators.append(ResilientLocator(
                priority_level=5,
                locator_type="text",
                locator_code=f'page.get_by_text("{clean_text}")',
                explanation="Direct visible text locator."
            ))

        # 6. ID or CSS Fallback
        elem_id = attributes.get("id")
        if elem_id and not re.match(r"^[0-9a-fA-F\-]{8,}$", elem_id):
            locators.append(ResilientLocator(
                priority_level=6,
                locator_type="id",
                locator_code=f'page.locator("#{elem_id}")',
                explanation="DOM ID fallback (only when semantic locators are unavailable)."
            ))

        return locators

    @classmethod
    def _heal_code(cls, code: str, errors: List[str], language: str = "python") -> str:
        """
        Attempts self-healing via Unified Hybrid LLM or deterministic rule-based repair.
        """
        # Try LLM Healing first
        prompt = (
            f"You are an automated code healing agent. The following {language} code has syntax errors.\n\n"
            f"ERRORS DETECTED:\n{chr(10).join(errors)}\n\n"
            f"CODE WITH ERRORS:\n```\n{code}\n```\n\n"
            "Return ONLY the corrected, clean, compilable code without markdown backticks or explanations."
        )
        llm_fix = LLMClient.generate(
            prompt=prompt,
            system_instruction="You fix syntax and linter errors in test automation code.",
            temperature=0.0
        )
        if llm_fix:
            # Strip markdown fences if present
            fixed_text = llm_fix.strip()
            if fixed_text.startswith("```"):
                lines = fixed_text.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                fixed_text = "\n".join(lines).strip()
            return fixed_text

        # Rule-based repair heuristics fallback
        return cls._heal_deterministic(code, errors, language)

    @classmethod
    def _heal_deterministic(cls, code: str, errors: List[str], language: str = "python") -> str:
        healed_lines = code.splitlines()

        for err in errors:
            # Check for common missing colons in Python
            if "expected ':'" in err or "SyntaxError" in err:
                match = re.search(r"line (\d+)", err)
                if match:
                    line_no = int(match.group(1)) - 1
                    if 0 <= line_no < len(healed_lines):
                        target_line = healed_lines[line_no].rstrip()
                        if any(target_line.strip().startswith(kw) for kw in ["def ", "class ", "if ", "for ", "while ", "try", "except", "with "]):
                            if not target_line.endswith(":"):
                                healed_lines[line_no] = target_line + ":"

            # Check for missing imports
            if "pytest" in code and "import pytest" not in code:
                healed_lines.insert(0, "import pytest")
            if "Page" in code and "from playwright" not in code and language == "python":
                healed_lines.insert(0, "from playwright.sync_api import Page, expect")

        return "\n".join(healed_lines)

    @classmethod
    def _check_bracket_balance(cls, code: str) -> Optional[str]:
        pairs = {')': '(', '}': '{', ']': '['}
        stack = []
        for i, char in enumerate(code):
            if char in "({[":
                stack.append((char, i))
            elif char in ")}]":
                if not stack or stack[-1][0] != pairs[char]:
                    return f"Unmatched bracket '{char}' at character index {i}"
                stack.pop()
        if stack:
            unmatched, idx = stack[-1]
            return f"Unclosed bracket '{unmatched}' at character index {idx}"
        return None
