"""LLM clients behind one small interface, so the provider is a config switch.

- OpenAICompatibleClient covers OpenAI, Google Gemini, Ollama (local), LM Studio,
  Groq and anything else that speaks the /chat/completions API.
- AnthropicClient covers Claude.
- DemoClient (demo_llm.py) answers the sample questions offline, with no API key.

All HTTP calls go through post_json(), which retries rate limits and server
errors with exponential backoff.
"""
from __future__ import annotations

import logging
import random
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}


class LLMError(Exception):
    pass


def post_json(url: str, payload: dict, *, headers: dict, timeout: float, retries: int = 3, label: str = "LLM") -> dict:
    last_error = ""
    for attempt in range(retries + 1):
        retry_after = None
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            last_error = f"could not reach {label} ({exc.__class__.__name__})"
        else:
            if response.status_code < 400:
                try:
                    return response.json()
                except ValueError as exc:
                    raise LLMError(f"{label} returned a response that is not JSON") from exc
            body = response.text[:300]
            if response.status_code in (401, 403):
                raise LLMError(f"{label} rejected the API key (HTTP {response.status_code}). Check LLM_API_KEY in .env.")
            if response.status_code not in RETRYABLE_STATUS:
                raise LLMError(f"{label} returned HTTP {response.status_code}: {body}")
            last_error = f"{label} returned HTTP {response.status_code}"
            header = response.headers.get("Retry-After", "")
            retry_after = float(header) if header.replace(".", "", 1).isdigit() else None
        if attempt < retries:
            delay = min(retry_after if retry_after is not None else 0.5 * 2 ** attempt + random.random() * 0.25, 10)
            logger.warning("%s; retrying in %.1fs (attempt %d/%d)", last_error, delay, attempt + 1, retries)
            time.sleep(delay)
    raise LLMError(f"{last_error} after {retries + 1} attempts")


class LLMClient:
    provider = "base"

    def __init__(self, model: str):
        self.model = model

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"

    def complete(self, system: str, messages: list[dict], *, purpose: str = "") -> str:
        """Return the assistant's text reply. `purpose` is a trace label ("sql" or "insight")."""
        raise NotImplementedError


class OpenAICompatibleClient(LLMClient):
    provider = "openai"

    def __init__(self, model: str, api_key: str = "", base_url: str = "", timeout: float = 60):
        super().__init__(model)
        self.api_key = api_key
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.timeout = timeout

    def complete(self, system: str, messages: list[dict], *, purpose: str = "") -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {"model": self.model, "messages": [{"role": "system", "content": system}, *messages]}
        data = post_json(f"{self.base_url}/chat/completions", payload, headers=headers, timeout=self.timeout, label=self.model)
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Unexpected response format from the model API") from exc


class AnthropicClient(LLMClient):
    provider = "anthropic"

    def __init__(self, model: str, api_key: str, base_url: str = "", timeout: float = 60):
        super().__init__(model)
        self.api_key = api_key
        self.base_url = (base_url or "https://api.anthropic.com").rstrip("/")
        self.timeout = timeout

    def complete(self, system: str, messages: list[dict], *, purpose: str = "") -> str:
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        payload = {"model": self.model, "max_tokens": 1500, "system": system, "messages": messages}
        data = post_json(f"{self.base_url}/v1/messages", payload, headers=headers, timeout=self.timeout, label=self.model)
        try:
            return "".join(block.get("text", "") for block in data["content"] if block.get("type") == "text")
        except (KeyError, TypeError) as exc:
            raise LLMError("Unexpected response format from the Anthropic API") from exc


DEFAULT_MODELS = {"openai": "gpt-4.1-mini", "anthropic": "claude-haiku-5-5"}


def get_llm() -> LLMClient:
    provider = settings.LLM_PROVIDER
    model = settings.LLM_MODEL or DEFAULT_MODELS.get(provider, "")
    if provider == "openai":
        return OpenAICompatibleClient(model, settings.LLM_API_KEY, settings.LLM_BASE_URL, settings.LLM_TIMEOUT_S)
    if provider == "anthropic":
        if not settings.LLM_API_KEY:
            raise LLMError("LLM_PROVIDER=anthropic needs LLM_API_KEY in backend/.env")
        return AnthropicClient(model, settings.LLM_API_KEY, settings.LLM_BASE_URL, settings.LLM_TIMEOUT_S)
    if provider == "demo":
        from .demo_llm import DemoClient

        return DemoClient()
    raise LLMError(f"Unknown LLM_PROVIDER '{provider}'. Use demo, openai or anthropic.")


def describe_provider() -> dict:
    try:
        llm = get_llm()
        return {"provider": llm.provider, "model": llm.model, "ready": True, "error": ""}
    except LLMError as exc:
        return {"provider": settings.LLM_PROVIDER, "model": settings.LLM_MODEL, "ready": False, "error": str(exc)}
