#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json

# Read add-on options
AI_PROVIDER=$(jq -r '.ai_provider // "openai"' "$CONFIG_PATH")
OPENAI_API_KEY=$(jq -r '.openai_api_key // ""' "$CONFIG_PATH")
OPENAI_MODEL=$(jq -r '.openai_model // "gpt-4o"' "$CONFIG_PATH")
ANTHROPIC_API_KEY=$(jq -r '.anthropic_api_key // ""' "$CONFIG_PATH")
ANTHROPIC_MODEL=$(jq -r '.anthropic_model // "claude-sonnet-4-20250514"' "$CONFIG_PATH")
GOOGLE_API_KEY=$(jq -r '.google_api_key // ""' "$CONFIG_PATH")
GOOGLE_MODEL=$(jq -r '.google_model // "gemini-2.0-flash-exp"' "$CONFIG_PATH")
OLLAMA_HOST=$(jq -r '.ollama_host // "http://localhost:11434"' "$CONFIG_PATH")
OLLAMA_MODEL=$(jq -r '.ollama_model // "llama3.1"' "$CONFIG_PATH")
OPENAI_COMPATIBLE_HOST=$(jq -r '.openai_compatible_host // ""' "$CONFIG_PATH")
OPENAI_COMPATIBLE_API_KEY=$(jq -r '.openai_compatible_api_key // ""' "$CONFIG_PATH")
OPENAI_COMPATIBLE_MODEL=$(jq -r '.openai_compatible_model // ""' "$CONFIG_PATH")

# Export environment variables for the app
export AI_PROVIDER="$AI_PROVIDER"
export OPENAI_API_KEY="$OPENAI_API_KEY"
export OPENAI_MODEL="$OPENAI_MODEL"
export ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY"
export ANTHROPIC_MODEL="$ANTHROPIC_MODEL"
export GOOGLE_API_KEY="$GOOGLE_API_KEY"
export GOOGLE_MODEL="$GOOGLE_MODEL"
export OLLAMA_HOST="$OLLAMA_HOST"
export OLLAMA_MODEL="$OLLAMA_MODEL"
export OPENAI_COMPATIBLE_HOST="$OPENAI_COMPATIBLE_HOST"
export OPENAI_COMPATIBLE_API_KEY="$OPENAI_COMPATIBLE_API_KEY"
export OPENAI_COMPATIBLE_MODEL="$OPENAI_COMPATIBLE_MODEL"

# Home Assistant connection via Supervisor API
if [ -n "$SUPERVISOR_TOKEN" ]; then
    export HA_URL="http://supervisor/core"
    export HA_TOKEN="$SUPERVISOR_TOKEN"
    echo "Running as Home Assistant add-on (using Supervisor API)"
else
    echo "Warning: SUPERVISOR_TOKEN not found, HA connection must be configured via setup wizard"
fi

# Use add-on config directory for persistent data
export DATA_DIR="/config"
ln -sf /config/data /app/data 2>/dev/null || true
mkdir -p /app/data

echo "Starting Tara Assistant (provider: $AI_PROVIDER)..."
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
