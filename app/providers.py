from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from abc import ABC, abstractmethod
from typing import Callable, Awaitable
from urllib.parse import urlparse

from app.models import ProviderInfo, ProviderError, ProviderKeys

logger = logging.getLogger(__name__)

RETRYABLE_CODES = {429, 503}
MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]


def _is_local_ollama_url(base_url: str) -> bool:
    parsed = urlparse(base_url)
    hostname = (parsed.hostname or "").lower()
    return hostname in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _ollama_connection_message(base_url: str) -> str:
    if _is_local_ollama_url(base_url):
        return f"Cannot reach Ollama at {base_url}. Please start Ollama and confirm the model server is listening."
    return f"Cannot reach the Ollama-compatible endpoint at {base_url}. Check the Base URL and service status."


def _normalize_base_url(base_url: str | None, default_base_url: str, *, allow_localhost: bool = False) -> str:
    value = (base_url or "").strip()
    if not value:
        return default_base_url

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ProviderError(400, "Base URL must be a valid http(s) URL.")

    hostname = (parsed.hostname or "").lower()
    blocked_hosts = {
        "169.254.169.254", "metadata.google.internal",
    }
    local_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
    if hostname in blocked_hosts or hostname.endswith(".local"):
        raise ProviderError(400, "Base URL points to a blocked local or metadata address.")

    if hostname in local_hosts and not allow_localhost:
        raise ProviderError(400, "This provider does not allow localhost Base URL values.")

    if parsed.username or parsed.password:
        raise ProviderError(400, "Base URL must not contain embedded credentials.")

    if parsed.scheme == "http" and hostname not in local_hosts:
        raise ProviderError(400, "Custom Base URL must use HTTPS unless it targets local development.")

    return value.rstrip("/")


def _mask_secret(secret: str) -> str:
    value = (secret or "").strip()
    if not value:
        return ""
    if len(value) <= 10:
        return f"{value[:2]}...{value[-2:]} (len={len(value)})"
    return f"{value[:6]}...{value[-4:]} (len={len(value)})"


async def _retry_on_transient(coro_factory, *args, **kwargs):
    """Retry an async callable on transient errors (429/503) with exponential backoff."""
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            return await coro_factory(*args, **kwargs)
        except ProviderError as e:
            if e.code in RETRYABLE_CODES and attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[attempt]
                logger.warning("Transient error %d, retrying in %ds (attempt %d/%d)", e.code, delay, attempt + 1, MAX_RETRIES)
                await asyncio.sleep(delay)
                last_exc = e
            else:
                raise
    raise last_exc


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
        request_key = (api_key or "").strip()
        env_key = os.environ.get(self.env_key, "").strip() if self.env_key else ""
        resolved_key = request_key or env_key
        resolved_key_source = "request" if request_key else ("env" if env_key else "missing")
        if not resolved_key and self.env_key:
            raise ProviderError(401, f"API key not configured for {self.display_name}. Set {self.env_key} or enter it in the web UI.")

        request_base_url = (base_url or "").strip()
        env_base_url = os.environ.get(self.base_url_env_key, "").strip() if self.base_url_env_key else ""
        resolved_base = request_base_url or env_base_url or self.default_base_url
        resolved_base_source = "request" if request_base_url else ("env" if env_base_url else "default")

        self.model = model or self.default_model
        self.max_tokens_analyze = max_tokens_analyze
        self.max_tokens_generate = max_tokens_generate
        self.temperature = temperature
        self.resolved_api_key_source = resolved_key_source
        self.resolved_base_url_source = resolved_base_source
        self.resolved_base_url = _normalize_base_url(resolved_base, self.default_base_url, allow_localhost=self.name == "ollama")
        self.debug_context = {
            "provider": self.name,
            "model": self.model,
            "key_source": resolved_key_source,
            "key_preview": _mask_secret(resolved_key),
            "request_key_preview": _mask_secret(request_key),
            "base_url_source": resolved_base_source,
            "base_url": self.resolved_base_url,
            "uses_custom_base_url": resolved_base_source in {"request", "env"} and bool(self.resolved_base_url),
        }
        self._init_client(resolved_key, self.resolved_base_url)

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
                return await _list_openai_compatible_models(api_key, base_url, "", allow_localhost=False)
            except ProviderError:
                raise
            except Exception as e:
                raise ProviderError(502, f"无法从 Base URL 获取模型列表，请手动输入模型名称。({e})")
        return cls.available_models

    def _init_client(self, api_key: str, base_url: str) -> None:
        from anthropic import AsyncAnthropic
        kwargs = {"api_key": api_key, "auth_token": ""}
        if base_url:
            kwargs["base_url"] = base_url
            logger.info("Anthropic base_url: %s", base_url)
        self.client = AsyncAnthropic(**kwargs)
        self.client.auth_token = None

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
                temperature=self.temperature,
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
                    temperature=self.temperature,
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
            raise _map_anthropic_error(e, self.resolved_base_url, self.resolved_base_url_source)

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
                temperature=self.temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            ) as stream:
                async for text in stream.text_stream:
                    full_text += text
                    await on_chunk(text)
            return full_text
        except Exception as e:
            raise _map_anthropic_error(e, self.resolved_base_url, self.resolved_base_url_source)


