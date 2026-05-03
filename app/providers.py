from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from abc import ABC, abstractmethod
from typing import Callable, Awaitable

from app.models import ProviderInfo, ProviderError, ProviderKeys

logger = logging.getLogger(__name__)


class AIProvider(ABC):
    name: str = ""
    display_name: str = ""
    available_models: tuple[str, ...] = ()
    default_model: str = ""
    env_key: str = ""
    base_url_env_key: str = ""
    default_base_url: str = ""

    def __init__(self, model: str | None = None, api_key: str | None = None, base_url: str | None = None,
                 max_tokens_analyze: int = 16384, max_tokens_generate: int = 32768, temperature: float = 0.7):
        key = api_key or os.environ.get(self.env_key, "")
        if not key and self.env_key:
            raise ProviderError(401, f"API key not configured for {self.display_name}. Set {self.env_key} or enter it in the web UI.")
        self.model = model or self.default_model
        self.max_tokens_analyze = max_tokens_analyze
        self.max_tokens_generate = max_tokens_generate
        self.temperature = temperature
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

    @classmethod
    async def list_models(cls, api_key: str, base_url: str = "") -> list[str]:
        raise NotImplementedError


class AnthropicProvider(AIProvider):
    name = "anthropic"
    display_name = "Anthropic Claude"
    available_models = ("claude-sonnet-4-6", "claude-haiku-4-5-20251001", "claude-opus-4-7", "mimo-v2.5-pro", "mimo-v2.5", "mimo-v2-pro")
    default_model = "claude-sonnet-4-6"
    env_key = "ANTHROPIC_API_KEY"
    base_url_env_key = "ANTHROPIC_BASE_URL"
    default_base_url = ""

    @classmethod
    async def list_models(cls, api_key: str, base_url: str = "") -> list[str]:
        if base_url:
            try:
                return await _list_openai_compatible_models(api_key, base_url, "")
            except ProviderError:
                raise
            except Exception as e:
                raise ProviderError(502, f"无法从 Base URL 获取模型列表，请手动输入模型名称。({e})")
        return cls.available_models

    def _init_client(self, api_key: str, base_url: str) -> None:
        from anthropic import AsyncAnthropic
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
            logger.info("Anthropic base_url: %s", base_url)
        self.client = AsyncAnthropic(**kwargs)

    async def analyze(self, system_prompt: str, user_prompt: str, json_schema: dict) -> dict:
        try:
            logger.info("Anthropic analyze: model=%s", self.model)
            schema_str = json.dumps(json_schema, ensure_ascii=False)
            full_system = (
                system_prompt + "\n\n"
                "IMPORTANT: You MUST respond with a single valid JSON object matching this schema:\n"
                f"{schema_str}\n"
                "Respond ONLY with the JSON object. No markdown, no explanation, no code fences."
            )
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens_analyze,
                system=full_system,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = ""
            thinking_text = ""
            for block in response.content:
                if block.type == "text":
                    text += block.text
                elif block.type == "thinking":
                    thinking_text += block.thinking
            if not text and thinking_text:
                logger.info("No text blocks, falling back to thinking content for JSON extraction")
                text = thinking_text

            # Try to parse; if it fails, retry by showing the model what it returned
            try:
                return _extract_json(text)
            except json.JSONDecodeError:
                logger.warning("First attempt not JSON, retrying with correction...")
                retry_response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens_analyze,
                    system="You must respond with ONLY a valid JSON object. No markdown, no text, no explanation.",
                    messages=[
                        {"role": "user", "content": f"Your previous response was not valid JSON:\n\n{text[:3000]}\n\nPlease redo it as a single valid JSON object matching the schema. Output ONLY the JSON."},
                    ],
                )
                retry_text = ""
                for block in retry_response.content:
                    if block.type == "text":
                        retry_text += block.text
                    elif block.type == "thinking":
                        retry_text += block.thinking
                return _extract_json(retry_text)
        except json.JSONDecodeError:
            logger.error("Failed to parse JSON after retry. text=%s...", text[:500] if text else "(empty)")
            raise ProviderError(500, f"Model returned non-JSON response. Response start: {text[:300] if text else '(empty)'}")
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
                max_tokens=self.max_tokens_generate,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            ) as stream:
                async for text in stream.text_stream:
                    full_text += text
                    await on_chunk(text)
            return full_text
        except Exception as e:
            raise _map_anthropic_error(e)


