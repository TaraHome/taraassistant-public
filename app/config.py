"""Configuration settings using Pydantic with encrypted storage support."""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Literal, Optional


class Settings(BaseSettings):
    """Application settings loaded from encrypted storage or environment variables."""

    # App
    app_name: str = Field(default="TaraHome AI Assistant")
    debug: bool = Field(default=False)

    # AI Provider
    ai_provider: Literal["openai", "anthropic", "ollama", "google", "openai_compatible"] = Field(default="openai")

    # OpenAI
    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="gpt-4o")

    # Anthropic
    anthropic_api_key: str = Field(default="")
    anthropic_model: str = Field(default="claude-sonnet-4-20250514")

    # Ollama
    ollama_host: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="llama3.1")

    # Google (Gemini)
    google_api_key: str = Field(default="")
    google_model: str = Field(default="gemini-2.0-flash-exp")

    # OpenAI-compatible (OpenWebUI, llama.cpp, LM Studio, vLLM, etc.)
    openai_compatible_host: str = Field(default="http://localhost:8080/v1")
    openai_compatible_api_key: str = Field(default="")  # Optional for some servers
    openai_compatible_model: str = Field(default="")

    # Home Assistant
    ha_url: str = Field(default="http://localhost:8123")
    ha_token: str = Field(default="")
    excluded_entities: str = Field(default="")

    # Rate limiting
    max_tokens_per_response: int = Field(default=4096)
    requests_per_minute: int = Field(default=20)

    # Safety guardrails (0-100, higher = stricter, 0 = disabled)
    guardrails_threshold: int = Field(default=70)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Settings cache
_settings_cache: Optional[Settings] = None


def clear_settings_cache() -> None:
    """Clear settings cache. Call after configuration changes."""
    global _settings_cache
    _settings_cache = None


def is_configured() -> bool:
    """Check if application has been configured via setup wizard."""
    from app.setup.storage import ConfigStorage
    storage = ConfigStorage()
    return storage.exists()


def get_settings() -> Settings:
    """Get settings - prioritizes encrypted storage over environment variables.

    Returns:
        Settings instance loaded from encrypted storage if available,
        otherwise from environment variables.
    """
    global _settings_cache

    if _settings_cache is not None:
        return _settings_cache

    # Try to load from encrypted storage first
    try:
        from app.setup.storage import ConfigStorage
        storage = ConfigStorage()
        stored_config = storage.load()

        if stored_config:
            # Build settings from stored config
            settings_dict = {
                "app_name": stored_config.app_name,
                "ai_provider": stored_config.provider.provider.value,
                "max_tokens_per_response": stored_config.limits.max_tokens_per_response,
                "requests_per_minute": stored_config.limits.requests_per_minute,
                "guardrails_threshold": getattr(stored_config.limits, 'guardrails_threshold', 70),
                "ha_url": stored_config.home_assistant.url,
                "ha_token": stored_config.home_assistant.token,
                "excluded_entities": getattr(stored_config, "excluded_entities", ""),
            }

            # Provider-specific settings
            provider = stored_config.provider
            if provider.provider.value == "openai":
                settings_dict["openai_api_key"] = provider.api_key or ""
                settings_dict["openai_model"] = provider.model
            elif provider.provider.value == "anthropic":
                settings_dict["anthropic_api_key"] = provider.api_key or ""
                settings_dict["anthropic_model"] = provider.model
            elif provider.provider.value == "ollama":
                settings_dict["ollama_host"] = provider.host or "http://localhost:11434"
                settings_dict["ollama_model"] = provider.model
            elif provider.provider.value == "google":
                settings_dict["google_api_key"] = provider.api_key or ""
                settings_dict["google_model"] = provider.model
            elif provider.provider.value == "openai_compatible":
                settings_dict["openai_compatible_host"] = provider.host or ""
                settings_dict["openai_compatible_api_key"] = provider.api_key or ""
                settings_dict["openai_compatible_model"] = provider.model

            _settings_cache = Settings(**settings_dict)
            return _settings_cache
    except Exception:
        # If encrypted storage fails, fall back to env
        pass

    # Fall back to environment-based settings
    _settings_cache = Settings()
    return _settings_cache
