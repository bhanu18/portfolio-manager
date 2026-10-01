from pydantic import field_validator
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
