import pytest
from app.core.masking import DataMasker
from app.core.llm_client import LLMClient
from app.parsers.prd_parser import PRDParser
from app.parsers.ast_parser import ASTParser

def test_data_masker_secrets():
    raw_text = (
        'const apiKey = "sk-proj-9999999999999999999999999999999999999999";\n'
        'const dbUrl = "postgres://admin:superSecretPass123@db.internal:5432/production_db";\n'
        'const bearer = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c";\n'
        'let password = "myHiddenPassword!";'
    )
    
    assert not DataMasker.is_clean(raw_text)
    
    masked, redactions = DataMasker.mask_text(raw_text)
    
    assert "[REDACTED_API_KEY]" in masked
    assert "superSecretPass123" not in masked
    assert "[REDACTED_PASSWORD]" in masked
    assert "[REDACTED_JWT_TOKEN]" in masked or "Bearer [REDACTED_TOKEN]" in masked
    assert len(redactions) >= 3

def test_prd_parser_with_masking():
    prd_with_secret = (
        "# Secure Payment Feature\n\n"
        "## US-01: Process Card\n"
        "As a Customer, I want to pay with card, so that I can buy goods.\n"
        "- AC: Given an API key sk-proj-1234567890123456789012345678901234 when request arrives then verify credentials.\n"
    )
    
    parsed = PRDParser.parse_markdown(prd_with_secret)
    ac_desc = parsed.user_stories[0].acceptance_criteria[0].description
    assert "sk-proj-" not in ac_desc
    assert "[REDACTED_API_KEY]" in ac_desc

def test_ast_parser_with_masking():
    code_with_pass = (
        "class DatabaseConfig:\n"
        "    def get_connection(self):\n"
        '        password = "ConfidentialServerPass123"\n'
        "        return password\n"
    )
    
    chunks = ASTParser.parse_code(code_with_pass, "config.py", "python")
    assert len(chunks) > 0
    assert "ConfidentialServerPass123" not in chunks[0].content
    assert "[REDACTED_PASSWORD]" in chunks[0].content

def test_llm_client_fallback():
    # Calling generate without valid API keys should return None and not crash
    result = LLMClient.generate("Test prompt with sk-proj-1111111111111111111111111111111111111111")
    # In test environment with no OpenAI key or fake key, returns None or mock
    assert result is None or isinstance(result, str)
