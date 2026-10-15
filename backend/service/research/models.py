"""LangChain chat models for each research provider.

Retries are off everywhere: failover and cooldowns (`errors.provider_failure`, orchestrator)
decide what happens after an error, and SDK retries would bill twice and hide 429s.
`output_version="v1"` makes OpenAI and Anthropic return text, citations and web-search
results as the same standard content blocks.
"""

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from core.config import settings
from service.research.errors import ProviderUnavailable
from service.research.local_agent import thinking as thinking_flag

# OpenAI's client insists on a key; local servers (Ollama, mlx_lm, LM Studio) ignore it.
LOCAL_PLACEHOLDER_KEY = "unused"


def require_key(key: str, name: str) -> str:
    """The SDK clients refuse to build without a key; fail like a 401 so Auto fails over."""
    if not key.strip():
        raise ProviderUnavailable(
            f"The {name} API key or model access needs attention on the server.", cooldown=1800
        )
    return key.strip()


def chat_model(
    provider: str, model: str, *, max_tokens: int, thinking: bool | None = None
) -> BaseChatModel:
    """Build the model for a provider. `thinking` overrides LOCAL_LLM_THINKING (local only)."""
    if provider == "anthropic":
        return ChatAnthropic(
            model=model,
            api_key=SecretStr(require_key(settings.ANTHROPIC_API_KEY, "Anthropic")),
            max_tokens=max_tokens,
            max_retries=0,
            default_request_timeout=90,
            output_version="v1",
        )
    if provider == "openai":
        return ChatOpenAI(
            model=model,
            api_key=SecretStr(require_key(settings.OPENAI_API_KEY, "OpenAI")),
            max_completion_tokens=max_tokens,
            max_retries=0,
            timeout=90,
            use_responses_api=True,
            output_version="v1",
            store=False,
            include=["web_search_call.action.sources", "reasoning.encrypted_content"],
        )
    if provider == "local":
        enabled = settings.LOCAL_LLM_THINKING if thinking is None else thinking
        return ChatOpenAI(
            model=model,
            base_url=settings.LOCAL_LLM_BASE_URL,
            api_key=SecretStr(settings.LOCAL_LLM_API_KEY.strip() or LOCAL_PLACEHOLDER_KEY),
            max_completion_tokens=max_tokens,
            max_retries=0,
            timeout=120,
            use_responses_api=False,
            output_version="v1",
            extra_body=thinking_flag(enabled),
        )
    raise ValueError(f"Unknown research provider: {provider}")
