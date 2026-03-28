"""Configuration management for OZ_A2M."""

import os
from functools import lru_cache
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    environment: str = Field(default="development", alias="ENVIRONMENT")
    debug: bool = Field(default=False, alias="DEBUG")
    secret_key: str = Field(default="change-me", alias="SECRET_KEY")
    api_key_salt: str = Field(default="change-me", alias="API_KEY_SALT")

    # MQTT
    mqtt_host: str = Field(default="localhost", alias="MQTT_HOST")
    mqtt_port: int = Field(default=1883, alias="MQTT_PORT")
    mqtt_username: Optional[str] = Field(default=None, alias="MQTT_USERNAME")
    mqtt_password: Optional[str] = Field(default=None, alias="MQTT_PASSWORD")
    mqtt_keepalive: int = Field(default=60, alias="MQTT_KEEPALIVE")

    # Redis
    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_db: int = Field(default=0, alias="REDIS_DB")
    redis_password: Optional[str] = Field(default=None, alias="REDIS_PASSWORD")

    # Elasticsearch
    es_host: str = Field(default="localhost", alias="ES_HOST")
    es_port: int = Field(default=9200, alias="ES_PORT")
    es_index_prefix: str = Field(default="oz_a2m", alias="ES_INDEX_PREFIX")

    # Database
    database_url: str = Field(
        default="postgresql://user:pass@localhost:5432/oz_a2m",
        alias="DATABASE_URL",
    )

    # Exchange
    exchange_api_key: Optional[str] = Field(default=None, alias="EXCHANGE_API_KEY")
    exchange_api_secret: Optional[str] = Field(default=None, alias="EXCHANGE_API_SECRET")
    exchange_name: str = Field(default="binance", alias="EXCHANGE_NAME")

    # LLM
    anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    gemini_api_key: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")

    # Trading
    initial_capital: float = Field(default=10000.0, alias="INITIAL_CAPITAL")
    max_position_pct: float = Field(default=0.1, alias="MAX_POSITION_PCT")
    stop_loss_pct: float = Field(default=0.02, alias="STOP_LOSS_PCT")
    take_profit_pct: float = Field(default=0.04, alias="TAKE_PROFIT_PCT")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="json", alias="LOG_FORMAT")

    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.environment.lower() == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development."""
        return self.environment.lower() == "development"

    @property
    def es_url(self) -> str:
        """Get Elasticsearch URL."""
        return f"http://{self.es_host}:{self.es_port}"

    @property
    def redis_url(self) -> str:
        """Get Redis URL."""
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