class OpenAICompatibleProvider(AIProvider):
    """Base class for providers using OpenAI-compatible chat/completions API."""

    default_list_models_base_url: str = ""

    @classmethod
    async def list_models(cls, api_key: str, base_url: str = "") -> list[str]:
        return await _list_openai_compatible_models(api_key, base_url, cls.default_list_models_base_url, allow_localhost=cls.name == "ollama")

    def _init_client(self, api_key: str, base_url: str) -> None:
        from openai import AsyncOpenAI
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = AsyncOpenAI(**kwargs)

    async def analyze(self, system_prompt: str, user_prompt: str, json_schema: dict) -> dict:
        schema_str = json.dumps(json_schema, ensure_ascii=False)
        prompt = (
            f"{user_prompt}\n\n"
            f"IMPORTANT: Respond with valid JSON matching this schema:\n{schema_str}\n"
            f"Respond ONLY with the JSON object, no other text."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens_analyze,
                temperature=self.temperature,
                response_format={"type": "json_object"},
                messages=messages,
            )
            text = response.choices[0].message.content or "{}"
            return _extract_json(text)
        except Exception as e:
            from openai import BadRequestError
            if isinstance(e, BadRequestError):
                logger.warning("response_format may not be supported for %s, retrying without it", self.model)
                try:
                    response = await self.client.chat.completions.create(
                        model=self.model,
                        max_tokens=self.max_tokens_analyze,
                        temperature=self.temperature,
                        messages=messages,
                    )
                    text = response.choices[0].message.content or "{}"
                    return _extract_json(text)
                except Exception as e2:
                    raise _map_openai_error(e2, self.display_name, getattr(self.client, "base_url", "") and str(self.client.base_url))
            raise _map_openai_error(e, self.display_name, getattr(self.client, "base_url", "") and str(self.client.base_url))

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
                temperature=self.temperature,
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
            raise _map_openai_error(e, self.display_name, getattr(self.client, "base_url", "") and str(self.client.base_url))


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
                    temperature=self.temperature,
                ),
            )
            text = response.text or "{}"
            return _extract_json(text)
        except Exception as e:
            raise _map_generic_error(e, "Gemini", "")

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
                    temperature=self.temperature,
                ),
            )
            async for chunk in response:
                if chunk.text:
                    full_text += chunk.text
                    await on_chunk(chunk.text)
            return full_text
        except Exception as e:
            raise _map_generic_error(e, "Gemini", "")


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


async def _list_openai_compatible_models(api_key: str, base_url: str, default_base_url: str, *, allow_localhost: bool = False) -> list[str]:
    import httpx
    normalized_base_url = _normalize_base_url(base_url, default_base_url, allow_localhost=allow_localhost)
    url = normalized_base_url.rstrip("/") + "/v1/models"
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


def get_provider(provider_name: str, model: str | None = None, api_keys: dict[str, ProviderKeys] | None = None,
                 temperature: float = 0.7) -> AIProvider:
    cls = PROVIDERS.get(provider_name)
    if not cls:
        raise ProviderError(400, f"Unknown provider: {provider_name}. Available: {list(PROVIDERS.keys())}")

    keys = (api_keys or {}).get(provider_name)
    api_key = keys.api_key if keys and keys.api_key else None
    base_url = keys.base_url if keys and keys.base_url else None
    max_analyze = keys.max_tokens_analyze if keys else 16384
    max_generate = keys.max_tokens_generate if keys else 32768
    temperature = keys.temperature if keys and keys.temperature is not None else temperature

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