class OpenAICompatibleProvider(AIProvider):
    """Base class for providers using OpenAI-compatible chat/completions API."""

    default_list_models_base_url: str = ""

    @classmethod
    async def list_models(cls, api_key: str, base_url: str = "") -> list[str]:
        return await _list_openai_compatible_models(api_key, base_url, cls.default_list_models_base_url)

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
                max_tokens=self.max_tokens_analyze,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
            )
            text = response.choices[0].message.content or "{}"
            return _extract_json(text)
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
                max_tokens=self.max_tokens_generate,
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


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"
    display_name = "OpenAI"
    available_models = ("gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini")
    default_model = "gpt-4o"
    env_key = "OPENAI_API_KEY"
    base_url_env_key = "OPENAI_BASE_URL"
    default_base_url = ""
    default_list_models_base_url = "https://api.openai.com"


class GeminiProvider(AIProvider):
    name = "gemini"
    display_name = "Google Gemini"
    available_models = ("gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash")
    default_model = "gemini-2.5-flash"
    env_key = "GOOGLE_API_KEY"
    base_url_env_key = ""
    default_base_url = ""

    @classmethod
    async def list_models(cls, api_key: str, base_url: str = "") -> list[str]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, cls._sync_list_models, api_key)

    @classmethod
    def _sync_list_models(cls, api_key: str) -> list[str]:
        from google import genai
        gclient = genai.Client(api_key=api_key)
        models = []
        for m in gclient.models.list():
            if hasattr(m, "name"):
                name = m.name.replace("models/", "")
                models.append(name)
        models.sort()
        return models

    def _init_client(self, api_key: str, base_url: str) -> None:
        from google import genai
        from google.genai import types
        self.genai_client = genai.Client(api_key=api_key)
        self._types = types

    async def analyze(self, system_prompt: str, user_prompt: str, json_schema: dict) -> dict:
        try:
            schema_str = json.dumps(json_schema, ensure_ascii=False)
            user_prompt_full = (
                f"{user_prompt}\n\n"
                f"IMPORTANT: Respond with valid JSON matching this schema:\n{schema_str}\n"
                f"Respond ONLY with the JSON object, no other text."
            )
            response = await self.genai_client.aio.models.generate_content(
                model=self.model,
                contents=user_prompt_full,
                config=self._types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    max_output_tokens=self.max_tokens_analyze,
                ),
            )
            text = response.text or "{}"
            return _extract_json(text)
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
            response = await self.genai_client.aio.models.generate_content_stream(
                model=self.model,
                contents=user_prompt,
                config=self._types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=self.max_tokens_generate,
                ),
            )
            async for chunk in response:
                if chunk.text:
                    full_text += chunk.text
                    await on_chunk(chunk.text)
            return full_text
        except Exception as e:
            raise _map_generic_error(e, "Gemini")


class DeepSeekProvider(OpenAICompatibleProvider):
    name = "deepseek"
    display_name = "DeepSeek"
    available_models = ("deepseek-chat", "deepseek-reasoner")
    default_model = "deepseek-chat"
    env_key = "DEEPSEEK_API_KEY"
    base_url_env_key = "DEEPSEEK_BASE_URL"
    default_base_url = "https://api.deepseek.com"
    default_list_models_base_url = "https://api.deepseek.com"


class OpenRouterProvider(OpenAICompatibleProvider):
    name = "openrouter"
    display_name = "OpenRouter"
    available_models = (
        "anthropic/claude-sonnet-4-6",
        "anthropic/claude-haiku-4-5-20251001",
        "openai/gpt-4o",
        "google/gemini-2.5-flash",
        "deepseek/deepseek-chat",
    )
    default_model = "anthropic/claude-sonnet-4-6"
    env_key = "OPENROUTER_API_KEY"
    base_url_env_key = ""
    default_base_url = "https://openrouter.ai/api/v1"
    default_list_models_base_url = "https://openrouter.ai/api/v1"

    def _init_client(self, api_key: str, base_url: str) -> None:
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or self.default_base_url,
            default_headers={"HTTP-Referer": "http://localhost:8000", "X-Title": "README Generator"},
        )


class GroqProvider(OpenAICompatibleProvider):
    name = "groq"
    display_name = "Groq"
    available_models = ("llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768")
    default_model = "llama-3.3-70b-versatile"
    env_key = "GROQ_API_KEY"
    base_url_env_key = ""
    default_base_url = "https://api.groq.com/openai/v1"
    default_list_models_base_url = "https://api.groq.com/openai/v1"


