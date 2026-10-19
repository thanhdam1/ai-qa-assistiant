import re
from typing import Tuple, List, Dict, Any

class DataMasker:
    """
    Enterprise Security Data Masker & Secret Redaction Engine.
    Detects and sanitizes PII, API Keys, Passwords, Connection Strings, and JWTs
    before text is ingested into Vector DBs or transmitted to Cloud/Local LLMs.
    """

    PATTERNS: List[Tuple[str, str, str]] = [
        # (Pattern Name, Regex, Replacement Tag)
        (
            "JWT_TOKEN",
            r"eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}",
            "[REDACTED_JWT_TOKEN]",
        ),
        (
            "OPENAI_KEY",
            r"sk-(?:proj-|live-)?[a-zA-Z0-9_-]{32,}",
            "[REDACTED_API_KEY]",
        ),
        (
            "GENERIC_SECRET_KEY",
            r"(?i)(api[_-]?key|secret[_-]?key|auth[_-]?token|access[_-]?token|client[_-]?secret)\s*[:=]\s*['\"]?([a-zA-Z0-9_\-\.]{16,})['\"]?",
            r"\1: [REDACTED_SECRET]",
        ),
        (
            "PASSWORD_ASSIGNMENT",
            r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]([^'\"]{4,})['\"]",
            r"\1: [REDACTED_PASSWORD]",
        ),
        (
            "DATABASE_URI",
            r"(?i)(postgres(?:ql)?|mongodb(?:\+srv)?|mysql|redis)://(?:[^:]+):([^@]+)@([a-zA-Z0-9\.-]+)(?::\d+)?(?:/[a-zA-Z0-9_\-\?]*)?",
            r"\1://[REDACTED_USER]:[REDACTED_PWD]@\3/[REDACTED_DB]",
        ),
        (
            "DOTNET_CONN_STRING",
            r"(?i)(Password|Pwd)=([^;]+);",
            r"\1=[REDACTED_PASSWORD];",
        ),
        (
            "PRIVATE_KEY_BLOCK",
            r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA |EC )?PRIVATE KEY-----",
            "[REDACTED_PRIVATE_KEY]",
        ),
        (
            "BEARER_AUTH_HEADER",
            r"(?i)bearer\s+[a-zA-Z0-9_\-\.]{24,}",
            "Bearer [REDACTED_TOKEN]",
        ),
        (
            "CREDIT_CARD",
            r"\b(?:\d{4}[ -]?){3}\d{4}\b",
            "[REDACTED_CREDIT_CARD]",
        ),
    ]

    @classmethod
    def mask_text(cls, text: str) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Masks all sensitive patterns in the input string.
        Returns the sanitized string and a log of redactions made.
        """
        if not text:
            return text, []

        sanitized = text
        redactions_log = []

        for name, pattern, replacement in cls.PATTERNS:
            matches = list(re.finditer(pattern, sanitized))
            if matches:
                count = len(matches)
                redactions_log.append({
                    "type": name,
                    "count": count
                })
                sanitized = re.sub(pattern, replacement, sanitized)

        return sanitized, redactions_log

    @classmethod
    def is_clean(cls, text: str) -> bool:
        """Checks whether the text contains any unmasked sensitive secrets."""
        if not text:
            return True
        for _, pattern, _ in cls.PATTERNS:
            if re.search(pattern, text):
                return False
        return True
