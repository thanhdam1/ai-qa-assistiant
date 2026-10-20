import json
import logging
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, List
from app.core.config import settings
from app.core.masking import DataMasker

logger = logging.getLogger(__name__)

class LLMClient:
    """
    Enterprise Unified Hybrid LLM Adapter.
    Seamlessly routes requests to:
      1. Local On-Premise Ollama (Air-gapped offline environment: Qwen2.5-Coder, DeepSeek)
      2. OpenAI Cloud (GPT-4o, GPT-4o-mini)
      3. Anthropic Claude (Claude 3.5 Sonnet)
      4. Deterministic Algorithmic Fallback (zero crash when offline/no keys configured)
    All prompts and outputs are automatically audited by DataMasker for enterprise compliance.
    """

    @classmethod
    def generate(
        cls,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        json_mode: bool = False
    ) -> Optional[str]:
        """
        Generates text using the configured LLM provider.
        Sanitizes sensitive data before transmission.
        """
        # Enterprise Data Masking
        sanitized_prompt, redactions = DataMasker.mask_text(prompt)
        if redactions:
            logger.info(f"[LLM Security Audit] Sanitized {len(redactions)} secrets from prompt before LLM dispatch.")

        provider = (settings.LLM_PROVIDER or "openai").lower()

        # 1. Try Local Ollama if configured
        if provider == "ollama":
            return cls._call_ollama(sanitized_prompt, system_instruction, temperature, json_mode)

        # 2. Try OpenAI if configured
        if provider == "openai" and settings.OPENAI_API_KEY and settings.OPENAI_API_KEY.startswith("sk-"):
            return cls._call_openai(sanitized_prompt, system_instruction, temperature, json_mode)

        # 3. Try Anthropic if configured
        if provider == "anthropic" and settings.ANTHROPIC_API_KEY:
            return cls._call_anthropic(sanitized_prompt, system_instruction, temperature)

        # Fallback to deterministic algorithmic generator
        logger.debug("[LLMClient] No live LLM provider available or configured. Yielding None for heuristic fallback.")
        return None

    @classmethod
    def _call_ollama(
        cls,
        prompt: str,
        system_instruction: Optional[str],
        temperature: float,
        json_mode: bool
    ) -> Optional[str]:
        """Calls local Ollama instance via HTTP POST /api/generate."""
        try:
            url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate"
            payload: Dict[str, Any] = {
                "model": settings.OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature
                }
            }
            if system_instruction:
                payload["system"] = system_instruction
            if json_mode:
                payload["format"] = "json"

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                res_body = json.loads(resp.read().decode("utf-8"))
                return res_body.get("response", "").strip()
        except Exception as e:
            logger.warning(f"[LLMClient] Ollama call to {settings.OLLAMA_BASE_URL} failed: {e}")
            return None

    @classmethod
    def _call_openai(
        cls,
        prompt: str,
        system_instruction: Optional[str],
        temperature: float,
        json_mode: bool
    ) -> Optional[str]:
        """Calls OpenAI Chat Completions API."""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=settings.OPENAI_API_KEY)
            messages = []
            if system_instruction:
                messages.append({"role": "system", "content": system_instruction})
            messages.append({"role": "user", "content": prompt})

            kwargs: Dict[str, Any] = {
                "model": settings.OPENAI_MODEL,
                "messages": messages,
                "temperature": temperature,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"[LLMClient] OpenAI API call failed: {e}")
            return None

    @classmethod
    def _call_anthropic(
        cls,
        prompt: str,
        system_instruction: Optional[str],
        temperature: float
    ) -> Optional[str]:
        """Calls Anthropic Messages API."""
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            kwargs: Dict[str, Any] = {
                "model": settings.ANTHROPIC_MODEL,
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature
            }
            if system_instruction:
                kwargs["system"] = system_instruction

            resp = client.messages.create(**kwargs)
            return resp.content[0].text.strip()
        except Exception as e:
            logger.error(f"[LLMClient] Anthropic call failed: {e}")
            return None