def _map_anthropic_error(e: Exception, base_url: str = "", base_url_source: str = "default") -> ProviderError:
    logger.error("Anthropic raw error: %s", repr(e))
    raw_message = getattr(e, "message", "") or str(e)
    raw_text = str(raw_message)
    gateway_message_match = re.search(r"'message': '([^']+)'", raw_text)
    gateway_type_match = re.search(r"'type': '([^']+)'", raw_text)
    gateway_message = gateway_message_match.group(1) if gateway_message_match else raw_text[:200]
    gateway_type = gateway_type_match.group(1) if gateway_type_match else ""
    try:
        from anthropic import AuthenticationError, RateLimitError, BadRequestError, APIConnectionError
        if isinstance(e, AuthenticationError):
            if base_url:
                extra = f" ({gateway_type})" if gateway_type else ""
                return ProviderError(
                    401,
                    "Anthropic authentication failed through the custom Base URL. "
                    f"Gateway response: {gateway_message}{extra}. "
                    "This means the custom endpoint received the request but rejected the credentials. "
                    f"Current Base URL: {base_url} (source: {base_url_source})."
                )
            return ProviderError(
                401,
                f"Anthropic authentication failed. Gateway response: {gateway_message}."
            )
        if isinstance(e, RateLimitError):
            return ProviderError(429, "Rate limited by Anthropic. Please wait and try again.")
        if isinstance(e, BadRequestError):
            return ProviderError(400, f"Anthropic API error: {e.message}")
        if isinstance(e, APIConnectionError):
            if base_url:
                return ProviderError(
                    503,
                    "Cannot reach the custom Anthropic-compatible endpoint. "
                    "The gateway did not complete the request. Check network, proxy, TLS/certificate state, service availability, or Base URL compatibility. "
                    f"Current Base URL: {base_url} (source: {base_url_source})."
                )
            return ProviderError(503, "Cannot reach the Anthropic API. Check your internet connection.")
    except ImportError:
        pass
    return ProviderError(500, f"Unexpected error: {e}")


def _map_openai_error(e: Exception, provider_name: str = "API", base_url: str = "") -> ProviderError:
    try:
        from openai import AuthenticationError, RateLimitError, BadRequestError, APIConnectionError
        if isinstance(e, AuthenticationError):
            return ProviderError(401, f"{provider_name} API key is invalid. Check your API key configuration.")
        if isinstance(e, RateLimitError):
            return ProviderError(429, f"Rate limited by {provider_name}. Please wait and try again.")
        if isinstance(e, BadRequestError):
            return ProviderError(400, f"{provider_name} API error: {str(e)[:200]}")
        if isinstance(e, APIConnectionError):
            if provider_name == "Ollama":
                return ProviderError(503, _ollama_connection_message(base_url or "http://localhost:11434/v1"))
            return ProviderError(503, f"Cannot reach the {provider_name} API. Check your internet connection or Base URL.")
    except ImportError:
        pass
    if provider_name == "Ollama":
        return ProviderError(503, _ollama_connection_message(base_url or "http://localhost:11434/v1"))
    return ProviderError(500, f"Unexpected {provider_name} error: {e}")


def _map_generic_error(e: Exception, provider_name: str, base_url: str = "") -> ProviderError:
    msg = str(e).lower()
    if "auth" in msg or "key" in msg or "permission" in msg:
        return ProviderError(401, f"{provider_name} API key is invalid.")
    if "rate" in msg or "quota" in msg or "429" in msg:
        return ProviderError(429, f"Rate limited by {provider_name}. Please wait and try again.")
    if "connect" in msg or "timeout" in msg or "network" in msg or "refused" in msg:
        if provider_name == "Ollama":
            return ProviderError(503, _ollama_connection_message(base_url or "http://localhost:11434/v1"))
        return ProviderError(503, f"Cannot reach {provider_name} API. Check your internet connection.")
    return ProviderError(500, f"{provider_name} error: {str(e)[:200]}")
