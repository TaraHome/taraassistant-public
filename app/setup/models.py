"""Pydantic models for setup wizard."""
from enum import Enum
from typing import Optional, List

from pydantic import BaseModel, Field, field_validator


class AIProvider(str, Enum):
    """Supported AI providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"
    GOOGLE = "google"
    OPENAI_COMPATIBLE = "openai_compatible"  # For OpenWebUI, llama.cpp, LM Studio, vLLM, etc.


class ProviderConfig(BaseModel):
    """AI provider configuration."""
    provider: AIProvider
    api_key: Optional[str] = None  # Not needed for Ollama, optional for OpenAI-compatible
    host: Optional[str] = None     # For Ollama and OpenAI-compatible (base URL)
    model: str

    @field_validator("api_key")
    @classmethod
    def validate_api_key_required(cls, v, info):
        """Ensure API key is provided for providers that require it."""
        provider = info.data.get("provider")
        # OpenAI, Anthropic, Google require API key
        # Ollama doesn't need one
        # OpenAI-compatible: optional (some servers require it, some don't)
        if provider in [AIProvider.OPENAI, AIProvider.ANTHROPIC, AIProvider.GOOGLE] and not v:
            raise ValueError(f"API key required for {provider}")
        return v

    @field_validator("host")
    @classmethod
    def validate_host_required(cls, v, info):
        """Ensure host is provided for providers that require it."""
        provider = info.data.get("provider")
        if provider in [AIProvider.OLLAMA, AIProvider.OPENAI_COMPATIBLE] and not v:
            raise ValueError(f"Host URL required for {provider}")
        return v


class LimitsConfig(BaseModel):
    """Rate limiting and token configuration."""
    max_tokens_per_response: int = Field(default=4096, ge=100, le=32000)
    requests_per_minute: int = Field(default=20, ge=1, le=100)
    guardrails_threshold: int = Field(default=70, ge=0, le=100)  # 0 = disabled


class HomeAssistantConfig(BaseModel):
    """Home Assistant connection configuration."""
    url: str
    token: str

    @field_validator("url")
    @classmethod
    def validate_url(cls, v):
        """Ensure URL has proper protocol and strip trailing slash."""
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v.rstrip("/")


class StoredConfig(BaseModel):
    """Complete stored configuration."""
    provider: ProviderConfig
    limits: LimitsConfig
    home_assistant: HomeAssistantConfig
    app_name: str = "TaraHome AI Assistant"
    excluded_entities: str = ""


# Request/Response models for validation endpoints

class ValidateProviderRequest(BaseModel):
    """Request to validate AI provider credentials."""
    provider: AIProvider
    api_key: Optional[str] = None
    host: Optional[str] = None


class ValidateProviderResponse(BaseModel):
    """Response from provider validation."""
    valid: bool
    models: List[str] = []
    error: Optional[str] = None


class ValidateHARequest(BaseModel):
    """Request to validate Home Assistant connection."""
    url: str
    token: str


class ValidateHAResponse(BaseModel):
    """Response from HA validation."""
    valid: bool
    version: Optional[str] = None
    error: Optional[str] = None


class SetupStatusResponse(BaseModel):
    """Response for setup status check."""
    configured: bool


class SaveConfigRequest(BaseModel):
    """Request to save configuration."""
    provider: ProviderConfig
    limits: LimitsConfig
    home_assistant: HomeAssistantConfig
    app_name: str = "TaraHome AI Assistant"
    excluded_entities: str = ""


class SaveLimitsRequest(BaseModel):
    """Request to save only limits configuration (no re-authentication required)."""
    limits: LimitsConfig
