"""Server-owned provider configuration; API responses never contain credentials."""

from core.config import settings
from models.research import ResearchProviderOption


def provider_options() -> list[ResearchProviderOption]:
    return [
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
    ]


def default_provider() -> str:
    options = provider_options()
    preferred = next(option for option in options if option.id == settings.RESEARCH_PROVIDER)
    return (
        next((option.id for option in options if option.enabled), preferred.id)
        if not preferred.enabled
        else preferred.id
    )


def model_for_provider(provider: str) -> str:
    return next(option.model for option in provider_options() if option.id == provider)


def provider_enabled(provider: str) -> bool:
    return any(option.id == provider and option.enabled for option in provider_options())
