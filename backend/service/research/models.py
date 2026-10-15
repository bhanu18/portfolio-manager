"""LangChain chat models for each research provider.

Retries are off everywhere: failover and cooldowns (`errors.provider_failure`, orchestrator)
decide what happens after an error, and SDK retries would bill twice and hide 429s.
`output_version="v1"` makes OpenAI and Anthropic return text, citations and web-search
results as the same standard content blocks.
"""

import json
from typing import Any

import httpx2
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from core.config import settings
from service.research.errors import ProviderUnavailable

# OpenAI's client insists on a key; local servers (Ollama, mlx_lm, LM Studio) ignore it.
LOCAL_PLACEHOLDER_KEY = "unused"


def thinking_flag(enabled: bool) -> dict[str, Any]:
    """Toggle reasoning on thinking models (Gemma 4, Qwen3) via the chat template.

    Honoured by mlx_lm.server, vLLM and LM Studio; servers that don't know it ignore it.
    """
    return {"chat_template_kwargs": {"enable_thinking": enabled}}


def local_body(max_tokens: int, thinking: bool | None = None) -> dict[str, Any]:
    """Request-body extras for local servers. They take `max_tokens`; LangChain would send
    `max_completion_tokens`, which older OpenAI-compatible servers ignore."""
    enabled = settings.LOCAL_LLM_THINKING if thinking is None else thinking
    return {**thinking_flag(enabled), "max_tokens": max_tokens}


class StringifyToolArguments(httpx2.AsyncBaseTransport):
    """Some local servers return tool-call `arguments` as a JSON object instead of the string
    the OpenAI schema requires, which LangChain rejects. Re-encode them as strings."""

    def __init__(self, inner: httpx2.AsyncBaseTransport):
        self.inner = inner

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        response = await self.inner.handle_async_request(request)
        if not request.url.path.endswith("/chat/completions"):
            return response
        body = await response.aread()
        try:
            data = json.loads(body)
        except ValueError:
            data = None
        changed = False
        for choice in (data.get("choices") or []) if isinstance(data, dict) else []:
            for call in (choice.get("message") or {}).get("tool_calls") or []:
                function = call.get("function") or {}
                if "arguments" in function and not isinstance(function["arguments"], str):
                    function["arguments"] = json.dumps(function["arguments"])
                    changed = True
        # The body was read (and decoded), so rebuild the response without transfer headers.
        headers = [
            (key, value)
            for key, value in response.headers.items()
            if key.lower() not in ("content-length", "content-encoding", "transfer-encoding")
        ]
        content = json.dumps(data).encode() if changed else body
        return httpx2.Response(response.status_code, headers=headers, content=content)

    async def aclose(self) -> None:
        await self.inner.aclose()


def local_transport() -> httpx2.AsyncBaseTransport:
    """The network transport for local servers (tests replace this)."""
    return httpx2.AsyncHTTPTransport()


def require_key(key: str, name: str) -> str:
    """The SDK clients refuse to build without a key; fail like a 401 so Auto fails over."""
    if not key.strip():
        raise ProviderUnavailable(
            f"The {name} API key or model access needs attention on the server.", cooldown=1800
        )
    return key.strip()


def chat_model(
    provider: str,
    model: str,
    *,
    max_tokens: int,
    thinking: bool | None = None,
    timeout: float | None = None,
) -> BaseChatModel:
    """Build the model for a provider. `thinking` overrides LOCAL_LLM_THINKING (local only);
    `timeout` overrides the provider's default request timeout."""
    if provider == "anthropic":
        return ChatAnthropic(
            model=model,
            api_key=SecretStr(require_key(settings.ANTHROPIC_API_KEY, "Anthropic")),
            max_tokens=max_tokens,
            max_retries=0,
            default_request_timeout=timeout or 90,
            output_version="v1",
        )
    if provider == "openai":
        return ChatOpenAI(
            model=model,
            api_key=SecretStr(require_key(settings.OPENAI_API_KEY, "OpenAI")),
            max_completion_tokens=max_tokens,
            max_retries=0,
            timeout=timeout or 90,
            use_responses_api=True,
            output_version="v1",
            store=False,
            include=["web_search_call.action.sources", "reasoning.encrypted_content"],
        )
    if provider == "local":
        return ChatOpenAI(
            model=model,
            base_url=settings.LOCAL_LLM_BASE_URL,
            api_key=SecretStr(settings.LOCAL_LLM_API_KEY.strip() or LOCAL_PLACEHOLDER_KEY),
            max_retries=0,
            timeout=timeout or 120,
            use_responses_api=False,
            output_version="v1",
            extra_body=local_body(max_tokens, thinking),
            http_async_client=httpx2.AsyncClient(
                timeout=timeout or 120, transport=StringifyToolArguments(local_transport())
            ),
        )
    raise ValueError(f"Unknown research provider: {provider}")
