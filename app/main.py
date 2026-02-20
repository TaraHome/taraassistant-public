"""FastAPI web server for TaraHome AI Assistant."""
import asyncio
import json
import logging
import re
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, List

from app.config import get_settings, is_configured
from app.memory import get_memory
from app.usage import get_usage_tracker

# Setup wizard routes
from app.setup.routes import router as setup_api_router, page_router as setup_page_router

# Middleware
from app.middleware.rate_limiter import RateLimiterMiddleware
from app.middleware.setup_redirect import SetupRedirectMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management - start/stop background tasks."""
    # Startup
    if is_configured():
        try:
            from app.patterns.scheduler import init_pattern_scheduler
            settings = get_settings()
            if settings.ha_url and settings.ha_token:
                scheduler = init_pattern_scheduler(settings.ha_url, settings.ha_token)
                scheduler.start()
                logger.info("Pattern tracking scheduler started")
        except Exception as e:
            logger.warning(f"Pattern scheduler failed to start: {e}")

    yield

    # Shutdown
    try:
        from app.patterns.scheduler import stop_pattern_scheduler
        stop_pattern_scheduler()
        logger.info("Pattern tracking scheduler stopped")
    except Exception:
        pass


# Initialize FastAPI app
app = FastAPI(
    title="TaraHome AI Assistant",
    description="AI-powered Home Assistant controller",
    version="1.0.0",
    lifespan=lifespan
)

# CORS - allow all origins for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add custom middleware (order matters - last added runs first)
# Rate limiter uses settings, so we need to get fresh settings
settings = get_settings()
app.add_middleware(RateLimiterMiddleware, requests_per_minute=settings.requests_per_minute)
app.add_middleware(SetupRedirectMiddleware)

# Include setup wizard routes
app.include_router(setup_api_router)
app.include_router(setup_page_router)

# Lazy-loaded agent (only initialize when configured)
_agent = None


def get_agent():
    """Get or create the Home Assistant agent."""
    global _agent
    if _agent is None:
        from app.agents.home_assistant_agent import HomeAssistantAgent
        _agent = HomeAssistantAgent()
    return _agent


def clear_agent_cache():
    """Clear the agent cache. Call after settings change."""
    global _agent
    _agent = None


def _infer_domains_from_text(text):
    keyword_domains = [
        ("light", "light"),
        ("lights", "light"),
        ("tts", "tts"),
        ("speak", "tts"),
        ("announce", "tts"),
        ("announcement", "tts"),
        ("media", "media_player"),
        ("music", "media_player"),
        ("play", "media_player"),
        ("volume", "media_player"),
        ("climate", "climate"),
        ("temp", "climate"),
        ("temperature", "climate"),
        ("heat", "climate"),
        ("cool", "climate"),
        ("lock", "lock"),
        ("unlock", "lock"),
        ("door", "lock"),
        ("cover", "cover"),
        ("blind", "cover"),
        ("shade", "cover"),
        ("fan", "fan"),
        ("switch", "switch"),
        ("plug", "switch"),
        ("automation", "automation")
    ]
    matched = set()
    for keyword, domain in keyword_domains:
        if keyword in text:
            matched.add(domain)
    return matched


def _filter_actions_by_context(actions, available_domains, entity_names, allowed_script_names):
    if not actions or not available_domains:
        return []

    filtered = []
    for action in actions:
        label = str(action.get("label", ""))
        command = str(action.get("command", ""))
        description = str(action.get("description", ""))
        text = f"{label} {command} {description}".lower()

        if "script" in text or text.strip().startswith("run "):
            if allowed_script_names and any(name in text for name in allowed_script_names):
                filtered.append(action)
            continue

        matched_domains = _infer_domains_from_text(text)
        if matched_domains:
            if matched_domains & available_domains:
                filtered.append(action)
            continue

        if any(name in text for name in entity_names):
            filtered.append(action)

    return filtered


def _fallback_quick_actions(entities, scripts):
    """Build simple quick actions from cached entities and scripts."""
    domain_templates = {
        "light": ("Lights On", "Turn on {name}", "Brighten {name}"),
        "switch": ("Turn Off", "Turn off {name}", "Power down {name}"),
        "fan": ("Fan Toggle", "Turn on {name}", "Airflow for {name}"),
        "media_player": ("Play Media", "Turn on {name}", "Start {name}"),
        "lock": ("Lock Door", "Lock {name}", "Secure {name}"),
        "cover": ("Close Cover", "Close {name}", "Lower {name}"),
        "climate": ("Set Climate", "Set {name} to 72 degrees", "Comfort for {name}"),
        "automation": ("Run Automation", "Run {name}", "Trigger {name}")
    }

    actions = []
    seen = set()
    for entity in entities:
        if entity.domain not in domain_templates:
            continue
        if entity.domain in seen:
            continue
        label, command_tpl, desc_tpl = domain_templates[entity.domain]
        name = entity.friendly_name
        actions.append({
            "label": label,
            "command": command_tpl.format(name=name),
            "description": desc_tpl.format(name=name)
        })
        seen.add(entity.domain)
        if len(actions) >= 4:
            break

    if scripts and len(actions) < 4:
        for script_id, alias in scripts:
            name = alias or script_id
            actions.append({
                "label": "Run Script",
                "command": f"Run {name}",
                "description": f"Trigger {name}"
            })
            if len(actions) >= 4:
                break

    return actions


def _load_scripts_metadata():
    """Read scripts.yaml and return script metadata with detected domains."""
    path = Path("scripts.yaml")
    if not path.exists():
        return []

    scripts = []
    current_id = None
    current_alias = None
    current_domains = set()
    for raw_line in path.read_text().splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" ") and line.endswith(":"):
            if current_id:
                scripts.append({
                    "id": current_id,
                    "alias": current_alias,
                    "domains": set(current_domains)
                })
            current_id = line.split(":", 1)[0].strip()
            current_alias = None
            current_domains = set()
            continue
        if current_id and line.lstrip().startswith("alias:"):
            current_alias = line.split("alias:", 1)[1].strip()
        if current_id:
            for match in re.findall(r"\b([a-z_]+)\.[a-z0-9_]+\b", line):
                current_domains.add(match)

    if current_id:
        scripts.append({
            "id": current_id,
            "alias": current_alias,
            "domains": set(current_domains)
        })

    return scripts


def _filter_scripts_by_domains(scripts, available_domains):
    if available_domains is None:
        return scripts
    filtered = []
    for script in scripts:
        domains = script.get("domains") or set()
        if domains and domains & available_domains:
            filtered.append(script)
    return filtered


def _load_scripts(available_domains=None) -> list[tuple[str, str | None]]:
    """Read scripts.yaml and return script id + alias list."""
    scripts = _load_scripts_metadata()
    scripts = _filter_scripts_by_domains(scripts, available_domains)
    return [(script["id"], script["alias"]) for script in scripts]


def _load_scripts_for_prompt(available_domains=None) -> list[str]:
    """Read scripts.yaml and return formatted script lines."""
    lines = []
    for script_id, alias in _load_scripts(available_domains):
        name = alias or script_id
        lines.append(f"- {name}: script.{script_id}")
    return lines


def _to_ws_url(ha_url: str) -> str:
    parsed = urlparse(ha_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = parsed.path.rstrip("/")
    if not path:
        path = ""
    return f"{scheme}://{parsed.netloc}{path}/api/websocket"


async def _fetch_ha_registry_maps(
    ha_url: str,
    ha_token: str,
) -> tuple[dict[str, str], dict[str, str]]:
    """Fetch entity->device_id and device_id->device_name maps from HA websocket API."""
    try:
        import websockets
    except Exception:
        return {}, {}

    ws_url = _to_ws_url(ha_url)
    entity_to_device_id: dict[str, str] = {}
    device_id_to_name: dict[str, str] = {}

    async with websockets.connect(
        ws_url,
        open_timeout=6,
        ping_timeout=6,
        max_size=None,  # HA registries can exceed default websocket frame limits
    ) as ws:
        auth_required = json.loads(await asyncio.wait_for(ws.recv(), timeout=4))
        if auth_required.get("type") != "auth_required":
            return {}, {}

        await ws.send(json.dumps({"type": "auth", "access_token": ha_token}))
        auth_response = json.loads(await asyncio.wait_for(ws.recv(), timeout=4))
        if auth_response.get("type") != "auth_ok":
            return {}, {}

        async def send_and_wait(msg_id: int, msg_type: str):
            await ws.send(json.dumps({"id": msg_id, "type": msg_type}))
            while True:
                data = json.loads(await asyncio.wait_for(ws.recv(), timeout=6))
                if data.get("id") == msg_id and data.get("type") == "result":
                    return data.get("result", [])

        devices = await send_and_wait(1, "config/device_registry/list")
        entities = await send_and_wait(2, "config/entity_registry/list")

        for device in devices or []:
            device_id = device.get("id")
            if not device_id:
                continue
            name = (
                device.get("name_by_user")
                or device.get("name")
                or device_id
            )
            device_id_to_name[device_id] = name

        for entity in entities or []:
            entity_id = entity.get("entity_id")
            device_id = entity.get("device_id")
            if entity_id and device_id:
                entity_to_device_id[entity_id] = device_id

    return entity_to_device_id, device_id_to_name


class ChatRequest(BaseModel):
    """Chat request model."""
    message: str
    session_id: Optional[str] = "default"


class ChatResponse(BaseModel):
    """Chat response model."""
    response: str
    success: bool = True
    session_id: str = "default"


class ExcludedEntitiesRequest(BaseModel):
    """Request model for updating excluded entities."""
    entity_ids: List[str] = []


@app.get("/", response_class=HTMLResponse)
async def home():
    """Serve the chat interface."""
    settings = get_settings()
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{settings.app_name}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=DM+Sans:ital,opsz,wght@0,9..40,100..1000;1,9..40,100..1000&display=swap" rel="stylesheet">
    <style>
        *, *::before, *::after {{ margin: 0; padding: 0; box-sizing: border-box; }}

        :root {{
            /* Typography */
            --font-primary: 'Outfit', system-ui, -apple-system, sans-serif;
            --font-secondary: 'DM Sans', system-ui, -apple-system, sans-serif;

            /* Warm Pastel Colors - Light Mode */
            --background: #fdfbf7;
            --foreground: #4a4137;

            /* Primary - Warm Coral */
            --primary: #ff9b85;
            --primary-light: #ffb5a3;
            --primary-dark: #f48171;
            --primary-foreground: #ffffff;

            /* Secondary - Soft Lavender */
            --secondary: #d4c5f9;
            --secondary-light: #e5dcfc;
            --secondary-dark: #c0afe6;
            --secondary-foreground: #4a4137;

            /* Accent - Soft Mint */
            --accent: #b8e6d5;
            --accent-light: #d1f0e3;
            --accent-dark: #a0d8c4;
            --accent-foreground: #4a4137;

            /* Info - Soft Sky Blue */
            --info: #a7d7f0;
            --info-light: #c5e6f7;
            --info-dark: #8fc7e3;
            --info-foreground: #4a4137;

            /* Warning - Soft Peach */
            --warning: #ffd89b;
            --warning-light: #ffe6b8;
            --warning-dark: #ffca7f;
            --warning-foreground: #4a4137;

            /* Error - Soft Rose */
            --error: #ffb3ba;
            --error-light: #ffd1d5;
            --error-dark: #ff9ba4;
            --error-foreground: #4a4137;

            /* Success - Soft Sage */
            --success: #c7e8b5;
            --success-light: #dcf1cd;
            --success-dark: #b5dd9f;
            --success-foreground: #4a4137;

            /* Neutrals */
            --muted: #f5f2ed;
            --muted-foreground: #8a8378;
            --card: #ffffff;
            --card-foreground: #4a4137;
            --border: #e8e4dc;
            --input-background: #faf8f4;

            /* Shadows - soft and subtle */
            --shadow-xs: 0 1px 2px 0 rgb(0 0 0 / 0.03);
            --shadow-sm: 0 2px 4px 0 rgb(0 0 0 / 0.04);
            --shadow-md: 0 4px 12px 0 rgb(0 0 0 / 0.05), 0 2px 4px 0 rgb(0 0 0 / 0.03);
            --shadow-lg: 0 8px 24px 0 rgb(0 0 0 / 0.06), 0 4px 8px 0 rgb(0 0 0 / 0.04);
            --shadow-xl: 0 16px 48px 0 rgb(0 0 0 / 0.08), 0 8px 16px 0 rgb(0 0 0 / 0.05);

            /* Radius tokens */
            --radius-sm: 0.5rem;
            --radius-md: 0.75rem;
            --radius-lg: 1rem;
            --radius-xl: 1.5rem;
            --radius-2xl: 2rem;
            --radius-full: 9999px;
        }}

        body.dark {{
            /* Dark mode - warm, cozy night theme */
            --background: #2a2520;
            --foreground: #f5f2ed;

            --primary: #ff9b85;
            --primary-light: #ffb5a3;
            --primary-dark: #f48171;
            --primary-foreground: #2a2520;

            --secondary: #b8a8e8;
            --secondary-light: #c9bced;
            --secondary-dark: #a594d8;
            --secondary-foreground: #f5f2ed;

            --accent: #92cdb8;
            --accent-light: #a7d9c7;
            --accent-dark: #7db9a5;
            --accent-foreground: #2a2520;

            --info: #8fc7e3;
            --info-light: #a7d7f0;
            --info-dark: #7ab5d3;
            --info-foreground: #2a2520;

            --warning: #ffca7f;
            --warning-light: #ffd89b;
            --warning-dark: #ffbc66;
            --warning-foreground: #2a2520;

            --error: #ff9ba4;
            --error-light: #ffb3ba;
            --error-dark: #ff8591;
            --error-foreground: #2a2520;

            --success: #b5dd9f;
            --success-light: #c7e8b5;
            --success-dark: #a3cf8b;
            --success-foreground: #2a2520;

            --muted: #3d3832;
            --muted-foreground: #a69d92;
            --card: #33302b;
            --card-foreground: #f5f2ed;
            --border: #4a453f;
            --input-background: #3d3832;

            --shadow-sm: 0 2px 4px rgba(0, 0, 0, 0.25);
            --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.3);
            --shadow-lg: 0 8px 24px rgba(0, 0, 0, 0.35);
            --shadow-xl: 0 16px 48px rgba(0, 0, 0, 0.4);
        }}

        body {{
            font-family: var(--font-secondary);
            font-size: 16px;
            line-height: 1.6;
            background: linear-gradient(135deg, #fff8f5 0%, #fdfbf7 25%, #f8f4ef 50%, #fef9f5 100%);
            min-height: 100vh;
            color: var(--foreground);
        }}

        body.dark {{
            background: linear-gradient(135deg, #332e28 0%, #2a2520 25%, #252119 50%, #2d2822 100%);
        }}

        h1, h2, h3, h4, h5, h6 {{
            font-family: var(--font-primary);
            font-weight: 600;
            line-height: 1.3;
            color: var(--foreground);
        }}

        h1 {{ font-size: 1.75rem; font-weight: 700; }}
        h2 {{ font-size: 1.25rem; }}
        h3 {{ font-size: 1.1rem; }}
        h4 {{ font-size: 1rem; font-weight: 500; }}

        /* Scrollbar styling */
        ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
        ::-webkit-scrollbar-track {{ background: transparent; }}
        ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: var(--radius-full); }}
        ::-webkit-scrollbar-thumb:hover {{ background: var(--muted-foreground); }}

        .app-shell {{
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }}

        .main-panel {{
            flex: 1;
            display: flex;
            flex-direction: column;
        }}

        /* ===== TOPBAR ===== */
        .topbar {{
            position: sticky;
            top: 0;
            z-index: 20;
            background: rgba(253, 251, 247, 0.85);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border-bottom: 1px solid var(--border);
        }}

        body.dark .topbar {{
            background: rgba(42, 37, 32, 0.85);
        }}

        .topbar-inner {{
            padding: 16px 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            max-width: 1600px;
            margin: 0 auto;
        }}

        .brand {{
            display: flex;
            align-items: center;
            gap: 14px;
        }}

        .brand-icon {{
            width: 48px;
            height: 48px;
            border-radius: var(--radius-lg);
            background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            color: #fff;
            font-family: var(--font-primary);
            font-weight: 700;
            font-size: 1.1rem;
            box-shadow: var(--shadow-md), 0 0 0 3px rgba(255, 155, 133, 0.15);
        }}

        .brand-meta h1 {{
            font-size: 1.25rem;
            margin-bottom: 2px;
        }}

        .brand-meta p {{
            color: var(--muted-foreground);
            font-size: 0.85rem;
        }}

        .header-actions {{
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }}

        .status-pill {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 14px;
            border-radius: var(--radius-full);
            background: var(--card);
            border: 1px solid var(--border);
            font-size: 0.8rem;
            font-weight: 500;
            box-shadow: var(--shadow-sm);
            color: var(--foreground);
        }}

        .status-dot {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--success);
            box-shadow: 0 0 0 3px rgba(199, 232, 181, 0.3);
            animation: statusPulse 2s ease-in-out infinite;
        }}

        @keyframes statusPulse {{
            0%, 100% {{ box-shadow: 0 0 0 3px rgba(199, 232, 181, 0.3); }}
            50% {{ box-shadow: 0 0 0 5px rgba(199, 232, 181, 0.15); }}
        }}

        .token-summary {{
            font-size: 0.8rem;
            color: var(--muted-foreground);
            padding: 8px 12px;
            background: var(--muted);
            border-radius: var(--radius-md);
        }}

        .header-btn {{
            border: none;
            background: var(--muted);
            color: var(--foreground);
            border-radius: var(--radius-md);
            padding: 8px 14px;
            cursor: pointer;
            font-family: var(--font-secondary);
            font-size: 0.8rem;
            font-weight: 500;
            transition: all 0.2s ease;
        }}

        .header-btn:hover {{
            background: var(--border);
            transform: translateY(-1px);
        }}

        .settings-link {{
            text-decoration: none;
            color: var(--foreground);
            border: 1px solid var(--border);
            padding: 8px 14px;
            border-radius: var(--radius-md);
            background: var(--card);
            font-size: 0.8rem;
            font-weight: 500;
            transition: all 0.2s ease;
        }}

        .settings-link:hover {{
            border-color: var(--primary);
            box-shadow: var(--shadow-sm);
        }}

        /* ===== CONTENT ===== */
        .content {{
            padding: 24px;
            display: flex;
            flex-direction: column;
            gap: 24px;
            max-width: 1200px;
            margin: 0 auto;
            width: 100%;
        }}

        /* ===== CARDS ===== */
        .card {{
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: var(--radius-xl);
            box-shadow: var(--shadow-md);
            color: var(--card-foreground);
            overflow: hidden;
        }}

        /* ===== CHAT CARD ===== */
        .chat-card {{
            padding: 24px;
            display: flex;
            flex-direction: column;
            gap: 20px;
        }}

        .chat-header {{
            display: flex;
            align-items: center;
            gap: 14px;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--border);
        }}

        .chat-header-icon {{
            width: 44px;
            height: 44px;
            border-radius: 50%;
            background: linear-gradient(135deg, var(--secondary) 0%, var(--accent) 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--secondary-foreground);
            font-family: var(--font-primary);
            font-weight: 700;
            font-size: 0.95rem;
            box-shadow: var(--shadow-sm);
        }}

        .chat-header-text h3 {{
            margin-bottom: 2px;
        }}

        .chat-header-text p {{
            color: var(--muted-foreground);
            font-size: 0.85rem;
        }}

        .chat-input {{
            display: flex;
            gap: 12px;
        }}

        .chat-input input {{
            flex: 1;
            padding: 14px 18px;
            background: var(--input-background);
            border: 2px solid var(--border);
            border-radius: var(--radius-lg);
            font-family: var(--font-secondary);
            font-size: 0.95rem;
            color: var(--foreground);
            transition: all 0.2s ease;
        }}

        .chat-input input::placeholder {{
            color: var(--muted-foreground);
        }}

        .chat-input input:focus {{
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 4px rgba(255, 155, 133, 0.15);
        }}

        .send-btn {{
            padding: 14px 24px;
            border: none;
            border-radius: var(--radius-lg);
            background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
            color: var(--primary-foreground);
            cursor: pointer;
            font-family: var(--font-secondary);
            font-weight: 600;
            font-size: 0.95rem;
            box-shadow: var(--shadow-sm), 0 0 0 1px rgba(255, 155, 133, 0.2);
            transition: all 0.2s ease;
        }}

        .send-btn:hover {{
            transform: translateY(-2px);
            box-shadow: var(--shadow-md), 0 0 0 1px rgba(255, 155, 133, 0.3);
        }}

        .send-btn:active {{
            transform: translateY(0);
        }}

        .send-btn:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }}

        /* ===== CHAT MESSAGES ===== */
        .chat-container {{
            display: flex;
            flex-direction: column;
            gap: 14px;
            max-height: 380px;
            overflow-y: auto;
            padding: 4px;
        }}

        .message {{
            padding: 14px 18px;
            border-radius: var(--radius-2xl);
            max-width: 80%;
            font-size: 0.95rem;
            line-height: 1.5;
            box-shadow: var(--shadow-sm);
            white-space: pre-wrap;
            word-wrap: break-word;
        }}

        .message.user {{
            background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
            color: var(--primary-foreground);
            align-self: flex-end;
            border-bottom-right-radius: var(--radius-sm);
        }}

        .message.assistant {{
            background: var(--card);
            border: 1px solid var(--border);
            color: var(--card-foreground);
            align-self: flex-start;
            border-bottom-left-radius: var(--radius-sm);
        }}

        .message.error {{
            background: var(--error-light);
            border: 1px solid var(--error);
            color: var(--error-foreground);
            align-self: flex-start;
        }}

        .typing {{
            align-self: flex-start;
            display: inline-flex;
            gap: 5px;
            padding: 16px 20px;
            border-radius: var(--radius-2xl);
            border-bottom-left-radius: var(--radius-sm);
            background: var(--card);
            border: 1px solid var(--border);
            box-shadow: var(--shadow-sm);
        }}

        .typing span {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--secondary);
            animation: typingBounce 1.4s infinite ease-in-out;
        }}

        .typing span:nth-child(1) {{ animation-delay: 0s; }}
        .typing span:nth-child(2) {{ animation-delay: 0.15s; }}
        .typing span:nth-child(3) {{ animation-delay: 0.3s; }}

        @keyframes typingBounce {{
            0%, 60%, 100% {{ transform: translateY(0); opacity: 0.4; }}
            30% {{ transform: translateY(-6px); opacity: 1; }}
        }}

        /* ===== GRID LAYOUT ===== */
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 24px;
            align-items: start;
        }}

        .section-title {{
            font-size: 1rem;
            margin-bottom: 14px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .section-title::before {{
            content: '';
            width: 4px;
            height: 18px;
            background: linear-gradient(180deg, var(--primary), var(--secondary));
            border-radius: var(--radius-full);
        }}

        /* ===== ACTION CARDS ===== */
        .action-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 12px;
        }}

        .action-card {{
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: var(--radius-xl);
            box-shadow: var(--shadow-sm);
            color: var(--foreground);
            padding: 18px;
            cursor: pointer;
            transition: all 0.25s ease;
            text-align: left;
            width: 100%;
            display: flex;
            flex-direction: column;
            gap: 6px;
            font-family: var(--font-secondary);
        }}

        .action-card:hover {{
            transform: translateY(-3px);
            box-shadow: var(--shadow-lg);
        }}

        .action-card:active {{
            transform: translateY(-1px) scale(0.98);
        }}

        .action-card.variant-primary {{
            background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
            border-color: transparent;
            color: var(--primary-foreground);
        }}

        .action-card.variant-secondary {{
            background: linear-gradient(135deg, var(--secondary) 0%, var(--secondary-dark) 100%);
            border-color: transparent;
            color: var(--secondary-foreground);
        }}

        .action-card.variant-accent {{
            background: linear-gradient(135deg, var(--accent) 0%, var(--accent-dark) 100%);
            border-color: transparent;
            color: var(--accent-foreground);
        }}

        .action-card.variant-info {{
            background: linear-gradient(135deg, var(--info) 0%, var(--info-dark) 100%);
            border-color: transparent;
            color: var(--info-foreground);
        }}

        .action-card.variant-warning {{
            background: linear-gradient(135deg, var(--warning) 0%, var(--warning-dark) 100%);
            border-color: transparent;
            color: var(--warning-foreground);
        }}

        .action-card.variant-primary .action-desc,
        .action-card.variant-secondary .action-desc,
        .action-card.variant-accent .action-desc,
        .action-card.variant-info .action-desc,
        .action-card.variant-warning .action-desc {{
            opacity: 0.85;
        }}

        .action-card:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }}

        .action-title {{
            font-family: var(--font-primary);
            font-weight: 600;
            font-size: 0.95rem;
            word-break: break-word;
        }}

        .action-desc {{
            font-size: 0.8rem;
            opacity: 0.7;
            word-break: break-word;
        }}

        .action-empty {{
            font-size: 0.85rem;
            color: var(--muted-foreground);
            padding: 16px;
            text-align: center;
            background: var(--muted);
            border-radius: var(--radius-lg);
        }}

        /* ===== DEVICE STATUS ===== */
        .status-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 14px;
        }}

        .status-count {{
            font-size: 0.8rem;
            color: var(--muted-foreground);
            background: var(--muted);
            padding: 4px 10px;
            border-radius: var(--radius-full);
        }}

        .device-list {{
            display: flex;
            flex-direction: column;
            gap: 8px;
            overflow-y: auto;
            padding: 2px;
        }}

        .device-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            padding: 10px 12px;
            border: 1px solid var(--border);
            border-radius: var(--radius-lg);
            background: var(--card);
            transition: all 0.2s ease;
        }}

        .device-row:hover {{
            border-color: var(--primary-light);
            box-shadow: var(--shadow-sm);
        }}

        .device-meta {{
            display: flex;
            flex-direction: column;
            gap: 2px;
            min-width: 0;
            flex: 1;
            overflow: hidden;
        }}

        .device-meta > div:first-child {{
            font-weight: 500;
            font-size: 0.85rem;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}

        .device-domain {{
            font-size: 0.65rem;
            color: var(--muted-foreground);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            font-weight: 500;
        }}

        .device-state {{
            font-size: 0.7rem;
            color: var(--muted-foreground);
            background: var(--muted);
            padding: 4px 10px;
            border-radius: var(--radius-full);
            text-transform: capitalize;
            font-weight: 500;
            white-space: nowrap;
            flex-shrink: 0;
        }}

        .device-state.on, .device-state.playing {{
            background: var(--success-light);
            color: var(--success-foreground);
        }}

        .device-state.off, .device-state.unavailable {{
            background: var(--muted);
            color: var(--muted-foreground);
        }}


        /* ===== INSIGHTS PANEL ===== */
        .insights-panel {{
            position: fixed;
            top: 0;
            right: 0;
            width: 380px;
            height: 100%;
            background: var(--background);
            border-left: 1px solid var(--border);
            padding: 24px;
            transform: translateX(100%);
            transition: transform 0.3s ease;
            z-index: 30;
            display: flex;
            flex-direction: column;
            gap: 20px;
            box-shadow: var(--shadow-xl);
            overflow: visible;
        }}

        .insights-panel.visible {{
            transform: translateX(0);
        }}

        .panel-toggle-arrow {{
            position: absolute;
            left: 0;
            top: 80px;
            transform: translateX(-100%);
            background: var(--card);
            border: 1px solid var(--border);
            border-right: none;
            border-radius: var(--radius-md) 0 0 var(--radius-md);
            padding: 12px 8px;
            cursor: pointer;
            box-shadow: var(--shadow-md);
            transition: background 0.2s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 31;
        }}

        .panel-toggle-arrow:hover {{
            background: var(--muted);
        }}

        .panel-toggle-arrow svg {{
            width: 20px;
            height: 20px;
            transition: transform 0.3s ease;
            color: var(--foreground);
        }}

        .insights-panel.visible .panel-toggle-arrow svg {{
            transform: rotate(180deg);
        }}

        .panel-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}

        .panel-header h3 {{
            font-size: 1.1rem;
        }}

        .panel-header button {{
            border: none;
            background: var(--muted);
            color: var(--foreground);
            border-radius: var(--radius-md);
            padding: 8px 14px;
            cursor: pointer;
            font-family: var(--font-secondary);
            font-size: 0.8rem;
            font-weight: 500;
            transition: all 0.2s ease;
        }}

        .panel-header button:hover {{
            background: var(--border);
        }}

        .chart-container {{
            height: 160px;
            background: var(--muted);
            border-radius: var(--radius-lg);
            padding: 12px;
        }}

        .log-tabs {{
            display: flex;
            gap: 8px;
        }}

        .log-tab {{
            flex: 1;
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            padding: 10px 12px;
            background: var(--card);
            cursor: pointer;
            font-family: var(--font-secondary);
            font-size: 0.8rem;
            font-weight: 500;
            color: var(--foreground);
            transition: all 0.2s ease;
        }}

        .log-tab:hover {{
            border-color: var(--primary-light);
        }}

        .log-tab.active {{
            background: linear-gradient(135deg, var(--primary), var(--primary-dark));
            color: var(--primary-foreground);
            border-color: transparent;
        }}

        .logs-container {{
            flex: 1;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 12px;
            padding: 2px;
        }}

        .log-entry {{
            border: 1px solid var(--border);
            border-radius: var(--radius-lg);
            padding: 14px;
            background: var(--card);
            font-size: 0.85rem;
        }}

        .log-header {{
            display: flex;
            justify-content: space-between;
            gap: 12px;
            color: var(--muted-foreground);
            font-size: 0.75rem;
        }}

        .log-toggle {{
            margin-top: 10px;
            font-weight: 600;
            cursor: pointer;
            color: var(--primary);
            font-size: 0.8rem;
            transition: color 0.2s ease;
        }}

        .log-toggle:hover {{
            color: var(--primary-dark);
        }}

        .log-content {{
            margin-top: 10px;
            padding: 12px;
            background: var(--muted);
            border-radius: var(--radius-md);
            white-space: pre-wrap;
            font-family: 'SF Mono', 'Monaco', 'Inconsolata', monospace;
            font-size: 0.75rem;
            line-height: 1.5;
            max-height: 200px;
            overflow-y: auto;
        }}

        /* ===== RESPONSIVE ===== */
        @media (min-width: 1024px) {{
            .app-shell {{
                flex-direction: row;
            }}

            .main-panel {{
                flex: 1;
                max-width: calc(100% - 380px);
            }}

            .insights-panel {{
                position: relative;
                transform: none;
                box-shadow: none;
                height: auto;
                min-height: 100vh;
            }}

            .insights-panel.collapsed {{
                width: 0;
                padding: 0;
                border-left: none;
            }}

            .insights-panel.collapsed > *:not(.panel-toggle-arrow) {{
                display: none;
            }}

            .insights-panel.collapsed .panel-toggle-arrow {{
                display: flex;
            }}

            .main-panel.expanded {{
                max-width: 100%;
            }}

            .panel-toggle {{
                display: none;
            }}

            .panel-toggle-arrow {{
                display: flex;
            }}
        }}

        @media (max-width: 768px) {{
            .topbar-inner {{
                flex-direction: column;
                align-items: flex-start;
                gap: 12px;
            }}

            .header-actions {{
                width: 100%;
                justify-content: flex-start;
            }}

            .content {{
                padding: 16px;
            }}

            .grid {{
                grid-template-columns: 1fr;
            }}

            .chat-input {{
                flex-direction: column;
            }}

            .send-btn {{
                width: 100%;
            }}

            .message {{
                max-width: 90%;
            }}

        }}
    </style>
</head>
<body>
    <div class="app-shell">
        <div class="main-panel">
            <header class="topbar">
                <div class="topbar-inner">
                    <div class="brand">
                        <div class="brand-icon">TH</div>
                        <div class="brand-meta">
                            <h1>{settings.app_name}</h1>
                            <p>Your cozy smart home companion</p>
                        </div>
                    </div>
                    <div class="header-actions">
                        <span class="status-pill">
                            <span class="status-dot"></span>
                            {settings.ai_provider.title()}
                        </span>
                        <span class="token-summary" id="token-summary">Tokens: --</span>
                        <button class="header-btn" onclick="toggleTheme()" id="theme-toggle">Dark mode</button>
                        <button class="header-btn panel-toggle" onclick="togglePanel()" id="panel-toggle">Insights</button>
                        <a href="/settings" class="settings-link">Settings</a>
                    </div>
                </div>
            </header>

            <section class="content">
                <div class="card chat-card">
                    <div class="chat-header">
                        <div class="chat-header-icon">AI</div>
                        <div class="chat-header-text">
                            <h3>AI Assistant</h3>
                            <p>Ready to help with your home</p>
                        </div>
                    </div>

                    <div class="chat-input">
                        <input type="text" id="input" placeholder="Ask me anything about your home..." />
                        <button id="send" class="send-btn" onclick="sendMessage()">Send</button>
                    </div>

                    <div class="chat-container" id="chat">
                        <div class="message assistant">
                            Hi! I'm your TaraHome AI Assistant. I can control your smart home, manage automations, and help you with anything home-related.
                        </div>
                    </div>
                </div>

                <!-- Usage Insights Section -->
                <div id="usage-insights-card" class="card" style="padding: 20px; margin-top: 24px;">
                    <div class="status-header">
                        <h3 class="section-title">Usage Insights</h3>
                        <div style="display: flex; gap: 8px; align-items: center;">
                            <button class="header-btn" onclick="syncPatterns()" style="padding: 6px 12px; font-size: 0.75rem; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--card); cursor: pointer;">Sync Now</button>
                            <span id="insights-sync-status" class="status-count">Not synced</span>
                        </div>
                    </div>
                    <p style="color: var(--muted-foreground); font-size: 0.85rem; margin: 10px 0 16px 0;">
                        Learning from your device usage to suggest smart automations
                    </p>
                    <!-- Detected Patterns -->
                    <div id="detected-patterns-section">
                        <h4 style="font-size: 0.9rem; margin-bottom: 10px; color: var(--foreground); font-weight: 500;">
                            Detected Patterns
                        </h4>
                        <div id="patterns-list" class="device-list"></div>
                        <div id="patterns-empty" class="action-empty" style="font-size: 0.85rem;">
                            No patterns detected yet. Keep using your devices!
                        </div>
                    </div>
                    <!-- Behavior-Based Suggestions -->
                    <div id="behavior-suggestions-section" style="margin-top: 20px;">
                        <h4 style="font-size: 0.9rem; margin-bottom: 10px; color: var(--foreground); font-weight: 500;">
                            Learned Automation Ideas
                        </h4>
                        <div id="behavior-suggestions-grid" class="action-grid"></div>
                        <div id="behavior-suggestions-empty" class="action-empty" style="font-size: 0.85rem;">
                            Learning your patterns... Check back after a few days of usage.
                        </div>
                    </div>
                </div>

                <div class="grid">
                    <div id="actions-card" class="card" style="padding: 20px;">
                        <h2 class="section-title">Quick Actions</h2>
                        <div id="quick-actions" class="action-grid"></div>
                        <div id="quick-actions-empty" class="action-empty">Loading quick actions...</div>
                        <h3 class="section-title" style="margin-top: 24px;">Automation Ideas</h3>
                        <p style="color: var(--muted-foreground); font-size: 0.85rem; margin-bottom: 14px;">Click to set up these automations</p>
                        <div id="suggested-actions" class="action-grid"></div>
                        <div id="suggested-actions-empty" class="action-empty">Generating automation ideas...</div>
                    </div>

                    <div id="devices-card" class="card" style="padding: 20px;">
                        <div class="status-header">
                            <h3 class="section-title">Devices</h3>
                            <div style="display: flex; gap: 8px; align-items: center;">
                                <button class="header-btn" onclick="syncDevices()" style="padding: 6px 12px; font-size: 0.75rem; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--card); cursor: pointer;">Sync Now</button>
                                <button class="header-btn" onclick="window.location.href='/devices-manager'" style="padding: 6px 12px; font-size: 0.75rem; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--card); cursor: pointer;">Manage</button>
                                <span id="device-count" class="status-count">Loading...</span>
                            </div>
                        </div>
                        <div class="device-controls" style="display: grid; gap: 8px; margin: 10px 0 12px 0;">
                            <input
                                type="text"
                                id="device-filter-text"
                                placeholder="Search devices by name, ID, or domain"
                                style="width: 100%; padding: 8px 10px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--background); color: var(--foreground); font-size: 0.8rem;"
                                oninput="renderDeviceList()"
                            />
                            <label style="display: flex; align-items: center; gap: 8px; font-size: 0.8rem; color: var(--muted-foreground);">
                                <input type="checkbox" id="show-excluded-toggle" onchange="renderDeviceList()" />
                                Show excluded devices
                            </label>
                        </div>
                        <div id="device-status-list" class="device-list"></div>
                    </div>
                </div>
            </section>
        </div>

        <aside class="insights-panel" id="side-panel">
            <!-- Toggle Arrow -->
            <button class="panel-toggle-arrow" onclick="togglePanel()">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="15 18 9 12 15 6"></polyline>
                </svg>
            </button>
            <div class="panel-header">
                <h3>Insights</h3>
                <button onclick="clearLogs()">Clear</button>
            </div>
            <div class="chart-container">
                <canvas id="tokenChart"></canvas>
            </div>
            <div class="log-tabs">
                <button class="log-tab active" id="llm-tab" onclick="switchLogTab('llm')">LLM Logs</button>
                <button class="log-tab" id="ha-tab" onclick="switchLogTab('ha')">HA API</button>
            </div>
            <div class="logs-container" id="logs-container">
                <p style="color: var(--muted-foreground); font-size: 0.85rem; text-align: center; padding: 20px;">No logs yet</p>
            </div>
        </aside>
    </div>

    <script>
        const chat = document.getElementById('chat');
        const input = document.getElementById('input');
        const sendBtn = document.getElementById('send');
        let tokenChart = null;
        let panelVisible = false;
        let allDevices = [];

        input.addEventListener('keypress', e => {{
            if (e.key === 'Enter') sendMessage();
        }});

        function addMessage(text, type) {{
            const msg = document.createElement('div');
            msg.className = 'message ' + type;
            msg.textContent = text;
            chat.appendChild(msg);
            chat.scrollTop = chat.scrollHeight;
        }}

        function escapeHtml(value) {{
            const div = document.createElement('div');
            div.textContent = value ?? '';
            return div.innerHTML;
        }}

        function showTyping() {{
            const t = document.createElement('div');
            t.className = 'typing';
            t.id = 'typing';
            t.innerHTML = '<span></span><span></span><span></span>';
            chat.appendChild(t);
            chat.scrollTop = chat.scrollHeight;
        }}

        function hideTyping() {{
            const t = document.getElementById('typing');
            if (t) t.remove();
        }}

        function send(text) {{
            input.value = text;
            sendMessage();
        }}

        async function sendMessage() {{
            const text = input.value.trim();
            if (!text) return;

            addMessage(text, 'user');
            input.value = '';
            sendBtn.disabled = true;
            showTyping();

            try {{
                const res = await fetch('/api/chat', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{message: text}})
                }});

                hideTyping();
                const data = await res.json();

                if (res.status === 429) {{
                    addMessage('Rate limit exceeded. Please wait.', 'error');
                }} else if (data.success) {{
                    addMessage(data.response, 'assistant');
                }} else {{
                    addMessage('Error: ' + (data.response || 'Unknown error'), 'error');
                }}

                if (panelVisible) {{
                    loadUsageData();
                    loadLogs();
                }}
                updateTokenSummary();
            }} catch (e) {{
                hideTyping();
                addMessage('Connection error.', 'error');
            }}

            sendBtn.disabled = false;
            input.focus();
        }}

        function togglePanel() {{
            const panel = document.getElementById('side-panel');
            const btn = document.getElementById('panel-toggle');
            const mainPanel = document.querySelector('.main-panel');
            const isDesktop = window.innerWidth >= 1024;

            if (isDesktop) {{
                // Desktop: toggle collapsed class based on current state
                const isCollapsed = panel.classList.contains('collapsed');
                if (isCollapsed) {{
                    panel.classList.remove('collapsed');
                    if (mainPanel) mainPanel.classList.remove('expanded');
                    panelVisible = true;
                    loadUsageData();
                    loadLogs();
                }} else {{
                    panel.classList.add('collapsed');
                    if (mainPanel) mainPanel.classList.add('expanded');
                    panelVisible = false;
                }}
            }} else {{
                // Mobile: toggle visible class based on current state
                const isVisible = panel.classList.contains('visible');
                if (isVisible) {{
                    panel.classList.remove('visible');
                    if (btn) btn.classList.remove('active');
                    panelVisible = false;
                }} else {{
                    panel.classList.add('visible');
                    if (btn) btn.classList.add('active');
                    panelVisible = true;
                    loadUsageData();
                    loadLogs();
                }}
            }}
        }}

        function setTheme(isDark) {{
            document.body.classList.toggle('dark', isDark);
            localStorage.setItem('theme', isDark ? 'dark' : 'light');
            const btn = document.getElementById('theme-toggle');
            if (btn) {{
                btn.textContent = isDark ? 'Light mode' : 'Dark mode';
            }}
        }}

        function toggleTheme() {{
            const isDark = !document.body.classList.contains('dark');
            setTheme(isDark);
        }}

        async function loadUsageData() {{
            try {{
                const res = await fetch('/api/usage');
                const data = await res.json();
                updateChart(data.history);
            }} catch (e) {{
                console.error('Failed to load usage data:', e);
            }}
        }}

        async function loadLogs() {{
            try {{
                const res = await fetch('/api/logs');
                const data = await res.json();
                renderLogs(data.logs);
            }} catch (e) {{
                console.error('Failed to load logs:', e);
            }}
        }}

        async function loadQuickActions() {{
            const container = document.getElementById('quick-actions');
            const empty = document.getElementById('quick-actions-empty');
            if (!container || !empty) return;

            empty.textContent = 'Loading quick actions...';
            empty.style.display = 'block';
            container.innerHTML = '';

            try {{
                const res = await fetch('/api/ui/quick-actions');
                const data = await res.json();
                const actions = data.actions || [];

                if (!actions.length) {{
                    empty.textContent = data.message || 'No quick actions available.';
                    return;
                }}

                empty.style.display = 'none';

                function pickVariant(action) {{
                    const label = (action.label || '').toLowerCase();
                    const command = (action.command || '').toLowerCase();
                    if (label.includes('automation') || label.includes('script') || label.includes('run')) return 'warning';
                    if (label.includes('play') || label.includes('media')) return 'info';
                    if (command.includes('light') || label.includes('light')) return 'primary';
                    if (command.includes('temp') || command.includes('climate') || command.includes('heat')) return 'secondary';
                    if (command.includes('lock') || command.includes('door')) return 'accent';
                    if (command.includes('music') || command.includes('media')) return 'info';
                    return 'primary';
                }}

                actions.slice(0, 4).forEach(action => {{
                    const btn = document.createElement('button');
                    const variant = pickVariant(action);
                    btn.className = `action-card variant-${{variant}}`;
                    btn.onclick = () => send(action.command);
                    btn.innerHTML = `
                        <div class=\"action-title\">${{escapeHtml(action.label)}}</div>
                        <div class=\"action-desc\">${{escapeHtml(action.description || '')}}</div>
                    `;
                    container.appendChild(btn);
                }});
            }} catch (e) {{
                empty.textContent = 'Could not load quick actions.';
            }}
        }}

        async function loadSuggestions() {{
            const container = document.getElementById('suggested-actions');
            const empty = document.getElementById('suggested-actions-empty');
            if (!container || !empty) return;

            empty.textContent = 'Generating automation ideas...';
            empty.style.display = 'block';
            container.innerHTML = '';

            try {{
                const res = await fetch('/api/ui/suggestions');
                const data = await res.json();
                const suggestions = data.suggestions || [];

                if (!suggestions.length) {{
                    empty.textContent = data.message || 'No suggestions available.';
                    return;
                }}

                empty.style.display = 'none';

                // Use softer variants for suggestions (they're ideas, not immediate actions)
                const variants = ['secondary', 'accent', 'info', 'warning'];

                suggestions.slice(0, 4).forEach((suggestion, index) => {{
                    const btn = document.createElement('button');
                    btn.className = `action-card variant-${{variants[index % variants.length]}}`;
                    btn.onclick = () => send(suggestion.command);
                    btn.innerHTML = `
                        <div class=\"action-title\">${{escapeHtml(suggestion.label)}}</div>
                        <div class=\"action-desc\">${{escapeHtml(suggestion.description || '')}}</div>
                    `;
                    container.appendChild(btn);
                }});
            }} catch (e) {{
                empty.textContent = 'Could not load suggestions.';
            }}
        }}

        async function loadDevices() {{
            const list = document.getElementById('device-status-list');
            const count = document.getElementById('device-count');
            if (!list || !count) return;

            list.innerHTML = '<div class=\"action-empty\">Loading devices...</div>';
            count.textContent = 'Loading...';

            try {{
                const res = await fetch('/api/ui/devices');
                const data = await res.json();
                allDevices = data.devices || [];
                renderDeviceList();
            }} catch (e) {{
                list.innerHTML = '<div class=\"action-empty\">Could not load devices.</div>';
                count.textContent = 'Unavailable';
            }}
        }}

        function renderDeviceList() {{
            const list = document.getElementById('device-status-list');
            const count = document.getElementById('device-count');
            const searchInput = document.getElementById('device-filter-text');
            const showExcludedToggle = document.getElementById('show-excluded-toggle');
            if (!list || !count) return;

            const search = (searchInput?.value || '').trim().toLowerCase();
            const showExcluded = !!showExcludedToggle?.checked;
            const filtered = allDevices.filter(device => {{
                const matchesVisibility = showExcluded || !device.excluded;
                if (!matchesVisibility) return false;
                if (!search) return true;
                const haystack = [
                    device.friendly_name || '',
                    device.entity_id || '',
                    device.domain || '',
                ].join(' ').toLowerCase();
                return haystack.includes(search);
            }});

            if (!filtered.length) {{
                list.innerHTML = '<div class=\"action-empty\">No devices match your filters.</div>';
            }} else {{
                list.innerHTML = '';
                filtered.forEach(device => {{
                    const row = document.createElement('div');
                    row.className = 'device-row';
                    if (device.excluded) {{
                        row.style.opacity = '0.72';
                    }}

                    const meta = document.createElement('div');
                    meta.className = 'device-meta';

                    const friendly = document.createElement('div');
                    friendly.textContent = device.friendly_name || device.entity_id;

                    const domain = document.createElement('div');
                    domain.className = 'device-domain';
                    domain.textContent = `${{device.domain || 'unknown'}} · ${{device.entity_id}}`;

                    meta.appendChild(friendly);
                    meta.appendChild(domain);

                    const right = document.createElement('div');
                    right.style.display = 'flex';
                    right.style.alignItems = 'center';
                    right.style.gap = '10px';

                    const state = document.createElement('div');
                    state.className = 'device-state ' + String(device.state || '').toLowerCase().replace(/\\s+/g, '_');
                    state.textContent = device.state || 'unknown';

                    const label = document.createElement('label');
                    label.style.display = 'flex';
                    label.style.alignItems = 'center';
                    label.style.gap = '5px';
                    label.style.fontSize = '0.74rem';
                    label.style.color = 'var(--muted-foreground)';

                    const checkbox = document.createElement('input');
                    checkbox.type = 'checkbox';
                    checkbox.checked = !!device.excluded;
                    checkbox.onchange = () => toggleDeviceExcluded(device.entity_id, checkbox.checked);

                    const text = document.createElement('span');
                    text.textContent = 'Excluded';

                    label.appendChild(checkbox);
                    label.appendChild(text);
                    right.appendChild(state);
                    right.appendChild(label);

                    row.appendChild(meta);
                    row.appendChild(right);
                    list.appendChild(row);
                }});
            }}

            const excludedCount = allDevices.filter(d => d.excluded).length;
            count.textContent = `${{filtered.length}} shown / ${{allDevices.length}} total (${{excludedCount}} excluded)`;
        }}

        async function toggleDeviceExcluded(entityId, excluded) {{
            const currentExcluded = new Set(
                allDevices
                    .filter(device => device.excluded)
                    .map(device => device.entity_id)
            );
            if (excluded) {{
                currentExcluded.add(entityId);
            }} else {{
                currentExcluded.delete(entityId);
            }}

            try {{
                const res = await fetch('/api/entities/exclusions', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        entity_ids: Array.from(currentExcluded)
                    }})
                }});
                const data = await res.json();
                const excludedSet = new Set(data.excluded_entities || []);
                allDevices = allDevices.map(device => ({{
                    ...device,
                    excluded: excludedSet.has(device.entity_id)
                }}));
                renderDeviceList();
            }} catch (e) {{
                console.error('Failed to update exclusions:', e);
                loadDevices();
            }}
        }}

        async function syncDevices() {{
            const count = document.getElementById('device-count');
            if (count) count.textContent = 'Syncing...';
            try {{
                await fetch('/api/entities/refresh', {{ method: 'POST' }});
            }} catch (e) {{
                console.error('Device sync failed:', e);
            }}
            await loadDevices();
            setTimeout(syncDeviceListHeight, 100);
        }}

        async function clearLogs() {{
            try {{
                await fetch('/api/logs', {{ method: 'DELETE' }});
                loadLogs();
                loadUsageData();
            }} catch (e) {{
                console.error('Failed to clear logs:', e);
            }}
        }}

        // ==================== Pattern Tracking Functions ====================

        async function loadPatterns() {{
            const list = document.getElementById('patterns-list');
            const empty = document.getElementById('patterns-empty');
            const statusEl = document.getElementById('insights-sync-status');
            if (!list || !empty) return;

            try {{
                const res = await fetch('/api/patterns/insights');
                const data = await res.json();

                // Update sync status
                if (statusEl) {{
                    if (data.last_sync) {{
                        const syncDate = new Date(data.last_sync);
                        const now = new Date();
                        const diffMs = now - syncDate;
                        const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
                        if (diffHours < 1) {{
                            statusEl.textContent = 'Just now';
                        }} else if (diffHours < 24) {{
                            statusEl.textContent = `${{diffHours}}h ago`;
                        }} else {{
                            statusEl.textContent = `${{Math.floor(diffHours / 24)}}d ago`;
                        }}
                    }} else {{
                        statusEl.textContent = 'Never synced';
                    }}
                }}

                const patterns = data.patterns || [];

                if (!patterns.length) {{
                    list.innerHTML = '';
                    empty.style.display = 'block';
                    return;
                }}

                empty.style.display = 'none';
                list.innerHTML = '';

                patterns.slice(0, 5).forEach(pattern => {{
                    const row = document.createElement('div');
                    row.className = 'device-row';
                    row.style.cssText = 'flex-direction: column; align-items: stretch; gap: 8px;';

                    const typeLabel = pattern.type === 'time_based' ? 'Time' : 'Sequence';
                    const typeColor = pattern.type === 'time_based' ? 'var(--info)' : 'var(--accent)';
                    const description = formatPatternDescription(pattern);
                    const confidencePct = Math.round(pattern.confidence * 100);

                    row.innerHTML = `
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <span style="font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.05em; padding: 3px 8px; border-radius: var(--radius-full); background: ${{typeColor}}; color: var(--foreground);">${{typeLabel}}</span>
                            <span style="font-size: 0.75rem; color: var(--muted-foreground);">${{pattern.occurrence_count}}x</span>
                        </div>
                        <div style="font-size: 0.85rem; color: var(--foreground);">${{escapeHtml(description)}}</div>
                        <div style="display: flex; gap: 4px; align-items: center;">
                            <div style="flex: 1; height: 4px; background: var(--muted); border-radius: var(--radius-full); overflow: hidden;">
                                <div style="height: 100%; width: ${{confidencePct}}%; background: linear-gradient(90deg, var(--warning), var(--success)); border-radius: var(--radius-full);"></div>
                            </div>
                            <span style="font-size: 0.7rem; color: var(--muted-foreground);">${{confidencePct}}%</span>
                        </div>
                        <div style="display: flex; gap: 8px; margin-top: 4px;">
                            <button onclick="acceptPattern(${{pattern.id}})" style="flex: 1; padding: 6px 10px; border: 1px solid var(--success); border-radius: var(--radius-md); background: var(--success-light); cursor: pointer; font-size: 0.75rem; color: var(--foreground);">Create Automation</button>
                            <button onclick="dismissPattern(${{pattern.id}})" style="flex: 1; padding: 6px 10px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--muted); cursor: pointer; font-size: 0.75rem; color: var(--muted-foreground);">Dismiss</button>
                        </div>
                    `;
                    list.appendChild(row);
                }});
            }} catch (e) {{
                console.error('Failed to load patterns:', e);
                empty.textContent = 'Could not load patterns.';
                empty.style.display = 'block';
            }}
        }}

        function formatPatternDescription(pattern) {{
            if (pattern.type === 'time_based') {{
                const d = pattern.data;
                const entity = pattern.entities[0] || 'device';
                const entityName = entity.split('.').pop().replace(/_/g, ' ');
                return `${{entityName}} turns ${{d.action || 'on'}} around ${{d.average_trigger_time || '??:??'}}`;
            }} else if (pattern.type === 'sequential') {{
                const seq = pattern.data.sequence || [];
                if (seq.length >= 2) {{
                    const e1 = seq[0].entity_id.split('.').pop().replace(/_/g, ' ');
                    const e2 = seq[1].entity_id.split('.').pop().replace(/_/g, ' ');
                    return `${{e1}} -> ${{e2}}`;
                }}
            }}
            return 'Pattern detected';
        }}

        async function loadBehaviorSuggestions() {{
            const container = document.getElementById('behavior-suggestions-grid');
            const empty = document.getElementById('behavior-suggestions-empty');
            if (!container || !empty) return;

            try {{
                const res = await fetch('/api/patterns/suggestions');
                const data = await res.json();
                const suggestions = data.suggestions || [];

                if (!suggestions.length) {{
                    container.innerHTML = '';
                    empty.style.display = 'block';
                    return;
                }}

                empty.style.display = 'none';
                container.innerHTML = '';

                const variants = ['secondary', 'accent', 'info', 'warning'];

                suggestions.slice(0, 4).forEach((suggestion, index) => {{
                    const btn = document.createElement('button');
                    btn.className = `action-card variant-${{variants[index % variants.length]}}`;
                    btn.onclick = () => acceptPattern(suggestion.id, suggestion.command);
                    const confidencePct = Math.round(suggestion.confidence * 100);
                    btn.innerHTML = `
                        <div class="action-title">${{escapeHtml(suggestion.title)}}</div>
                        <div class="action-desc">${{escapeHtml(suggestion.description || '')}}</div>
                        <div style="margin-top: 8px; display: flex; gap: 4px; align-items: center;">
                            <div style="flex: 1; height: 3px; background: var(--muted); border-radius: var(--radius-full); overflow: hidden;">
                                <div style="height: 100%; width: ${{confidencePct}}%; background: linear-gradient(90deg, var(--warning), var(--success)); border-radius: var(--radius-full);"></div>
                            </div>
                            <span style="font-size: 0.7rem; opacity: 0.8;">${{confidencePct}}%</span>
                        </div>
                    `;
                    container.appendChild(btn);
                }});
            }} catch (e) {{
                console.error('Failed to load behavior suggestions:', e);
                empty.textContent = 'Could not load suggestions.';
                empty.style.display = 'block';
            }}
        }}

        async function syncPatterns() {{
            const statusEl = document.getElementById('insights-sync-status');
            if (statusEl) statusEl.textContent = 'Syncing...';

            try {{
                await fetch('/api/patterns/sync', {{ method: 'POST' }});
                await fetch('/api/patterns/detect', {{ method: 'POST' }});
                await loadPatterns();
                await loadBehaviorSuggestions();
                if (statusEl) statusEl.textContent = 'Just now';
            }} catch (e) {{
                console.error('Sync failed:', e);
                if (statusEl) statusEl.textContent = 'Sync failed';
            }}
        }}

        async function acceptPattern(patternId, command) {{
            try {{
                const res = await fetch(`/api/patterns/${{patternId}}/accept`, {{ method: 'POST' }});
                const data = await res.json();

                if (data.command) {{
                    send(data.command);
                }}

                loadPatterns();
                loadBehaviorSuggestions();
            }} catch (e) {{
                console.error('Failed to accept pattern:', e);
            }}
        }}

        async function dismissPattern(patternId) {{
            try {{
                await fetch(`/api/patterns/${{patternId}}/dismiss`, {{ method: 'POST' }});
                loadPatterns();
                loadBehaviorSuggestions();
            }} catch (e) {{
                console.error('Failed to dismiss pattern:', e);
            }}
        }}

        async function updateTokenSummary() {{
            try {{
                const res = await fetch('/api/usage');
                const data = await res.json();
                const summary = data.summary;
                document.getElementById('token-summary').textContent =
                    `Tokens: ${{summary.total_tokens.toLocaleString()}} (${{summary.total_requests}} reqs)`;
            }} catch (e) {{}}
        }}

        function updateChart(history) {{
            const ctx = document.getElementById('tokenChart').getContext('2d');

            const labels = history.map((_, i) => i + 1);
            const inputData = history.map(h => h.input_tokens);
            const outputData = history.map(h => h.output_tokens);

            if (tokenChart) {{
                tokenChart.destroy();
            }}

            const isDark = document.body.classList.contains('dark');
            const textColor = isDark ? '#a69d92' : '#8a8378';
            const gridColor = isDark ? 'rgba(166, 157, 146, 0.15)' : 'rgba(138, 131, 120, 0.15)';

            tokenChart = new Chart(ctx, {{
                type: 'bar',
                data: {{
                    labels: labels,
                    datasets: [
                        {{
                            label: 'Input',
                            data: inputData,
                            backgroundColor: 'rgba(255, 155, 133, 0.8)',
                            hoverBackgroundColor: 'rgba(255, 155, 133, 1)',
                            borderRadius: 6,
                            borderSkipped: false
                        }},
                        {{
                            label: 'Output',
                            data: outputData,
                            backgroundColor: 'rgba(212, 197, 249, 0.8)',
                            hoverBackgroundColor: 'rgba(212, 197, 249, 1)',
                            borderRadius: 6,
                            borderSkipped: false
                        }}
                    ]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{
                            position: 'top',
                            labels: {{
                                color: textColor,
                                font: {{ size: 11, family: "'DM Sans', sans-serif" }},
                                boxWidth: 12,
                                boxHeight: 12,
                                borderRadius: 4,
                                useBorderRadius: true,
                                padding: 12
                            }}
                        }}
                    }},
                    scales: {{
                        x: {{
                            stacked: true,
                            grid: {{ display: false }},
                            ticks: {{ color: textColor, font: {{ size: 10, family: "'DM Sans', sans-serif" }} }},
                            border: {{ display: false }}
                        }},
                        y: {{
                            stacked: true,
                            grid: {{ color: gridColor, drawBorder: false }},
                            ticks: {{ color: textColor, font: {{ size: 10, family: "'DM Sans', sans-serif" }} }},
                            border: {{ display: false }}
                        }}
                    }}
                }}
            }});
        }}

        function renderLogs(logs) {{
            const container = document.getElementById('logs-container');

            if (!logs || logs.length === 0) {{
                container.innerHTML = '<p style="color: var(--muted-foreground); font-size: 0.85rem; text-align: center; padding: 20px;">No logs yet</p>';
                return;
            }}

            container.innerHTML = logs.reverse().map((log, i) => `
                <div class="log-entry">
                    <div class="log-header">
                        <span>${{new Date(log.timestamp).toLocaleTimeString()}}</span>
                        <span>${{log.input_tokens}} in / ${{log.output_tokens}} out (${{log.duration_ms}}ms)</span>
                    </div>
                    ${{log.error ? `<div style="color: var(--error); margin-top: 8px; font-size: 0.8rem;">Error: ${{log.error}}</div>` : ''}}
                    <div class="log-toggle" onclick="toggleLogContent(this)">Show details</div>
                    <div class="log-content" style="display: none;">
<b>Request:</b>
${{JSON.stringify(log.request, null, 2)}}

<b>Response:</b>
${{JSON.stringify(log.response, null, 2)}}
                    </div>
                </div>
            `).join('');
        }}

        function toggleLogContent(el) {{
            const content = el.nextElementSibling;
            const isHidden = content.style.display === 'none';
            content.style.display = isHidden ? 'block' : 'none';
            el.textContent = isHidden ? 'Hide request/response' : 'Show request/response';
        }}

        let currentLogTab = 'llm';

        function switchLogTab(tab) {{
            currentLogTab = tab;
            document.querySelectorAll('.log-tab').forEach(t => t.classList.remove('active'));
            document.getElementById(tab + '-tab').classList.add('active');

            if (tab === 'llm') {{
                loadLogs();
            }} else {{
                fetchHALogs();
            }}
        }}

        async function fetchHALogs() {{
            try {{
                const response = await fetch('/api/logs/ha');
                const data = await response.json();
                renderHALogs(data.logs);
            }} catch (e) {{
                console.error('Failed to fetch HA logs:', e);
            }}
        }}

        function renderHALogs(logs) {{
            const container = document.getElementById('logs-container');

            if (!logs || logs.length === 0) {{
                container.innerHTML = '<p style="color: var(--muted-foreground); font-size: 0.85rem; text-align: center; padding: 20px;">No HA API logs yet</p>';
                return;
            }}

            container.innerHTML = logs.reverse().map((log, i) => `
                <div class="log-entry">
                    <div class="log-header">
                        <span>${{new Date(log.timestamp).toLocaleTimeString()}}</span>
                        <span>${{log.method}} ${{log.endpoint}} (${{log.status_code}}) ${{log.duration_ms}}ms</span>
                    </div>
                    ${{log.error ? `<div style="color: var(--error); margin-top: 8px; font-size: 0.8rem;">Error: ${{log.error}}</div>` : ''}}
                    <div class="log-toggle" onclick="toggleLogContent(this)">Show details</div>
                    <div class="log-content" style="display: none;">
${{log.request_data ? `<b>Request:</b>
${{JSON.stringify(log.request_data, null, 2)}}` : '<b>Request:</b> (none)'}}

<b>Response:</b>
${{JSON.stringify(log.response_data, null, 2)}}
                    </div>
                </div>
            `).join('');
        }}

        if (window.innerWidth >= 1024) {{
            panelVisible = true;
            loadUsageData();
            loadLogs();
        }}

        const storedTheme = localStorage.getItem('theme');
        if (storedTheme === 'dark') {{
            setTheme(true);
        }} else {{
            setTheme(false);
        }}

        function syncDeviceListHeight() {{
            const actionsCard = document.getElementById('actions-card');
            const deviceList = document.getElementById('device-status-list');
            const devicesCard = document.getElementById('devices-card');
            if (actionsCard && deviceList && devicesCard) {{
                // Get the actions card height
                const actionsHeight = actionsCard.offsetHeight;
                // Get the devices card header height (title + count)
                const headerHeight = devicesCard.querySelector('.status-header')?.offsetHeight || 0;
                const controlsHeight = devicesCard.querySelector('.device-controls')?.offsetHeight || 0;
                // Calculate available height for device list (includes card padding and control spacing)
                const availableHeight = actionsHeight - headerHeight - controlsHeight - 48;
                deviceList.style.maxHeight = Math.max(300, availableHeight) + 'px';
            }}
        }}

        loadQuickActions();
        loadSuggestions().then(() => setTimeout(syncDeviceListHeight, 100));
        loadDevices().then(() => setTimeout(syncDeviceListHeight, 100));
        updateTokenSummary();

        // Load pattern tracking data
        loadPatterns();
        loadBehaviorSuggestions();

        // Also sync on window resize
        window.addEventListener('resize', syncDeviceListHeight);
    </script>
</body>
</html>
    """


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """Handle chat messages."""
    try:
        agent = get_agent()
        response = await agent.run(request.message, request.session_id)
        return ChatResponse(
            response=response,
            success=True,
            session_id=request.session_id
        )
    except Exception as e:
        return ChatResponse(
            response=str(e),
            success=False,
            session_id=request.session_id
        )


