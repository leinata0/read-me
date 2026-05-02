from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import Callable, Awaitable

from app.models import ProviderInfo, ProviderError, ProviderKeys


class AIProvider(ABC):
    name: str = ""
    display_name: str = ""
    available_models: list[str] = []
    default_model: str = ""
    env_key: str = ""
    base_url_env_key: str = ""
    default_base_url: str = ""

    def __init__(self, model: str | None = None, api_key: str | None = None, base_url: str | None = None):
        key = api_key or os.environ.get(self.env_key, "")
        if not key:
            raise ProviderError(401, f"API key not configured for {self.display_name}. Set {self.env_key} or enter it in the web UI.")
        self.model = model or self.default_model
        base = base_url or os.environ.get(self.base_url_env_key, "") or self.default_base_url
        self._init_client(key, base)

    @abstractmethod
    def _init_client(self, api_key: str, base_url: str) -> None: ...

    @abstractmethod
    async def analyze(self, system_prompt: str, user_prompt: str, json_schema: dict) -> dict:
        """Structured analysis returning a JSON dict."""

    @abstractmethod
    async def generate_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        on_chunk: Callable[[str], Awaitable[None]],
    ) -> str:
        """Stream text generation, calling on_chunk for each delta."""

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.environ.get(cls.env_key, ""))


class AnthropicProvider(AIProvider):
    name = "anthropic"
    display_name = "Anthropic Claude"
    available_models = ["mimo-v2.5[1m]", "claude-sonnet-4-6", "claude-haiku-4-5-20251001", "claude-opus-4-7"]
    default_model = "mimo-v2.5[1m]"
    env_key = "ANTHROPIC_API_KEY"
    base_url_env_key = "ANTHROPIC_BASE_URL"
    default_base_url = ""

    def _init_client(self, api_key: str, base_url: str) -> None:
        from anthropic import AsyncAnthropic
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = AsyncAnthropic(**kwargs)

    async def analyze(self, system_prompt: str, user_prompt: str, json_schema: dict) -> dict:
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=8192,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = ""
            for block in response.content:
                if block.type == "text":
                    text += block.text
            return json.loads(text) if text else {}
        except Exception as e:
            raise _map_anthropic_error(e)

    async def generate_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        on_chunk: Callable[[str], Awaitable[None]],
    ) -> str:
        try:
            full_text = ""
            async with self.client.messages.stream(
                model=self.model,
                max_tokens=16384,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            ) as stream:
                async for text in stream.text_stream:
                    full_text += text
                    await on_chunk(text)
            return full_text
        except Exception as e:
            raise _map_anthropic_error(e)