class OllamaProvider(OpenAICompatibleProvider):
    name = "ollama"
    display_name = "Ollama (本地)"
    available_models = ("qwen2.5:7b", "llama3.1:8b", "deepseek-coder-v2:16b", "mistral:7b")
    default_model = "qwen2.5:7b"
    env_key = ""  # Ollama 不需要 API key
    base_url_env_key = ""
    default_base_url = "http://localhost:11434/v1"
    default_list_models_base_url = "http://localhost:11434/v1"


class MoonshotProvider(OpenAICompatibleProvider):
    name = "moonshot"
    display_name = "Moonshot (月之暗面)"
    available_models = ("moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k")
    default_model = "moonshot-v1-8k"
    env_key = "MOONSHOT_API_KEY"
    base_url_env_key = ""
    default_base_url = "https://api.moonshot.cn/v1"
    default_list_models_base_url = "https://api.moonshot.cn/v1"


class SiliconFlowProvider(OpenAICompatibleProvider):
    name = "siliconflow"
    display_name = "SiliconFlow (硅基流动)"
    available_models = ("Qwen/Qwen2.5-7B-Instruct", "deepseek-ai/DeepSeek-V3", "meta-llama/Meta-Llama-3.1-8B-Instruct")
    default_model = "Qwen/Qwen2.5-7B-Instruct"
    env_key = "SILICONFLOW_API_KEY"
    base_url_env_key = ""
    default_base_url = "https://api.siliconflow.cn/v1"
    default_list_models_base_url = "https://api.siliconflow.cn/v1"


class TogetherProvider(OpenAICompatibleProvider):
    name = "together"
    display_name = "Together AI"
    available_models = ("meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo", "mistralai/Mixtral-8x7B-Instruct-v0.1", "Qwen/Qwen2.5-72B-Instruct-Turbo")
    default_model = "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo"
    env_key = "TOGETHER_API_KEY"
    base_url_env_key = ""
    default_base_url = "https://api.together.xyz/v1"
    default_list_models_base_url = "https://api.together.xyz/v1"


class DashScopeProvider(OpenAICompatibleProvider):
    name = "dashscope"
    display_name = "DashScope (通义千问)"
    available_models = ("qwen-turbo", "qwen-plus", "qwen-max", "qwen-long")
    default_model = "qwen-plus"
    env_key = "DASHSCOPE_API_KEY"
    base_url_env_key = ""
    default_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    default_list_models_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"


async def _list_openai_compatible_models(api_key: str, base_url: str, default_base_url: str) -> list[str]:
    import httpx
    url = (base_url or default_base_url).rstrip("/") + "/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 404:
            raise ProviderError(404, "该 API 不支持模型列表查询，请手动输入模型名称")
        if resp.status_code != 200:
            raise ProviderError(resp.status_code, f"获取模型列表失败 (HTTP {resp.status_code})")
        data = resp.json()
        models = sorted(m["id"] for m in data.get("data", []) if m.get("id"))
        return models


PROVIDERS: dict[str, type[AIProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "deepseek": DeepSeekProvider,
    "openrouter": OpenRouterProvider,
    "groq": GroqProvider,
    "ollama": OllamaProvider,
    "moonshot": MoonshotProvider,
    "siliconflow": SiliconFlowProvider,
    "together": TogetherProvider,
    "dashscope": DashScopeProvider,
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
    max_analyze = keys.max_tokens_analyze if keys else 16384
    max_generate = keys.max_tokens_generate if keys else 32768
    temperature = keys.temperature if keys else 0.7

    return cls(model=model, api_key=api_key, base_url=base_url,
               max_tokens_analyze=max_analyze, max_tokens_generate=max_generate,
               temperature=temperature)


def _extract_json(text: str) -> dict:
    """Extract JSON from model response, handling markdown-wrapped responses."""
    if not text or not text.strip():
        return {}

    # 1. Try direct parse
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Try extracting from ```json ... ``` code blocks
    code_blocks = re.findall(r'```(?:json)?\s*\n?(.*?)```', text, re.DOTALL)
    for block in code_blocks:
        try:
            return json.loads(block.strip())
        except json.JSONDecodeError:
            continue

    # 3. Try finding the outermost { ... } or [ ... ]
    for opener, closer in [('{', '}'), ('[', ']')]:
        start = text.find(opener)
        if start < 0:
            continue
        depth = 0
        end = -1
        for i in range(start, len(text)):
            if text[i] == opener:
                depth += 1
            elif text[i] == closer:
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                continue

    raise json.JSONDecodeError("No valid JSON found in response", text, 0)


def _map_anthropic_error(e: Exception) -> ProviderError:
    logger.error("Anthropic raw error: %s", repr(e))
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