@app.get("/devices-manager", response_class=HTMLResponse)
async def devices_manager_page():
    """Dedicated device manager page (simpler than modal for reliability)."""
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Manage Devices</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --font-primary: 'Outfit', system-ui, -apple-system, sans-serif;
            --font-secondary: 'DM Sans', system-ui, -apple-system, sans-serif;
            --background: #fdfbf7;
            --foreground: #4a4137;
            --muted: #f5f2ed;
            --muted-foreground: #8a8378;
            --card: #ffffff;
            --border: #e8e4dc;
            --primary: #ff9b85;
            --primary-dark: #f48171;
            --shadow-sm: 0 2px 4px 0 rgb(0 0 0 / 0.04);
            --shadow-md: 0 4px 12px 0 rgb(0 0 0 / 0.05);
            --radius-md: 0.75rem;
            --radius-lg: 1rem;
            --radius-xl: 1.25rem;
        }
        body {
            margin: 0;
            font-family: var(--font-secondary);
            background: linear-gradient(135deg, #fff8f5 0%, #fdfbf7 30%, #f8f4ef 100%);
            color: var(--foreground);
        }
        .wrap {
            max-width: 1200px;
            margin: 20px auto 28px auto;
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: var(--radius-xl);
            box-shadow: var(--shadow-md);
            overflow: hidden;
        }
        .head {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 18px 20px;
            border-bottom: 1px solid var(--border);
            background: linear-gradient(135deg, rgba(255, 155, 133, 0.08) 0%, rgba(212, 197, 249, 0.1) 100%);
        }
        .toolbar {
            display: grid;
            grid-template-columns: 1fr auto auto auto auto;
            gap: 10px;
            padding: 14px 20px;
            border-bottom: 1px solid var(--border);
            background: var(--muted);
        }
        input[type="text"], select {
            padding: 9px 11px;
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            background: var(--card);
            color: var(--foreground);
            font-family: var(--font-secondary);
            font-size: 0.9rem;
            width: 100%;
        }
        button {
            padding: 8px 12px;
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            background: var(--card);
            color: var(--foreground);
            font-family: var(--font-secondary);
            font-weight: 500;
            cursor: pointer;
            box-shadow: var(--shadow-sm);
            transition: transform 0.15s ease, border-color 0.15s ease;
        }
        button:hover {
            transform: translateY(-1px);
            border-color: var(--primary);
        }
        .content {
            max-height: calc(100vh - 210px);
            overflow-y: auto;
            padding: 14px 20px 18px 20px;
        }
        details {
            border: 1px solid var(--border);
            border-radius: var(--radius-lg);
            margin-bottom: 8px;
            background: var(--card);
            box-shadow: var(--shadow-sm);
        }
        summary {
            cursor: pointer;
            padding: 11px 12px;
            font-weight: 600;
            font-family: var(--font-primary);
        }
        .rows {
            padding: 8px;
            border-top: 1px solid var(--border);
            background: var(--muted);
        }
        .group-actions {
            display: flex;
            gap: 8px;
            justify-content: flex-end;
            margin-bottom: 8px;
        }
        .group-actions button {
            padding: 6px 10px;
            font-size: 12px;
        }
        .row {
            display: grid;
            grid-template-columns: minmax(0, 1fr) 120px 120px;
            gap: 8px;
            align-items: center;
            padding: 8px;
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            margin-bottom: 6px;
            background: var(--card);
        }
        .meta {
            min-width: 0;
        }
        .name {
            font-size: 14px;
            font-weight: 600;
            font-family: var(--font-primary);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .sub {
            font-size: 12px;
            color: var(--muted-foreground);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .state {
            font-size: 12px;
            color: var(--muted-foreground);
            background: var(--muted);
            padding: 6px 8px;
            border-radius: 999px;
            text-align: center;
        }
        .empty {
            padding: 14px;
            border: 1px dashed var(--border);
            border-radius: var(--radius-md);
            color: var(--muted-foreground);
            text-align: center;
            background: var(--muted);
        }
        .back-link {
            text-decoration: none;
        }
        .back-btn {
            background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
            color: #fff;
            border-color: transparent;
        }
        .toolbar label {
            display:flex;
            align-items:center;
            gap:6px;
            font-size:14px;
            color: var(--muted-foreground);
        }
        #count {
            display:flex;
            align-items:center;
            font-size:13px;
            color: var(--muted-foreground);
            background: var(--card);
            border: 1px solid var(--border);
            padding: 0 10px;
            border-radius: 999px;
        }
        @media (max-width: 900px) {
            .toolbar { grid-template-columns: 1fr; }
            .row { grid-template-columns: 1fr; }
            .group-actions { justify-content: flex-start; }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="head">
            <h2 style="margin:0; font-family: var(--font-primary);">Manage Devices</h2>
            <a href="/" class="back-link"><button class="back-btn">Back</button></a>
        </div>
        <div class="toolbar">
            <input type="text" id="search" placeholder="Search by device, entity, domain, or state" />
            <select id="viewMode">
                <option value="device">Device view</option>
                <option value="domain">Domain view</option>
            </select>
            <label><input id="showExcluded" type="checkbox" /> Show excluded</label>
            <button onclick="syncNow()">Sync Now</button>
            <div id="count">Loading...</div>
        </div>
        <div class="content" id="list"><div class="empty">Loading devices...</div></div>
    </div>

    <script>
        let allDevices = [];

        function groupDevices(devices) {
            const mode = document.getElementById('viewMode').value || 'device';
            const groups = new Map();
            for (const device of devices) {
                let key;
                let label;
                if (mode === 'domain') {
                    key = 'domain-' + (device.domain || 'unknown');
                    label = (device.domain || 'unknown');
                } else {
                    label = device.device_group || device.friendly_name || device.entity_id || 'Unnamed Device';
                    key = device.device_group_key || label.toLowerCase().trim();
                }
                if (!groups.has(key)) groups.set(key, { key, label, items: [] });
                groups.get(key).items.push(device);
            }
            return Array.from(groups.values()).sort((a, b) => a.label.localeCompare(b.label));
        }

        function getFilteredDevices() {
            const q = (document.getElementById('search').value || '').toLowerCase().trim();
            const showExcluded = document.getElementById('showExcluded').checked;
            return allDevices.filter(d => {
                if (!showExcluded && d.excluded) return false;
                if (!q) return true;
                const hay = [(d.device_group || ''), (d.friendly_name || ''), (d.entity_id || ''), (d.domain || ''), (d.state || '')].join(' ').toLowerCase();
                return hay.includes(q);
            });
        }

        function render() {
            const list = document.getElementById('list');
            const filtered = getFilteredDevices();
            const groups = groupDevices(filtered);
            const excludedCount = allDevices.filter(d => d.excluded).length;
            document.getElementById('count').textContent = `${filtered.length} shown / ${allDevices.length} total (${excludedCount} excluded)`;

            if (!groups.length) {
                list.innerHTML = '<div class="empty">No devices match your filters.</div>';
                return;
            }

            list.innerHTML = '';
            for (const group of groups) {
                const details = document.createElement('details');
                details.open = true;
                const summary = document.createElement('summary');
                const excludedInGroup = group.items.filter(i => i.excluded).length;
                summary.textContent = `${group.label} (${group.items.length} entities, ${excludedInGroup} excluded)`;
                details.appendChild(summary);

                const rows = document.createElement('div');
                rows.className = 'rows';

                const actions = document.createElement('div');
                actions.className = 'group-actions';
                const includeAllBtn = document.createElement('button');
                includeAllBtn.textContent = 'Include all';
                includeAllBtn.onclick = (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setGroupExcluded(group.items, false);
                };
                const excludeAllBtn = document.createElement('button');
                excludeAllBtn.textContent = 'Exclude all';
                excludeAllBtn.onclick = (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setGroupExcluded(group.items, true);
                };
                actions.appendChild(includeAllBtn);
                actions.appendChild(excludeAllBtn);
                rows.appendChild(actions);

                for (const item of group.items) {
                    const row = document.createElement('div');
                    row.className = 'row';

                    const meta = document.createElement('div');
                    meta.className = 'meta';
                    const name = document.createElement('div');
                    name.className = 'name';
                    name.textContent = item.friendly_name || item.entity_id || 'Unnamed Entity';
                    const sub = document.createElement('div');
                    sub.className = 'sub';
                    sub.textContent = `${item.domain || 'unknown'} - ${item.entity_id || 'unknown'}`;
                    meta.appendChild(name);
                    meta.appendChild(sub);

                    const state = document.createElement('div');
                    state.className = 'state';
                    state.textContent = item.state || 'unknown';

                    const label = document.createElement('label');
                    label.style.display = 'inline-flex';
                    label.style.alignItems = 'center';
                    label.style.gap = '6px';
                    label.style.fontSize = '13px';
                    const checkbox = document.createElement('input');
                    checkbox.type = 'checkbox';
                    checkbox.checked = !!item.excluded;
                    checkbox.onchange = () => updateExcluded(item.entity_id, checkbox.checked);
                    const txt = document.createElement('span');
                    txt.textContent = 'Excluded';
                    label.appendChild(checkbox);
                    label.appendChild(txt);

                    row.appendChild(meta);
                    row.appendChild(state);
                    row.appendChild(label);
                    rows.appendChild(row);
                }

                details.appendChild(rows);
                list.appendChild(details);
            }
        }

        async function persistExcludedSet(excludedSet) {
            const res = await fetch('/api/entities/exclusions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ entity_ids: Array.from(excludedSet) })
            });
            const data = await res.json();
            const updated = new Set(data.excluded_entities || []);
            allDevices = allDevices.map(d => ({ ...d, excluded: updated.has(d.entity_id) }));
            render();
        }

        async function load() {
            const list = document.getElementById('list');
            list.innerHTML = '<div class="empty">Loading devices...</div>';
            try {
                const res = await fetch('/api/ui/devices');
                const data = await res.json();
                allDevices = data.devices || [];
                render();
            } catch (e) {
                list.innerHTML = '<div class="empty">Could not load devices.</div>';
            }
        }

        async function updateExcluded(entityId, excluded) {
            const excludedSet = new Set(allDevices.filter(d => d.excluded).map(d => d.entity_id));
            if (excluded) excludedSet.add(entityId);
            else excludedSet.delete(entityId);
            try {
                await persistExcludedSet(excludedSet);
            } catch (e) {
                await load();
            }
        }

        async function setGroupExcluded(groupItems, excluded) {
            const excludedSet = new Set(allDevices.filter(d => d.excluded).map(d => d.entity_id));
            for (const item of groupItems) {
                if (excluded) excludedSet.add(item.entity_id);
                else excludedSet.delete(item.entity_id);
            }
            try {
                await persistExcludedSet(excludedSet);
            } catch (e) {
                await load();
            }
        }

        async function syncNow() {
            document.getElementById('count').textContent = 'Syncing...';
            try { await fetch('/api/entities/refresh', { method: 'POST' }); } catch (e) {}
            await load();
        }

        document.getElementById('search').addEventListener('input', render);
        document.getElementById('showExcluded').addEventListener('change', render);
        document.getElementById('viewMode').addEventListener('change', render);
        load();
    </script>
</body>
</html>
    """


@app.get("/api/usage")
async def get_usage():
    """Get token usage statistics."""
    tracker = get_usage_tracker()
    return {
        "history": tracker.get_usage_history(limit=20),
        "summary": tracker.get_usage_summary()
    }


@app.get("/api/logs")
async def get_logs():
    """Get LLM request logs."""
    tracker = get_usage_tracker()
    return {
        "logs": tracker.get_log_history(limit=20)
    }


@app.get("/api/logs/ha")
async def get_ha_logs():
    """Get Home Assistant API logs."""
    tracker = get_usage_tracker()
    return {
        "logs": tracker.get_ha_log_history(limit=50)
    }


@app.delete("/api/logs")
async def clear_logs():
    """Clear all logs and usage history."""
    tracker = get_usage_tracker()
    tracker.clear_all()
    return {"status": "cleared"}


@app.delete("/api/session/{session_id}")
async def clear_session(session_id: str):
    """Clear conversation history for a session."""
    memory = get_memory(session_id)
    memory.clear()
    return {"status": "cleared", "session_id": session_id}


@app.get("/api/entities")
async def get_entities():
    """Get cached entity index info."""
    from app.entity_filters import get_excluded_entity_patterns
    from app.setup.entity_cache import get_entity_cache

    cache = get_entity_cache()
    index = cache.load()
    excluded = get_excluded_entity_patterns()

    if not index:
        return {
            "cached": False,
            "entity_count": 0,
            "last_refreshed": None,
            "excluded_count": len(excluded),
            "message": "No entity cache. Validate Home Assistant connection to populate."
        }

    return {
        "cached": True,
        "entity_count": index.entity_count,
        "excluded_count": len(excluded),
        "last_refreshed": index.last_refreshed,
        "ha_url": index.ha_url
    }


@app.get("/api/ui/devices")
async def get_ui_devices():
    """Get all cached devices with current state for the UI."""
    from app.config import get_settings
    from app.entity_filters import get_excluded_entity_patterns, is_entity_excluded
    from app.setup.entity_cache import get_entity_cache
    from app.tools.home_assistant import HomeAssistantClient

    settings = get_settings()
    excluded_patterns = get_excluded_entity_patterns()
    entity_to_device_id: dict[str, str] = {}
    device_id_to_name: dict[str, str] = {}
    if settings.ha_url and settings.ha_token:
        try:
            entity_to_device_id, device_id_to_name = await _fetch_ha_registry_maps(
                settings.ha_url,
                settings.ha_token,
            )
        except Exception:
            entity_to_device_id, device_id_to_name = {}, {}

    cache = get_entity_cache()
    index = cache.load()
    by_entity_id = {}
    if index:
        for entity in index.entities:
            by_entity_id[entity.entity_id] = {
                "entity_id": entity.entity_id,
                "domain": entity.domain,
                "friendly_name": entity.friendly_name,
                "device_class": entity.device_class,
                "state": "unknown",
                "device_name": None,
                "device_registry_id": entity_to_device_id.get(entity.entity_id),
            }

    has_live_states = False
    try:
        if settings.ha_url and settings.ha_token:
            client = HomeAssistantClient()
            # Keep UI responsive: if live state fetch is slow, fall back to cached entities.
            states = await asyncio.wait_for(
                client.get_states(include_excluded=True),
                timeout=4.0
            )
            has_live_states = True
            for state in states:
                entity_id = state.entity_id
                domain = entity_id.split(".")[0] if "." in entity_id else "unknown"
                existing = by_entity_id.get(entity_id, {})
                by_entity_id[entity_id] = {
                    "entity_id": entity_id,
                    "domain": existing.get("domain") or domain,
                    "friendly_name": (
                        state.attributes.get("friendly_name")
                        or existing.get("friendly_name")
                        or entity_id
                    ),
                    "device_class": (
                        state.attributes.get("device_class")
                        or existing.get("device_class")
                    ),
                    "state": state.state,
                    "device_name": (
                        state.attributes.get("device_name")
                        or existing.get("device_name")
                        or (
                            device_id_to_name.get(entity_to_device_id.get(entity_id, ""))
                            if entity_to_device_id.get(entity_id)
                            else None
                        )
                    ),
                    "device_registry_id": (
                        entity_to_device_id.get(entity_id)
                        or existing.get("device_registry_id")
                    ),
                }
    except Exception:
        has_live_states = False

    devices = []
    grouped_entity_counts: dict[str, int] = defaultdict(int)
    for entity in by_entity_id.values():
        entity_id = entity["entity_id"]
        registry_device_id = entity.get("device_registry_id")
        if registry_device_id:
            group_key = f"device-{registry_device_id}"
            group_label = (
                device_id_to_name.get(registry_device_id)
                or entity.get("device_name")
                or entity.get("friendly_name")
                or entity_id
            )
        else:
            # Entity is not linked to a device in HA registry.
            group_key = f"unassigned-{entity_id.replace('.', '-')}"
            group_label = f"Unassigned: {entity.get('friendly_name') or entity_id}"
        grouped_entity_counts[group_key] += 1
        devices.append({
            **entity,
            "device_group": group_label,
            "device_group_key": group_key,
            "excluded": is_entity_excluded(entity["entity_id"], excluded_patterns),
        })
    devices.sort(
        key=lambda d: (
            d["excluded"],
            d.get("domain", ""),
            (d.get("friendly_name") or d.get("entity_id") or "").lower(),
        )
    )

    return {
        "cached": bool(index),
        "live_states": has_live_states,
        "registry_mapped": bool(entity_to_device_id),
        "last_refreshed": index.last_refreshed if index else None,
        "devices": devices,
        "excluded_count": sum(1 for d in devices if d["excluded"]),
        "group_count": len(grouped_entity_counts),
    }


@app.get("/api/entities/exclusions")
async def get_entity_exclusions():
    """Get the currently configured excluded entities."""
    from app.entity_filters import get_excluded_entity_patterns

    excluded = get_excluded_entity_patterns()
    return {
        "excluded_entities": excluded,
        "count": len(excluded),
    }


@app.post("/api/entities/exclusions")
async def update_entity_exclusions(request: ExcludedEntitiesRequest):
    """Persist excluded entities and refresh caches."""
    from app.config import clear_settings_cache
    from app.setup.entity_cache import get_entity_cache
    from app.setup.models import StoredConfig
    from app.setup.storage import ConfigStorage

    normalized = sorted({
        entity_id.strip().lower()
        for entity_id in (request.entity_ids or [])
        if isinstance(entity_id, str) and entity_id.strip()
    })

    storage = ConfigStorage()
    existing_config = storage.load()
    if not existing_config:
        return {
            "success": False,
            "error": "No configuration found. Complete setup first.",
            "excluded_entities": [],
        }

    updated_config = StoredConfig(
        provider=existing_config.provider,
        limits=existing_config.limits,
        home_assistant=existing_config.home_assistant,
        app_name=existing_config.app_name,
        excluded_entities=",".join(normalized),
    )
    storage.save(updated_config)

    clear_settings_cache()
    clear_agent_cache()

    cache = get_entity_cache()
    cache.clear_memory_cache()
    if (
        existing_config.home_assistant.url
        and existing_config.home_assistant.token
    ):
        await cache.fetch_and_cache(
            existing_config.home_assistant.url,
            existing_config.home_assistant.token,
            background=True,
        )

    return {
        "success": True,
        "excluded_entities": normalized,
        "count": len(normalized),
    }


@app.get("/api/ui/quick-actions")
async def get_ui_quick_actions():
    """Generate curated quick actions based on devices and guardrails."""
    from app.config import get_settings
    from app.guardrails import SafetyGuardrails
    from app.providers.llm import get_llm_provider, Message
    from app.setup.entity_cache import get_entity_cache

    settings = get_settings()
    cache = get_entity_cache()
    index = cache.load()
    if not index:
        return {"actions": [], "message": "No entity cache available."}

    entities = index.entities[:50]
    available_domains = {e.domain for e in index.entities if e.domain}
    entity_names = {
        e.friendly_name.lower()
        for e in index.entities
        if e.friendly_name
    }
    device_lines = [
        f"- {e.friendly_name} ({e.entity_id}) [{e.domain}]"
        for e in entities
    ]
    automation_lines = [
        f"- {e.friendly_name} ({e.entity_id})"
        for e in index.entities
        if e.domain == "automation"
    ][:25]

    system_prompt = (
        "You create concise, safe quick actions for a smart home dashboard. "
        "Return ONLY a JSON array of up to 4 objects, each with: "
        "label, command, description. "
        "Commands must be safe, non-destructive, and use the device names provided. "
        "Only suggest actions for the available domains and scripts provided. "
        "Include a mix of: (1) direct device actions and (2) automation actions. "
        "Automation actions can be existing ones (Run/Enable) or suggestions to create new "
        "automations phrased like 'Create an automation to <do something>' when appropriate. "
        "Avoid anything that locks users out, disables security, or changes critical settings."
    )
    user_prompt = (
        "Devices:\n"
        + "\n".join(device_lines)
        + "\n\nAvailable domains:\n"
        + ", ".join(sorted(available_domains))
        + f"\n\nGuardrails threshold: {settings.guardrails_threshold}\n"
        + "Return the JSON array now."
    )

    script_lines = _load_scripts_for_prompt(available_domains)
    if script_lines:
        user_prompt = (
            user_prompt
            + "\n\nScripts:\n"
            + "\n".join(script_lines)
        )

    if automation_lines:
        user_prompt = (
            user_prompt
            + "\n\nAutomations:\n"
            + "\n".join(automation_lines)
        )

    scripts = _load_scripts(available_domains)
    allowed_script_names = {
        (alias or script_id).lower()
        for script_id, alias in scripts
    }
    allowed_script_names.update({f"script.{script_id}".lower() for script_id, _ in scripts})

    actions: list[dict] = []
    llm_error = None
    try:
        llm = get_llm_provider()
        response = await llm.chat(
            messages=[
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_prompt)
            ]
        )
        raw = response.content or "[]"
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\[[\\s\\S]*\\]", raw)
            parsed = json.loads(match.group(0)) if match else []
        if isinstance(parsed, list):
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label", "")).strip()
                command = str(item.get("command", "")).strip()
                description = str(item.get("description", "")).strip()
                if not label or not command:
                    continue
                actions.append({
                    "label": label[:48],
                    "command": command[:140],
                    "description": description[:80]
                })
    except Exception as e:
        llm_error = str(e)

    actions = _filter_actions_by_context(
        actions,
        available_domains,
        entity_names,
        allowed_script_names
    )

    if not actions:
        actions = _fallback_quick_actions(index.entities, scripts)

    guardrails = SafetyGuardrails()
    filtered = []
    for action in actions:
        if settings.guardrails_threshold == 0:
            filtered.append(action)
            continue
        try:
            result = await guardrails.check(action["command"])
            if result.passed:
                filtered.append(action)
        except Exception:
            continue

    if not filtered and actions:
        filtered = actions[:4]

    response = {"actions": filtered[:4]}
    if llm_error:
        response["message"] = "Generated fallback actions."
    return response


@app.get("/api/ui/suggestions")
async def get_ui_suggestions():
    """Generate automation suggestions based on available devices and scripts."""
    from app.config import get_settings
    from app.providers.llm import get_llm_provider, Message
    from app.setup.entity_cache import get_entity_cache

    settings = get_settings()
    cache = get_entity_cache()
    index = cache.load()
    if not index:
        return {"suggestions": [], "message": "No entity cache available."}

    # Get device info grouped by domain
    domains_with_devices: dict[str, list[str]] = {}
    for entity in index.entities:
        if entity.domain not in domains_with_devices:
            domains_with_devices[entity.domain] = []
        if len(domains_with_devices[entity.domain]) < 5:  # Limit per domain
            domains_with_devices[entity.domain].append(entity.friendly_name)

    # Format devices by domain for the prompt
    device_summary_lines = []
    for domain, names in sorted(domains_with_devices.items()):
        if domain in ("automation", "script", "scene", "update", "button", "number"):
            continue  # Skip non-controllable domains
        device_summary_lines.append(f"- {domain}: {', '.join(names[:3])}" +
                                    (f" (+{len(names)-3} more)" if len(names) > 3 else ""))

    # Load scripts
    scripts = _load_scripts()
    script_lines = [f"- {alias or script_id}" for script_id, alias in scripts[:10]]

    # Load existing automations
    automation_names = [
        e.friendly_name for e in index.entities
        if e.domain == "automation" and e.friendly_name
    ][:10]

    system_prompt = """You are a helpful smart home automation advisor. Your job is to suggest creative, useful automations that the user could set up based on their available devices.

Generate 3-4 automation SUGGESTIONS (not commands to execute now). Each suggestion should:
1. Be phrased as an idea/recommendation starting with action words like "Create", "Set up", "Automate", "Schedule"
2. Combine multiple devices or use time/event triggers creatively
3. Be practical and improve daily life (comfort, convenience, energy saving, security)
4. Reference actual device names from the list provided

Return ONLY a JSON array with objects containing:
- "label": Short title (2-4 words, e.g., "Morning Routine", "Movie Mode", "Away Security")
- "command": The full suggestion phrased as a request (e.g., "Create an automation that turns on the living room lights at sunset")
- "description": Brief benefit explanation (e.g., "Never come home to a dark house")

Focus on cross-device automations and time-based triggers. Be creative but practical."""

    user_prompt = f"""Available devices by type:
{chr(10).join(device_summary_lines)}

{"Scripts available:" + chr(10) + chr(10).join(script_lines) if script_lines else "No scripts defined yet."}

{"Existing automations (for reference, suggest NEW ones):" + chr(10) + chr(10).join(f"- {name}" for name in automation_names) if automation_names else "No automations yet - great opportunity to suggest some!"}

Generate 3-4 creative automation suggestions as a JSON array."""

    suggestions: list[dict] = []
    llm_error = None

    try:
        llm = get_llm_provider()
        response = await llm.chat(
            messages=[
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_prompt)
            ]
        )
        raw = response.content or "[]"
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # Try to extract JSON array from response
            match = re.search(r"\[[\s\S]*\]", raw)
            parsed = json.loads(match.group(0)) if match else []

        if isinstance(parsed, list):
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label", "")).strip()
                command = str(item.get("command", "")).strip()
                description = str(item.get("description", "")).strip()
                if not label or not command:
                    continue
                suggestions.append({
                    "label": label[:32],
                    "command": command[:200],
                    "description": description[:100]
                })
    except Exception as e:
        llm_error = str(e)

    # Fallback suggestions if LLM fails
    if not suggestions:
        suggestions = _fallback_suggestions(domains_with_devices, scripts)

    result = {"suggestions": suggestions[:4]}
    if llm_error:
        result["message"] = "Using example suggestions."
    return result


def _fallback_suggestions(domains: dict[str, list[str]], scripts: list) -> list[dict]:
    """Generate fallback automation suggestions when LLM is unavailable."""
    suggestions = []

    # Check what domains are available and suggest accordingly
    has_lights = "light" in domains
    has_media = "media_player" in domains
    has_climate = "climate" in domains
    has_lock = "lock" in domains
    has_cover = "cover" in domains
    has_switch = "switch" in domains
    has_tts = "tts" in domains
    has_weather = "weather" in domains
    has_person = "person" in domains

    # Media player suggestions (TV, speakers, etc.)
    if has_media:
        media_name = domains["media_player"][0] if domains["media_player"] else "TV"
        suggestions.append({
            "label": "Bedtime TV Off",
            "command": f"Create an automation to turn off {media_name} at 11 PM on weeknights",
            "description": "Never fall asleep with the TV on"
        })

        if has_tts:
            suggestions.append({
                "label": "TV Time Limit",
                "command": f"Create an automation that announces a reminder after 3 hours of TV being on",
                "description": "Gentle reminder to take a break"
            })

    # TTS + Weather combo
    if has_tts and has_weather:
        suggestions.append({
            "label": "Morning Briefing",
            "command": "Create a morning automation that announces today's weather forecast at 7 AM",
            "description": "Start your day informed"
        })

    # TTS suggestions
    if has_tts:
        suggestions.append({
            "label": "Welcome Home",
            "command": "Create an automation that announces 'Welcome home' when I arrive",
            "description": "Personal greeting when you return"
        })

    # Lights suggestions
    if has_lights:
        light_name = domains["light"][0] if domains["light"] else "lights"
        suggestions.append({
            "label": "Sunset Lights",
            "command": f"Create an automation to turn on {light_name} at sunset",
            "description": "Never come home to a dark house"
        })

    if has_media and has_lights:
        suggestions.append({
            "label": "Movie Mode",
            "command": "Create a movie mode that dims the lights when I start playing media on the TV",
            "description": "Perfect ambiance for movie night"
        })

    # Climate suggestions
    if has_climate:
        climate_name = domains["climate"][0] if domains["climate"] else "thermostat"
        suggestions.append({
            "label": "Energy Saver",
            "command": f"Set up an automation to adjust {climate_name} when everyone leaves home",
            "description": "Save energy when no one is home"
        })

    # Lock suggestions
    if has_lock:
        suggestions.append({
            "label": "Bedtime Security",
            "command": "Create a bedtime routine that locks all doors at 11 PM",
            "description": "Peace of mind every night"
        })

    # Switch suggestions
    if has_switch:
        suggestions.append({
            "label": "All Off",
            "command": "Create a 'leaving home' automation that turns off all switches and lights",
            "description": "One command to secure your home"
        })

    # Person/presence suggestions
    if has_person and has_media:
        suggestions.append({
            "label": "Away Mode",
            "command": "Create an automation to turn off the TV when everyone leaves home",
            "description": "Save energy automatically"
        })

    # If we still don't have enough suggestions, add generic helpful ones
    if len(suggestions) < 2:
        suggestions.append({
            "label": "Weekend Mode",
            "command": "Help me create a weekend automation that's different from weekdays",
            "description": "Different routines for different days"
        })

    if len(suggestions) < 3:
        suggestions.append({
            "label": "Night Routine",
            "command": "Create a goodnight routine that runs when I say goodnight",
            "description": "One command to end your day"
        })

    return suggestions[:4]


@app.post("/api/entities/refresh")
async def refresh_entities():
    """Manually refresh the entity cache."""
    from app.setup.entity_cache import get_entity_cache
    from app.config import get_settings

    settings = get_settings()
    if not settings.ha_url or not settings.ha_token:
        return {
            "success": False,
            "error": "Home Assistant not configured"
        }

    cache = get_entity_cache()
    cache.clear_memory_cache()  # Force fresh fetch
    success, error = await cache.fetch_and_cache(settings.ha_url, settings.ha_token)

    # Also clear the agent cache so it picks up new entities
    clear_agent_cache()

    if success:
        index = cache.load()
        return {
            "success": True,
            "entity_count": index.entity_count if index else 0,
            "last_refreshed": index.last_refreshed if index else None
        }

    return {
        "success": False,
        "error": error
    }


# ==================== Pattern Tracking Endpoints ====================


@app.get("/api/patterns/insights")
async def get_pattern_insights():
    """Get detected usage patterns for the UI."""
    try:
        from app.patterns.database import get_pattern_db

        db = get_pattern_db()
        patterns = db.get_active_patterns(min_confidence=0.3)
        last_sync = db.get_last_sync_timestamp()

        return {
            "patterns": [
                {
                    "id": p.id,
                    "type": p.pattern_type.value,
                    "entities": p.entity_ids,
                    "confidence": p.confidence,
                    "occurrence_count": p.occurrence_count,
                    "last_seen": p.last_seen.isoformat() + "Z",
                    "data": p.pattern_data,
                }
                for p in patterns
            ],
            "pattern_count": len(patterns),
            "last_sync": (last_sync.isoformat() + "Z") if last_sync else None,
        }
    except Exception as e:
        return {"patterns": [], "pattern_count": 0, "last_sync": None, "error": str(e)}


@app.get("/api/patterns/suggestions")
async def get_pattern_suggestions():
    """Get automation suggestions based on detected patterns."""
    try:
        from app.patterns.suggestions import get_suggestion_generator
        from app.setup.entity_cache import get_entity_cache

        cache = get_entity_cache()
        generator = get_suggestion_generator(entity_cache=cache)
        suggestions = generator.generate_suggestions(max_suggestions=6)

        return {
            "suggestions": [
                {
                    "id": s.pattern_id,
                    "type": s.pattern_type.value,
                    "title": s.title,
                    "description": s.description,
                    "command": s.command,
                    "confidence": s.confidence,
                    "occurrence_count": s.occurrence_count,
                    "entities": s.entities_involved,
                    "automation_yaml": s.automation_yaml,
                }
                for s in suggestions
            ]
        }
    except Exception as e:
        return {"suggestions": [], "error": str(e)}


@app.post("/api/patterns/sync")
async def trigger_pattern_sync():
    """Manually trigger a sync from Home Assistant history."""
    try:
        from app.patterns.collector import EventCollector
        from app.config import get_settings

        settings = get_settings()
        if not settings.ha_url or not settings.ha_token:
            return {"success": False, "error": "Home Assistant not configured", "events_synced": 0}

        collector = EventCollector(settings.ha_url, settings.ha_token)
        count, error = await collector.sync_from_history_api()

        if error:
            return {"success": False, "error": error, "events_synced": 0}
        return {"success": True, "events_synced": count}
    except Exception as e:
        return {"success": False, "error": str(e), "events_synced": 0}


@app.post("/api/patterns/detect")
async def trigger_pattern_detection():
    """Manually trigger pattern detection."""
    try:
        from app.patterns.detector import get_pattern_detector

        detector = get_pattern_detector()
        patterns = detector.detect_all_patterns()

        return {"success": True, "patterns_detected": len(patterns)}
    except Exception as e:
        return {"success": False, "error": str(e), "patterns_detected": 0}


@app.post("/api/patterns/{pattern_id}/dismiss")
async def dismiss_pattern(pattern_id: int):
    """Dismiss a pattern so it won't generate suggestions."""
    try:
        from app.patterns.database import get_pattern_db

        db = get_pattern_db()
        db.deactivate_pattern(pattern_id)
        db.insert_user_preference(pattern_id, "dismissed")

        return {"success": True, "pattern_id": pattern_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/patterns/{pattern_id}/accept")
async def accept_pattern(pattern_id: int):
    """Mark a pattern as accepted (user wants the automation)."""
    try:
        from app.patterns.database import get_pattern_db
        from app.patterns.suggestions import get_suggestion_generator
        from app.setup.entity_cache import get_entity_cache

        db = get_pattern_db()
        pattern = db.get_pattern_by_id(pattern_id)

        if not pattern:
            return {"success": False, "error": "Pattern not found"}

        cache = get_entity_cache()
        generator = get_suggestion_generator(entity_cache=cache)
        suggestion = generator._pattern_to_suggestion(pattern)

        db.insert_user_preference(pattern_id, "accepted")

        return {
            "success": True,
            "pattern_id": pattern_id,
            "command": suggestion.command if suggestion else None,
            "automation_yaml": suggestion.automation_yaml if suggestion else None,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/patterns/stats")
async def get_pattern_stats():
    """Get statistics about pattern tracking."""
    try:
        from app.patterns.database import get_pattern_db

        db = get_pattern_db()
        stats = db.get_stats()
        stats["last_sync"] = db.get_last_sync_timestamp()
        if stats["last_sync"]:
            stats["last_sync"] = stats["last_sync"].isoformat() + "Z"

        return stats
    except Exception as e:
        return {"error": str(e), "total_events": 0}


@app.get("/health")
async def health():
    """Health check endpoint."""
    settings = get_settings()
    configured = is_configured()
    return {
        "status": "ok",
        "configured": configured,
        "app": settings.app_name,
        "ai_provider": settings.ai_provider if configured else None
    }


# Run with: uvicorn app.main:app --reload
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

