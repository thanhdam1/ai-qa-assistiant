import logging
from typing import Protocol, TypeVar

from openai import APIConnectionError, APIError, APITimeoutError, AsyncOpenAI, RateLimitError
from pydantic import BaseModel, ValidationError

from app.config import Settings, settings
from app.errors import AIProviderError
from app.models import Story
from app.schemas import RequirementReviewContent, TestCaseSetContent
from app.services.prompts import requirement_review_input, test_case_input

logger = logging.getLogger(__name__)
OutputT = TypeVar("OutputT", bound=BaseModel)


class AIProvider(Protocol):
    model_name: str

    async def review_requirements(self, story: Story) -> RequirementReviewContent: ...

    async def generate_test_cases(
        self, story: Story, review: RequirementReviewContent
    ) -> TestCaseSetContent: ...


class OpenAIProvider:
    def __init__(self, config: Settings = settings):
        self.config = config
        self.model_name = config.openai_model
        self.client = AsyncOpenAI(
            api_key=config.openai_api_key or "missing-key",
            timeout=config.ai_timeout_seconds,
            max_retries=config.ai_max_retries,
        )

    async def _parse(
        self, input_items: list[dict[str, str]], output_type: type[OutputT]
    ) -> OutputT:
        if not self.config.openai_api_key:
            raise AIProviderError("OPENAI_API_KEY is not configured")
        try:
            response = await self.client.responses.parse(
                model=self.config.openai_model,
                input=input_items,
                text_format=output_type,
                store=False,
            )
            if response.status != "completed" or response.output_parsed is None:
                raise AIProviderError("The model refused or returned an incomplete response")
            return output_type.model_validate(response.output_parsed)
        except RateLimitError as exc:
            body = exc.body if isinstance(exc.body, dict) else {}
            error = body.get("error", body) if isinstance(body, dict) else {}
            provider_code = error.get("code") if isinstance(error, dict) else None
            billing_messages = {
                "credit_balance_exhausted": (
                    "OpenAI credit balance is exhausted. Add credits in OpenAI billing settings."
                ),
                "organization_spend_limit_exceeded": (
                    "The OpenAI organization spend limit has been reached."
                ),
                "project_spend_limit_exceeded": "The OpenAI project spend limit has been reached.",
                "organization_usage_limit_exceeded": (
                    "The OpenAI organization usage limit has been reached."
                ),
            }
            if provider_code in billing_messages:
                raise AIProviderError(
                    billing_messages[provider_code],
                    retryable=False,
                    provider_code=provider_code,
                ) from exc
            raise AIProviderError(
                "OpenAI request rate limit reached. Wait before retrying.",
                retryable=True,
                provider_code=provider_code,
            ) from exc
        except (APITimeoutError, APIConnectionError) as exc:
            raise AIProviderError("OpenAI connection timed out", retryable=True) from exc
        except (APIError, ValidationError) as exc:
            logger.exception("OpenAI response failed validation")
            raise AIProviderError("OpenAI returned an invalid response") from exc

    async def review_requirements(self, story: Story) -> RequirementReviewContent:
        return await self._parse(requirement_review_input(story), RequirementReviewContent)

    async def generate_test_cases(
        self, story: Story, review: RequirementReviewContent
    ) -> TestCaseSetContent:
        return await self._parse(test_case_input(story, review), TestCaseSetContent)


class GeminiProvider:
    def __init__(self, config: Settings = settings):
        self.config = config
        self.model_name = config.gemini_model
        self.client = AsyncOpenAI(
            api_key=config.gemini_api_key or "missing-key",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            timeout=config.ai_timeout_seconds,
            max_retries=config.ai_max_retries,
        )

    async def _parse(
        self, input_items: list[dict[str, str]], output_type: type[OutputT]
    ) -> OutputT:
        if not self.config.gemini_api_key:
            raise AIProviderError("GEMINI_API_KEY is not configured")
        messages = [
            {
                "role": "system" if item["role"] == "developer" else item["role"],
                "content": item["content"],
            }
            for item in input_items
        ]
        try:
            completion = await self.client.beta.chat.completions.parse(
                model=self.config.gemini_model,
                messages=messages,
                response_format=output_type,
            )
            if not completion.choices or completion.choices[0].message.parsed is None:
                raise AIProviderError("Gemini refused or returned an incomplete response")
            return output_type.model_validate(completion.choices[0].message.parsed)
        except RateLimitError as exc:
            body = exc.body if isinstance(exc.body, dict) else {}
            error = body.get("error", body) if isinstance(body, dict) else {}
            provider_code = error.get("status") if isinstance(error, dict) else None
            raise AIProviderError(
                "Gemini free-tier rate limit reached. Wait before retrying.",
                retryable=True,
                provider_code=provider_code,
            ) from exc
        except (APITimeoutError, APIConnectionError) as exc:
            raise AIProviderError("Gemini connection timed out", retryable=True) from exc
        except (APIError, ValidationError) as exc:
            logger.exception("Gemini response failed validation")
            raise AIProviderError("Gemini returned an invalid response") from exc

    async def review_requirements(self, story: Story) -> RequirementReviewContent:
        return await self._parse(requirement_review_input(story), RequirementReviewContent)

    async def generate_test_cases(
        self, story: Story, review: RequirementReviewContent
    ) -> TestCaseSetContent:
        return await self._parse(test_case_input(story, review), TestCaseSetContent)


def get_ai_provider() -> AIProvider:
    provider = settings.ai_provider.strip().lower()
    if provider == "gemini":
        return GeminiProvider()
    if provider == "openai":
        return OpenAIProvider()
    raise AIProviderError(
        f"Unsupported AI_PROVIDER: {settings.ai_provider}",
        provider_code="unsupported_provider",
    )
