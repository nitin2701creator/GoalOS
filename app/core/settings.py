"""
Application settings.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "GoalOS"
    environment: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    database_url: str = "postgresql+psycopg://goalos:goalos@localhost:5432/goalos"

    model_config = SettingsConfigDict(
        env_prefix="GOALOS_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
