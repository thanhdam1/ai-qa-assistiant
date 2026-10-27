import json
from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError, RateLimitError

from app.config import Settings
from app.errors import AIProviderError
from app.schemas import RequirementReviewContent, TestCaseSetContent as SuiteContent
from app.services.ai import GeminiProvider, OpenAIProvider


@pytest.fixture(autouse=True)
def block_unmocked_provider_network(monkeypatch):
    async def fail_send(*_args, **_kwargs):
        raise AssertionError("Unit test attempted an unmocked HTTP request")

    monkeypatch.setattr(httpx.AsyncClient, "send", fail_send)


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

    async def fake_create(**kwargs):
        captured.update(kwargs)
        message = SimpleNamespace(refusal=None, content=review_content.model_dump_json())
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(provider.client.chat.completions, "create", fake_create)
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


def test_gemini_mock_intercepts_create_without_network_or_event_loop(monkeypatch, review_content):
    provider = GeminiProvider(config())
    calls = []

    async def fake_create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            refusal=None, content=review_content.model_dump_json(),
        ))])

    monkeypatch.setattr(provider.client.chat.completions, "create", fake_create)
    operation = provider._parse([{"role": "developer", "content": "Review"}], RequirementReviewContent)
    with pytest.raises(StopIteration) as finished:
        operation.send(None)
    assert finished.value.value.business_summary == review_content.business_summary
    assert calls[0]["messages"][0]["role"] == "system"


def test_gemini_traceability_repair_names_case_and_allowed_targets(monkeypatch, test_content):
    provider = GeminiProvider(config())
    invalid = test_content.model_dump(mode="json")
    invalid["test_cases"][0]["requirement_traceability"] = []
    invalid["test_cases"][0]["api_traceability"] = []
    calls = []

    async def fake_create(**kwargs):
        calls.append(kwargs)
        content = invalid if len(calls) == 1 else test_content.model_dump(mode="json")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            refusal=None, content=json.dumps(content),
        ))])

    monkeypatch.setattr(provider.client.chat.completions, "create", fake_create)
    operation = provider._parse(
        [{"role": "developer", "content": "Design tests"}],
        SuiteContent,
        traceability_ids={
            "requirement_traceability": ["AC-001", "RSK-001"],
            "api_traceability": ["API-001"],
        },
    )
    with pytest.raises(StopIteration) as finished:
        operation.send(None)
    assert finished.value.value.test_cases[0].id == "TC-001"
    assert len(calls) == 2
    repair_message = calls[1]["messages"][-1]["content"]
    assert "TC-001" in repair_message
    assert "test_cases.0" in repair_message
    assert '"requirement_traceability": ["AC-001", "RSK-001"]' in repair_message
    assert '"api_traceability": ["API-001"]' in repair_message
    assert "unrelated ID" in repair_message


def test_gemini_final_traceability_error_names_case_without_extra_retry(monkeypatch, test_content):
    provider = GeminiProvider(config())
    invalid = test_content.model_dump(mode="json")
    invalid["test_cases"][1]["requirement_traceability"] = []
    invalid["test_cases"][1]["api_traceability"] = []
    calls = []

    async def fake_create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            refusal=None, content=json.dumps(invalid),
        ))])

    monkeypatch.setattr(provider.client.chat.completions, "create", fake_create)
    operation = provider._parse(
        [{"role": "developer", "content": "Design tests"}],
        SuiteContent,
        traceability_ids={"requirement_traceability": ["AC-001"], "api_traceability": []},
    )
    with pytest.raises(AIProviderError) as failure:
        operation.send(None)
    assert "test_cases.1" in failure.value.message
    assert "TC-002" in failure.value.message
    assert len(calls) == 2
