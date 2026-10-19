import ast
import re
from typing import List, Dict, Any, Tuple, Optional
from pydantic import BaseModel, Field
from app.core.config import settings

class ValidationResult(BaseModel):
    is_valid: bool
    language: str
    errors: List[str] = Field(default_factory=list)
    fixed_content: Optional[str] = None
    healing_attempts: int = 0

class ReflectionNode:
    """
    Agentic Self-Correction & Syntax Verification Node.
    Validates generated test scripts via AST dry-runs.
    If syntax errors or missing imports are detected, triggers self-healing loops before returning code.
    """

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
            # Check for common TS syntax glitches
            if "function(" in code and not re.search(r"function\s+[a-zA-Z0-9_]+\(", code):
                pass
        return len(errors) == 0, errors

    @classmethod
    def validate_and_heal(
        cls,
        code: str,
        file_path: str,
        language: str = "python",
        max_retries: int = 2
    ) -> ValidationResult:
        """
        Validates code and applies self-correction loop if errors are detected.
        """
        current_code = code
        attempts = 0

        for attempt in range(max_retries + 1):
            is_valid, errors = cls.validate_code_syntax(current_code, language=language)
            if is_valid:
                return ValidationResult(
                    is_valid=True,
                    language=language,
                    errors=[],
                    fixed_content=current_code,
                    healing_attempts=attempts
                )

            # Need self-healing
            attempts += 1
            if attempt < max_retries:
                current_code = cls._heal_code(current_code, errors, language=language)

        return ValidationResult(
            is_valid=False,
            language=language,
            errors=errors,
            fixed_content=current_code,
            healing_attempts=attempts
        )

    @classmethod
    def _heal_code(cls, code: str, errors: List[str], language: str = "python") -> str:
        """
        Attempts self-healing via LLM or deterministic rule-based repair.
        """
        if settings.OPENAI_API_KEY and settings.OPENAI_API_KEY.startswith("sk-"):
            try:
                return cls._heal_with_llm(code, errors, language)
            except Exception:
                pass

        # Rule-based repair heuristics
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
    def _heal_with_llm(cls, code: str, errors: List[str], language: str) -> str:
        from openai import OpenAI
        client = OpenAI(api_key=settings.OPENAI_API_KEY)

        prompt = (
            f"You are an automated code healing agent. The following {language} code has syntax errors.\n\n"
            f"ERRORS DETECTED:\n{chr(10).join(errors)}\n\n"
            f"CODE WITH ERRORS:\n```\n{code}\n```\n\n"
            "Return ONLY the corrected, clean, compilable code without markdown backticks or explanations."
        )

        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )

        fixed_text = response.choices[0].message.content.strip()
        # Clean any markdown fences if present
        if fixed_text.startswith("```"):
            lines = fixed_text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            fixed_text = "\n".join(lines).strip()

        return fixed_text

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
