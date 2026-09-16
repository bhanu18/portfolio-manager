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

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


# Create a single, importable instance of the settings
settings = Settings()
