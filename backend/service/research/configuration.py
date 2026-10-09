"""Server-owned provider configuration; API responses never contain credentials."""

from core.config import settings
from models.research import ResearchProviderOption


def provider_options() -> list[ResearchProviderOption]:
    options = [
        ResearchProviderOption(
            id="openai",
            label="OpenAI",
            model=settings.RESEARCH_MODEL,
            enabled=bool(settings.OPENAI_API_KEY.strip()),
        ),
        ResearchProviderOption(
            id="anthropic",
            label="Anthropic",
            model=settings.ANTHROPIC_RESEARCH_MODEL,
            enabled=bool(settings.ANTHROPIC_API_KEY.strip()),
        ),
        ResearchProviderOption(
            id="local",
            label="Local",
            model=settings.LOCAL_LLM_MODEL.strip() or "Ollama",
            enabled=bool(settings.LOCAL_LLM_MODEL.strip()),
        ),
    ]
    auto = ResearchProviderOption(
        id="auto",
        label="Auto",
        model="cost-routed",
        enabled=any(option.enabled for option in options),
    )
    return [auto, *options]


def default_provider() -> str:
    options = provider_options()
    preferred = next(option for option in options if option.id == settings.RESEARCH_PROVIDER)
    return (
        # Fall back to a concrete provider; Auto is only used when chosen explicitly.
        next(
            (option.id for option in options if option.enabled and option.id != "auto"),
            preferred.id,
        )
        if not preferred.enabled
        else preferred.id
    )


def model_for_provider(provider: str) -> str:
    return next(option.model for option in provider_options() if option.id == provider)


def provider_enabled(provider: str) -> bool:
    return any(option.id == provider and option.enabled for option in provider_options())