class OpenAIProvider(AIProvider):
    name = "openai"
    display_name = "OpenAI"
    available_models = ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini"]
    default_model = "gpt-4o"
    env_key = "OPENAI_API_KEY"
    base_url_env_key = "OPENAI_BASE_URL"
    default_base_url = ""

    def _init_client(self, api_key: str, base_url: str) -> None:
        from openai import AsyncOpenAI
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = AsyncOpenAI(**kwargs)

    async def analyze(self, system_prompt: str, user_prompt: str, json_schema: dict) -> dict:
        try:
            schema_str = json.dumps(json_schema, ensure_ascii=False)
            prompt = (
                f"{user_prompt}\n\n"
                f"IMPORTANT: Respond with valid JSON matching this schema:\n{schema_str}\n"
                f"Respond ONLY with the JSON object, no other text."
            )
            response = await self.client.chat.completions.create(
                model=self.model,
                max_tokens=8192,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
            )
            text = response.choices[0].message.content or "{}"
            return json.loads(text)
        except Exception as e:
            raise _map_openai_error(e)

    async def generate_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        on_chunk: Callable[[str], Awaitable[None]],
    ) -> str:
        try:
            full_text = ""
            stream = await self.client.chat.completions.create(
                model=self.model,
                max_tokens=16384,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    full_text += delta
                    await on_chunk(delta)
            return full_text
        except Exception as e:
            raise _map_openai_error(e)


class GeminiProvider(AIProvider):
    name = "gemini"
    display_name = "Google Gemini"
    available_models = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"]
    default_model = "gemini-2.5-flash"
    env_key = "GOOGLE_API_KEY"
    base_url_env_key = ""
    default_base_url = ""

    def _init_client(self, api_key: str, base_url: str) -> None:
        from google import genai
        from google.genai import types
        self.genai_client = genai.Client(api_key=api_key)
        self._types = types

    async def analyze(self, system_prompt: str, user_prompt: str, json_schema: dict) -> dict:
        try:
            schema_str = json.dumps(json_schema, ensure_ascii=False)
            prompt = (
                f"{system_prompt}\n\n{user_prompt}\n\n"
                f"IMPORTANT: Respond with valid JSON matching this schema:\n{schema_str}\n"
                f"Respond ONLY with the JSON object, no other text."
            )
            response = await self.genai_client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=self._types.GenerateContentConfig(
                    response_mime_type="application/json",
                    max_output_tokens=8192,
                ),
            )
            text = response.text or "{}"
            return json.loads(text)
        except Exception as e:
            raise _map_generic_error(e, "Gemini")

    async def generate_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        on_chunk: Callable[[str], Awaitable[None]],
    ) -> str:
        try:
            full_text = ""
            prompt = f"{system_prompt}\n\n{user_prompt}"
            response = await self.genai_client.aio.models.generate_content_stream(
                model=self.model,
                contents=prompt,
                config=self._types.GenerateContentConfig(max_output_tokens=16384),
            )
            async for chunk in response:
                if chunk.text:
                    full_text += chunk.text
                    await on_chunk(chunk.text)
            return full_text
        except Exception as e:
            raise _map_generic_error(e, "Gemini")


