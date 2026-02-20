"""Setup wizard API routes."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app.setup.models import (
    AIProvider,
    ValidateProviderRequest,
    ValidateProviderResponse,
    ValidateHARequest,
    ValidateHAResponse,
    SaveConfigRequest,
    SaveLimitsRequest,
    SetupStatusResponse,
    StoredConfig,
    ProviderConfig,
    LimitsConfig,
    HomeAssistantConfig,
)
from app.setup.validators import ProviderValidator, HomeAssistantValidator
from app.setup.storage import ConfigStorage
from app.setup.templates import get_setup_html, get_limits_html


# API routes
router = APIRouter(prefix="/api/setup", tags=["setup"])

# HTML page routes
page_router = APIRouter(tags=["setup-pages"])


@page_router.get("/setup", response_class=HTMLResponse)
async def setup_page():
    """Serve the setup wizard UI."""
    return get_setup_html()


@page_router.get("/settings", response_class=HTMLResponse)
async def settings_page():
    """Serve settings page (reuses setup wizard with pre-filled values)."""
    storage = ConfigStorage()
    if not storage.exists():
        return RedirectResponse(url="/setup")

    config = storage.load()
    return get_setup_html(existing_config=config)


@page_router.get("/settings/limits", response_class=HTMLResponse)
async def limits_page():
    """Serve quick limits settings page (no re-authentication required)."""
    storage = ConfigStorage()
    if not storage.exists():
        return RedirectResponse(url="/setup")

    config = storage.load()
    return get_limits_html(existing_config=config)


@router.get("/status", response_model=SetupStatusResponse)
async def setup_status():
    """Check if setup has been completed."""
    storage = ConfigStorage()
    return SetupStatusResponse(configured=storage.exists())


@router.post("/validate/provider", response_model=ValidateProviderResponse)
async def validate_provider(request: ValidateProviderRequest):
    """Validate AI provider credentials and return available models."""
    valid, models, error = await ProviderValidator.validate(
        provider=request.provider,
        api_key=request.api_key,
        host=request.host
    )
    return ValidateProviderResponse(valid=valid, models=models, error=error)


@router.post("/validate/home-assistant", response_model=ValidateHAResponse)
async def validate_home_assistant(request: ValidateHARequest):
    """Validate Home Assistant connection."""
    valid, version, error = await HomeAssistantValidator.validate(
        url=request.url,
        token=request.token
    )
    return ValidateHAResponse(valid=valid, version=version, error=error)


@router.post("/save")
async def save_config(request: SaveConfigRequest):
    """Save configuration (encrypted)."""
    try:
        storage = ConfigStorage()
        existing_config = storage.load()
        excluded_entities = request.excluded_entities
        if not excluded_entities and existing_config:
            excluded_entities = existing_config.excluded_entities

        # Build StoredConfig from request
        config = StoredConfig(
            provider=request.provider,
            limits=request.limits,
            home_assistant=request.home_assistant,
            app_name=request.app_name,
            excluded_entities=excluded_entities
        )
        storage.save(config)

        # Clear caches so new config is loaded
        from app.config import clear_settings_cache
        from app.main import clear_agent_cache
        clear_settings_cache()
        clear_agent_cache()

        return {"success": True, "message": "Configuration saved successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save configuration: {str(e)}")


@router.post("/save-limits")
async def save_limits(request: SaveLimitsRequest):
    """Save only limits configuration (no re-authentication required).

    This endpoint merges the new limits with the existing configuration,
    allowing users to adjust thresholds without re-entering API keys.
    """
    storage = ConfigStorage()
    existing_config = storage.load()

    if not existing_config:
        raise HTTPException(
            status_code=400,
            detail="No existing configuration found. Please complete full setup first."
        )

    try:
        # Merge new limits with existing config
        updated_config = StoredConfig(
            provider=existing_config.provider,
            limits=request.limits,
            home_assistant=existing_config.home_assistant,
            app_name=existing_config.app_name,
            excluded_entities=existing_config.excluded_entities
        )

        storage.save(updated_config)

        # Clear caches so new config is loaded
        from app.config import clear_settings_cache
        from app.main import clear_agent_cache
        clear_settings_cache()
        clear_agent_cache()

        return {"success": True, "message": "Limits updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save limits: {str(e)}")


@router.delete("/reset")
async def reset_config():
    """Reset configuration (requires re-setup)."""
    storage = ConfigStorage()
    deleted = storage.delete()

    if deleted:
        from app.config import clear_settings_cache
        from app.main import clear_agent_cache
        clear_settings_cache()
        clear_agent_cache()

    return {
        "success": True,
        "message": "Configuration reset" if deleted else "No configuration to reset"
    }


@router.get("/current")
async def get_current_config():
    """Get current configuration (without sensitive data)."""
    storage = ConfigStorage()
    config = storage.load()

    if not config:
        raise HTTPException(status_code=404, detail="No configuration found")

    # Return config without sensitive data
    return {
        "provider": config.provider.provider.value,
        "model": config.provider.model,
        "limits": config.limits.model_dump(),
        "home_assistant_url": config.home_assistant.url,
        "app_name": config.app_name,
        "excluded_entities": config.excluded_entities
    }
