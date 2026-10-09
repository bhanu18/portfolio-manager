from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    A Pydantic model to handle application configuration from environment variables.
    """

    # --- Database ---
    DATABASE_URL: str
    SYNC_DATABASE_URL: str

    DB_ECHO: bool = False  # log every SQL statement (noisy; dev debugging only)

    # --- Testing ---
    TEST_DATABASE_URL: str | None = None

    # --- CORS ---
    # Comma-separated list of allowed frontend origins
    CORS_ORIGINS: str = "http://localhost:5173"

    # --- Frontend ---
    # Base URL used to build links in emails (e.g. password reset)
    FRONTEND_URL: str = "http://localhost:5173"

    # --- Security ---
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 15

    # --- Research (server-side only) ---
    OPENAI_API_KEY: str = ""
    RESEARCH_MODEL: str = "gpt-5-mini"
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_RESEARCH_MODEL: str = "claude-sonnet-5-5"
    RESEARCH_PROVIDER: Literal["openai", "anthropic", "local", "auto"] = "openai"
    # OpenAI-compatible local server (Ollama default). Empty model disables local research.
    LOCAL_LLM_BASE_URL: str = "http://localhost:11434/v1"
    LOCAL_LLM_MODEL: str = ""
    # Model that maps unfamiliar trade-import columns; empty = LOCAL_LLM_MODEL. Tiny (~2B)
    # models tend to echo cell values instead of column names, so a 4B+ instruct model fits.
    IMPORT_LLM_MODEL: str = ""
    LOCAL_LLM_API_KEY: str = "ollama"
    # Reasoning on thinking models (Gemma 4, Qwen3): slower and token-hungry; off by default.
    LOCAL_LLM_THINKING: bool = False
    # "provider:model" targets the Auto orchestrator routes to; local tier is LOCAL_LLM_MODEL.
    RESEARCH_TIER_CHEAP: str = "openai:gpt-5-mini"
    RESEARCH_TIER_STRONG: str = "anthropic:claude-sonnet-5-5"
    RESEARCH_DAILY_LIMIT: int = Field(default=20, ge=1)
    RESEARCH_MAX_ACTIVE_PER_USER: int = Field(default=1, ge=1)
    RESEARCH_MAX_MODEL_TURNS: int = Field(default=6, ge=1, le=20)
    RESEARCH_MAX_TOOL_CALLS: int = Field(default=8, ge=1, le=30)
    RESEARCH_TIMEOUT_SECONDS: int = Field(default=180, ge=10)
    RESEARCH_MAX_INPUT_TOKENS: int = Field(default=24000, ge=2000)
    RESEARCH_MAX_OUTPUT_TOKENS: int = Field(default=12000, ge=1000)
    RESEARCH_LEASE_SECONDS: int = Field(default=30, ge=15)
    RESEARCH_POLL_SECONDS: float = Field(default=2, ge=0.1)

    # --- Email Settings ---
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    EMAIL_FROM: str = ""
    EMAIL_FROM_NAME: str = "Portfolio Tracker"

    # This tells Pydantic to load the variables from a .env file
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("SECRET_KEY")
    @classmethod
    def _secret_key_strong_enough(cls, v: str) -> str:
        # Anyone who knows the key can mint tokens for any user, admins included
        if v == "change-me" or len(v) < 32:
            raise ValueError(
                "SECRET_KEY must be at least 32 characters; generate one with "
                'python3 -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return v

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


# Create a single, importable instance of the settings
settings = Settings()