class DeepSeekProvider(AIProvider):
    name = "deepseek"
    display_name = "DeepSeek"
    available_models = ["deepseek-chat", "deepseek-reasoner"]
    default_model = "deepseek-chat"
    env_key = "DEEPSEEK_API_KEY"
    base_url_env_key = "DEEPSEEK_BASE_URL"
    default_base_url = "https://api.deepseek.com"

    def _init_client(self, api_key: str, base_url: str) -> None:
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url or self.default_base_url)

    async def analyze(self, system_prompt: str, user_prompt: str, json_schema: dict) -> dict:
        try:
            schema_str = json.dumps(json_schema, ensure_ascii=False)
            prompt = (
                f"{user_prompt}\n\n"
                f"IMPORTANT: Respond with valid JSON matching this schema:\n{schema_str}\n"
                f"Respond ONLY with the JSON object, no other text."
            )
            response = await self.client.chat.completions.create(
                model=self.model,
                max_tokens=8192,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
            )
            text = response.choices[0].message.content or "{}"
            return json.loads(text)
        except Exception as e:
            raise _map_openai_error(e)

    async def generate_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        on_chunk: Callable[[str], Awaitable[None]],
    ) -> str:
        try:
            full_text = ""
            stream = await self.client.chat.completions.create(
                model=self.model,
                max_tokens=16384,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    full_text += delta
                    await on_chunk(delta)
            return full_text
        except Exception as e:
            raise _map_openai_error(e)


class OpenRouterProvider(AIProvider):
    name = "openrouter"
    display_name = "OpenRouter"
    available_models = [
        "anthropic/claude-sonnet-4-6",
        "anthropic/claude-haiku-4-5-20251001",
        "openai/gpt-4o",
        "google/gemini-2.5-flash",
        "deepseek/deepseek-chat",
    ]
    default_model = "anthropic/claude-sonnet-4-6"
    env_key = "OPENROUTER_API_KEY"
    base_url_env_key = ""
    default_base_url = "https://openrouter.ai/api/v1"

    def _init_client(self, api_key: str, base_url: str) -> None:
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or self.default_base_url,
            default_headers={"HTTP-Referer": "http://localhost:8000", "X-Title": "README Generator"},
        )

    async def analyze(self, system_prompt: str, user_prompt: str, json_schema: dict) -> dict:
        try:
            schema_str = json.dumps(json_schema, ensure_ascii=False)
            prompt = (
                f"{user_prompt}\n\n"
                f"IMPORTANT: Respond with valid JSON matching this schema:\n{schema_str}\n"
                f"Respond ONLY with the JSON object, no other text."
            )
            response = await self.client.chat.completions.create(
                model=self.model,
                max_tokens=8192,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
            )
            text = response.choices[0].message.content or "{}"
            return json.loads(text)
        except Exception as e:
            raise _map_openai_error(e)

    async def generate_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        on_chunk: Callable[[str], Awaitable[None]],
    ) -> str:
        try:
            full_text = ""
            stream = await self.client.chat.completions.create(
                model=self.model,
                max_tokens=16384,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    full_text += delta
                    await on_chunk(delta)
            return full_text
        except Exception as e:
            raise _map_openai_error(e)


PROVIDERS: dict[str, type[AIProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "deepseek": DeepSeekProvider,
    "openrouter": OpenRouterProvider,
}


def list_providers() -> list[ProviderInfo]:
    result = []
    for name, cls in PROVIDERS.items():
        result.append(ProviderInfo(
            name=name,
            display_name=cls.display_name,
            available_models=cls.available_models,
            is_configured=cls.is_configured(),
            base_url_hint=cls.default_base_url,
            env_key_hint=cls.env_key,
        ))
    return result


def get_provider(provider_name: str, model: str | None = None, api_keys: dict[str, ProviderKeys] | None = None) -> AIProvider:
    cls = PROVIDERS.get(provider_name)
    if not cls:
        raise ProviderError(400, f"Unknown provider: {provider_name}. Available: {list(PROVIDERS.keys())}")

    keys = (api_keys or {}).get(provider_name)
    api_key = keys.api_key if keys and keys.api_key else None
    base_url = keys.base_url if keys and keys.base_url else None

    return cls(model=model, api_key=api_key, base_url=base_url)


def _map_anthropic_error(e: Exception) -> ProviderError:
    try:
        from anthropic import AuthenticationError, RateLimitError, BadRequestError, APIConnectionError
        if isinstance(e, AuthenticationError):
            return ProviderError(401, "Anthropic API key is invalid. Check your API key.")
        if isinstance(e, RateLimitError):
            return ProviderError(429, "Rate limited by Anthropic. Please wait and try again.")
        if isinstance(e, BadRequestError):
            return ProviderError(400, f"Anthropic API error: {e.message}")
        if isinstance(e, APIConnectionError):
            return ProviderError(503, "Cannot reach the Anthropic API. Check your internet connection or base URL.")
    except ImportError:
        pass
    return ProviderError(500, f"Unexpected error: {e}")


def _map_openai_error(e: Exception) -> ProviderError:
    try:
        from openai import AuthenticationError, RateLimitError, BadRequestError, APIConnectionError
        if isinstance(e, AuthenticationError):
            return ProviderError(401, "API key is invalid. Check your API key configuration.")
        if isinstance(e, RateLimitError):
            return ProviderError(429, "Rate limited. Please wait and try again.")
        if isinstance(e, BadRequestError):
            return ProviderError(400, f"API error: {str(e)[:200]}")
        if isinstance(e, APIConnectionError):
            return ProviderError(503, "Cannot reach the API. Check your internet connection or base URL.")
    except ImportError:
        pass
    return ProviderError(500, f"Unexpected error: {e}")


def _map_generic_error(e: Exception, provider_name: str) -> ProviderError:
    msg = str(e).lower()
    if "auth" in msg or "key" in msg or "permission" in msg:
        return ProviderError(401, f"{provider_name} API key is invalid.")
    if "rate" in msg or "quota" in msg or "429" in msg:
        return ProviderError(429, f"Rate limited by {provider_name}. Please wait and try again.")
    if "connect" in msg or "timeout" in msg or "network" in msg:
        return ProviderError(503, f"Cannot reach {provider_name} API. Check your internet connection.")
    return ProviderError(500, f"{provider_name} error: {str(e)[:200]}")
