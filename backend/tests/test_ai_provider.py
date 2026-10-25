from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError, RateLimitError

from app.config import Settings
from app.errors import AIProviderError
from app.schemas import RequirementReviewContent
from app.services.ai import GeminiProvider, OpenAIProvider


def config(**changes) -> Settings:
    defaults = {
        "database_url": "sqlite+pysqlite://",
        "openai_api_key": "test-key",
        "openai_model": "gpt-6-astra",
        "gemini_api_key": "gemini-test-key",
        "gemini_model": "gemini-3.5-flash-lite",
        "ai_max_retries": 2,
    }
    return Settings(_env_file=None, **(defaults | changes))


@pytest.mark.asyncio
async def test_missing_api_key_fails_before_network(review_content):
    provider = OpenAIProvider(config(openai_api_key=""))
    with pytest.raises(AIProviderError, match="not configured"):
        await provider._parse([], RequirementReviewContent)


@pytest.mark.asyncio
async def test_parses_structured_output(monkeypatch, review_content):
    provider = OpenAIProvider(config())

    async def fake_parse(**_kwargs):
        return SimpleNamespace(status="completed", output_parsed=review_content)

    monkeypatch.setattr(provider.client.responses, "parse", fake_parse)
    result = await provider._parse([], RequirementReviewContent)
    assert result.business_summary == review_content.business_summary
    assert provider.client.max_retries == 2


@pytest.mark.asyncio
async def test_incomplete_response_is_reported(monkeypatch):
    provider = OpenAIProvider(config())

    async def fake_parse(**_kwargs):
        return SimpleNamespace(status="incomplete", output_parsed=None)

    monkeypatch.setattr(provider.client.responses, "parse", fake_parse)
    with pytest.raises(AIProviderError, match="incomplete"):
        await provider._parse([], RequirementReviewContent)


@pytest.mark.asyncio
async def test_timeout_is_retryable(monkeypatch):
    provider = OpenAIProvider(config())

    async def fake_parse(**_kwargs):
        raise APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))

    monkeypatch.setattr(provider.client.responses, "parse", fake_parse)
    with pytest.raises(AIProviderError) as caught:
        await provider._parse([], RequirementReviewContent)
    assert caught.value.details["retryable"] is True


@pytest.mark.asyncio
async def test_exhausted_credit_is_not_retryable(monkeypatch):
    provider = OpenAIProvider(config())

    async def fake_parse(**_kwargs):
        response = httpx.Response(
            429,
            request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
            json={
                "error": {
                    "message": "No credits",
                    "type": "insufficient_quota",
                    "code": "credit_balance_exhausted",
                }
            },
        )
        raise RateLimitError("No credits", response=response, body=response.json())

    monkeypatch.setattr(provider.client.responses, "parse", fake_parse)
    with pytest.raises(AIProviderError, match="credit balance") as caught:
        await provider._parse([], RequirementReviewContent)
    assert caught.value.details == {
        "retryable": False,
        "provider_code": "credit_balance_exhausted",
    }


@pytest.mark.asyncio
async def test_schema_mismatch_is_reported(monkeypatch):
    provider = OpenAIProvider(config())

    async def fake_parse(**_kwargs):
        return SimpleNamespace(status="completed", output_parsed={"language": "vi"})

    monkeypatch.setattr(provider.client.responses, "parse", fake_parse)
    with pytest.raises(AIProviderError, match="invalid"):
        await provider._parse([], RequirementReviewContent)


@pytest.mark.asyncio
async def test_gemini_requires_api_key():
    provider = GeminiProvider(config(gemini_api_key=""))
    with pytest.raises(AIProviderError, match="GEMINI_API_KEY"):
        await provider._parse([], RequirementReviewContent)


@pytest.mark.asyncio
async def test_gemini_parses_structured_output_and_maps_developer_role(monkeypatch, review_content):
    provider = GeminiProvider(config())
    captured = {}

    async def fake_parse(**kwargs):
        captured.update(kwargs)
        message = SimpleNamespace(parsed=review_content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(provider.client.beta.chat.completions, "parse", fake_parse)
    result = await provider._parse(
        [
            {"role": "developer", "content": "System instructions"},
            {"role": "user", "content": "Story data"},
        ],
        RequirementReviewContent,
    )
    assert result.business_summary == review_content.business_summary
    assert captured["model"] == "gemini-3.5-flash-lite"
    assert captured["messages"][0]["role"] == "system"
