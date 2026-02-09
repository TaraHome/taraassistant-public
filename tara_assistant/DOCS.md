# Tara Assistant Add-on

Tara is a self-hosted AI assistant that integrates with Home Assistant. It observes
your household routines, detects patterns, and generates automations you can inspect,
edit, and approve.

## How it works

1. **Observes** — Tara watches state changes and user actions in your Home Assistant
2. **Detects** — Identifies repeating routines and patterns in your household
3. **Suggests** — Generates readable Home Assistant automations for your approval
4. **Controls** — Accepts natural language commands to control your devices

## Installation

1. Add this repository as a custom add-on repository in Home Assistant:
   **Settings → Add-ons → Add-on Store → ⋮ (top-right) → Repositories**
2. Enter: `https://github.com/TaraHome/taraassistant-public`
3. Find **Tara Assistant** in the add-on store and click **Install**
4. Configure your AI provider in the **Configuration** tab
5. Start the add-on and click **Open Web UI** in the sidebar

## Configuration

### AI Provider

Choose one provider and fill in its settings. Leave other provider fields empty.

| Provider | Requires API Key | Local/Cloud |
|----------|-----------------|-------------|
| OpenAI | Yes | Cloud |
| Anthropic | Yes | Cloud |
| Google (Gemini) | Yes | Cloud |
| Ollama | No | Local |
| OpenAI-Compatible | Optional | Local |

### Home Assistant Connection

When running as an add-on, Tara automatically connects to Home Assistant using the
Supervisor API — no manual HA URL or token configuration needed.

## Support

- GitHub: <https://github.com/TaraHome/taraassistant-public>
- Issues: <https://github.com/TaraHome/taraassistant-public/issues>
