from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process configuration. Connection strings come only from the environment."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongodb_uri: str = Field(min_length=1)
    mongodb_database: str = Field(default="credits", min_length=1)
    redis_url: str = Field(min_length=1)
    port: int = Field(default=8000, ge=1, le=65535)


def get_settings() -> Settings:
    """Load settings from the environment and an optional `.env` file."""
    return Settings()
