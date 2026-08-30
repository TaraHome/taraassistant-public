"""HTML templates for setup wizard."""
from typing import Optional
from app.setup.models import StoredConfig


def get_limits_html(existing_config: StoredConfig) -> str:
    """Generate quick limits settings HTML.

    This page allows users to adjust limits without re-authenticating.

    Args:
        existing_config: Current configuration to pre-fill values.

    Returns:
        HTML string for the limits settings page.
    """
    prefill_max_tokens = existing_config.limits.max_tokens_per_response
    prefill_rpm = existing_config.limits.requests_per_minute
    prefill_guardrails = getattr(existing_config.limits, 'guardrails_threshold', 70)
    prefill_backfill = getattr(existing_config.limits, 'history_backfill_days', 7)
    prefill_cleanup = getattr(existing_config.limits, 'cleanup_retention_days', 30)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TaraHome AI Assistant - Configure Limits</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}

        :root {{
            --background: #fdfbf7;
            --foreground: #4a4137;
            --primary: #ff9b85;
            --primary-dark: #f48171;
            --primary-foreground: #ffffff;
            --secondary: #d4c5f9;
            --accent: #b8e6d5;
            --info: #a7d7f0;
            --warning: #ffd89b;
            --error: #ffb3ba;
            --success: #c7e8b5;
            --muted: #f5f2ed;
            --muted-foreground: #8a8378;
            --card: #ffffff;
            --border: #e8e4dc;
            --input-background: #faf8f4;
            --shadow-sm: 0 2px 4px rgba(0, 0, 0, 0.04);
            --shadow-md: 0 10px 24px rgba(0, 0, 0, 0.08);
            --radius-lg: 18px;
            --radius-xl: 24px;
        }}

        body.dark {{
            --background: #2a2520;
            --foreground: #f5f2ed;
            --primary: #ff9b85;
            --primary-dark: #f48171;
            --primary-foreground: #2a2520;
            --secondary: #b8a8e8;
            --accent: #92cdb8;
            --info: #8fc7e3;
            --warning: #ffca7f;
            --error: #ff9ba4;
            --success: #b5dd9f;
            --muted: #3d3832;
            --muted-foreground: #a69d92;
            --card: #33302b;
            --border: #4a453f;
            --input-background: #3d3832;
            --shadow-sm: 0 2px 4px rgba(0, 0, 0, 0.35);
            --shadow-md: 0 10px 24px rgba(0, 0, 0, 0.35);
        }}

        body {{
            font-family: 'Outfit', system-ui, sans-serif;
            background: radial-gradient(circle at top left, #fff6f0 0%, #fdfbf7 40%, #f8f2eb 100%);
            min-height: 100vh;
            color: var(--foreground);
        }}

        body.dark {{
            background: radial-gradient(circle at top left, #3a322b 0%, #2a2520 45%, #231f1a 100%);
        }}

        .container {{
            max-width: 720px;
            margin: 0 auto;
            padding: 48px 20px 72px;
        }}

        .settings-topbar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }}

        .back-link {{
            color: var(--muted-foreground);
            text-decoration: none;
            font-size: 0.9rem;
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        .back-link:hover {{
            color: var(--foreground);
        }}

        .theme-toggle {{
            border: none;
            background: var(--muted);
            border-radius: 12px;
            padding: 8px 12px;
            cursor: pointer;
            font-size: 0.85rem;
            color: var(--foreground);
        }}

        header {{
            text-align: center;
            margin-bottom: 36px;
        }}

        header h1 {{
            font-size: 2rem;
            font-weight: 600;
            background: linear-gradient(120deg, var(--primary), var(--secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}

        header p {{
            color: var(--muted-foreground);
            margin-top: 10px;
        }}

        .card {{
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: var(--radius-xl);
            padding: 28px;
            box-shadow: var(--shadow-md);
            margin-bottom: 20px;
        }}

        .card h2 {{
            font-size: 1.25rem;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}

        .card-icon {{
            width: 32px;
            height: 32px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.1rem;
        }}

        .card-icon.tokens {{ background: rgba(167, 215, 240, 0.3); }}
        .card-icon.rate {{ background: rgba(255, 216, 155, 0.3); }}
        .card-icon.safety {{ background: rgba(199, 232, 181, 0.3); }}

        .card-description {{
            color: var(--muted-foreground);
            font-size: 0.9rem;
            margin-bottom: 20px;
            line-height: 1.5;
        }}

        .slider-group {{
            margin-bottom: 8px;
        }}

        .slider-header {{
            display: flex;
            justify-content: space-between;
            margin-bottom: 10px;
            align-items: center;
        }}

        .slider-header label {{
            font-weight: 500;
        }}

        .slider-value {{
            background: rgba(255, 155, 133, 0.2);
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.85rem;
            color: var(--primary-dark);
            min-width: 60px;
            text-align: center;
        }}

        input[type="range"] {{
            width: 100%;
            height: 8px;
            border-radius: 4px;
            background: rgba(74, 65, 55, 0.15);
            outline: none;
            -webkit-appearance: none;
        }}

        input[type="range"]::-webkit-slider-thumb {{
            -webkit-appearance: none;
            width: 22px;
            height: 22px;
            border-radius: 50%;
            background: linear-gradient(135deg, var(--primary), var(--secondary));
            cursor: pointer;
        }}

        .slider-hint {{
            color: var(--muted-foreground);
            font-size: 0.8rem;
            margin-top: 8px;
        }}

        .info-box {{
            background: rgba(167, 215, 240, 0.2);
            border: 1px solid rgba(167, 215, 240, 0.4);
            border-radius: 12px;
            padding: 14px;
            margin-top: 12px;
        }}

        .info-box.warning {{
            background: rgba(255, 216, 155, 0.2);
            border-color: rgba(255, 216, 155, 0.5);
        }}

        .info-box.danger {{
            background: rgba(255, 179, 186, 0.2);
            border-color: rgba(255, 179, 186, 0.5);
        }}

        .info-box p {{
            font-size: 0.85rem;
            line-height: 1.5;
            color: var(--foreground);
        }}

        .btn {{
            padding: 14px 28px;
            border: none;
            border-radius: 14px;
            font-size: 1rem;
            cursor: pointer;
            transition: all 0.2s;
            font-family: 'Outfit', system-ui, sans-serif;
            font-weight: 500;
        }}

        .btn-primary {{
            background: var(--primary);
            color: #fff;
            box-shadow: var(--shadow-sm);
            width: 100%;
        }}

        .btn-primary:hover {{
            transform: translateY(-1px);
            background: var(--primary-dark);
        }}

        .btn-primary:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }}

        .btn-secondary {{
            background: var(--muted);
            color: var(--foreground);
            border: 1px solid var(--border);
        }}

        .btn-group {{
            display: flex;
            gap: 12px;
            margin-top: 24px;
        }}

        .status-message {{
            padding: 14px;
            border-radius: 12px;
            margin-top: 16px;
            display: none;
            font-family: 'DM Sans', system-ui, sans-serif;
        }}

        .status-message.success {{
            background: rgba(199, 232, 181, 0.35);
            border: 1px solid rgba(199, 232, 181, 0.8);
            color: #3d4a3a;
            display: block;
        }}

        .status-message.error {{
            background: rgba(255, 179, 186, 0.35);
            border: 1px solid rgba(255, 179, 186, 0.8);
            color: #6b3b3f;
            display: block;
        }}

        .loading {{
            display: inline-block;
            width: 18px;
            height: 18px;
            border: 2px solid rgba(74, 65, 55, 0.2);
            border-radius: 50%;
            border-top-color: var(--primary);
            animation: spin 1s linear infinite;
            margin-right: 8px;
        }}

        @keyframes spin {{
            to {{ transform: rotate(360deg); }}
        }}

        .settings-link {{
            text-align: center;
            margin-top: 24px;
        }}

        .settings-link a {{
            color: var(--muted-foreground);
            font-size: 0.9rem;
        }}

        .settings-link a:hover {{
            color: var(--primary);
        }}

        @media (max-width: 640px) {{
            .card {{
                padding: 22px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="settings-topbar">
            <a href="/" class="back-link">&larr; Back to chat</a>
            <button class="theme-toggle" onclick="toggleTheme()" id="theme-toggle">Dark mode</button>
        </div>

        <header>
            <h1>Configure Limits</h1>
            <p>Adjust response limits and safety thresholds without re-authenticating</p>
        </header>

        <!-- Max Tokens -->
        <div class="card">
            <h2><span class="card-icon tokens">&#x1F4DD;</span> Response Length</h2>
            <p class="card-description">
                Controls the maximum length of AI responses. Higher values allow more detailed answers
                but increase API costs and response time. Most conversations work well with 2000-4000 tokens.
            </p>

            <div class="slider-group">
                <div class="slider-header">
                    <label>Max Tokens per Response</label>
                    <span class="slider-value" id="tokens-value">{prefill_max_tokens}</span>
                </div>
                <input type="range" id="max-tokens" min="500" max="16000" step="500" value="{prefill_max_tokens}"
                       oninput="document.getElementById('tokens-value').textContent = this.value">
                <p class="slider-hint">
                    <strong>500-1500:</strong> Short, concise answers &nbsp;|&nbsp;
                    <strong>2000-4000:</strong> Balanced &nbsp;|&nbsp;
                    <strong>8000+:</strong> Long, detailed explanations
                </p>
            </div>
        </div>

        <!-- Rate Limiting -->
        <div class="card">
            <h2><span class="card-icon rate">&#x23F1;</span> Rate Limiting</h2>
            <p class="card-description">
                Limits how many requests can be made per minute to prevent runaway API costs and
                accidental overuse. This applies across all users of this assistant instance.
            </p>

            <div class="slider-group">
                <div class="slider-header">
                    <label>Requests per Minute</label>
                    <span class="slider-value" id="rpm-value">{prefill_rpm}</span>
                </div>
                <input type="range" id="requests-per-minute" min="5" max="60" step="5" value="{prefill_rpm}"
                       oninput="document.getElementById('rpm-value').textContent = this.value">
                <p class="slider-hint">
                    <strong>5-10:</strong> Conservative (personal use) &nbsp;|&nbsp;
                    <strong>15-30:</strong> Normal &nbsp;|&nbsp;
                    <strong>40+:</strong> High throughput
                </p>
            </div>

            <div class="info-box">
                <p>Exceeding this limit returns a "rate limited" error until the next minute window.</p>
            </div>
        </div>

        <!-- Safety Guardrails -->
        <div class="card">
            <h2><span class="card-icon safety">&#x1F6E1;</span> Safety Guardrails</h2>
            <p class="card-description">
                The AI evaluates each Home Assistant command with a risk score (0-100) before execution.
                Commands with scores above this threshold are blocked. This protects against potentially
                harmful automations like unlocking doors, disabling alarms, or high-risk device changes.
            </p>

            <div class="slider-group">
                <div class="slider-header">
                    <label>Risk Threshold</label>
                    <span class="slider-value" id="guardrails-value">{prefill_guardrails}</span>
                </div>
                <input type="range" id="guardrails-threshold" min="0" max="100" step="5" value="{prefill_guardrails}"
                       oninput="updateGuardrailsUI(this.value)">
                <p class="slider-hint" id="guardrails-hint">
                    Commands scoring above this value will be blocked
                </p>
            </div>

            <div class="info-box" id="guardrails-info">
                <p id="guardrails-explanation">Balanced protection for most homes.</p>
            </div>
        </div>

        <!-- Pattern Learning -->
        <div class="card">
            <h2><span class="card-icon tokens">&#x1F9E0;</span> Pattern Learning</h2>
            <p class="card-description">
                Configure how TaraAssistant syncs and retains Home Assistant history for pattern detection.
            </p>

            <div class="slider-group">
                <div class="slider-header">
                    <label>History Backfill (Days)</label>
                </div>
                <input type="number" id="history-backfill-days" min="0" max="3650" step="1" value="{prefill_backfill}" style="width: 100%; padding: 8px; border: 1px solid var(--border); border-radius: 8px; background: var(--input-background); color: var(--foreground); margin-bottom: 8px;">
                <p class="slider-hint">
                    How far back the first sync pulls Home Assistant history. 0 = as far back as available (up to ~10 years). Actual reach is limited by your HA recorder retention (purge_keep_days).
                </p>
            </div>

            <div class="slider-group" style="margin-top: 24px;">
                <div class="slider-header">
                    <label>Cleanup Retention (Days)</label>
                </div>
                <input type="number" id="cleanup-retention-days" min="0" max="3650" step="1" value="{prefill_cleanup}" style="width: 100%; padding: 8px; border: 1px solid var(--border); border-radius: 8px; background: var(--input-background); color: var(--foreground); margin-bottom: 8px;">
                <p class="slider-hint">
                    How many days of collected events to keep. 0 = never delete. Set this &gt;= the backfill window, or backfilled history will be pruned.
                </p>
            </div>

            <button class="btn btn-secondary" onclick="saveAndBackfill()" id="backfill-now-btn" style="margin-top: 16px; width: 100%;">
                Save &amp; Backfill Now
            </button>
        </div>

        <div id="save-status" class="status-message"></div>

        <button class="btn btn-primary" onclick="saveLimits()" id="save-btn">
            Save Changes
        </button>

        <div class="settings-link">
            <a href="/settings">Need to change API keys or Home Assistant connection? &rarr; Full Settings</a>
        </div>
    </div>

    <script>
        function updateGuardrailsUI(value) {{
            document.getElementById('guardrails-value').textContent = value;
            const info = document.getElementById('guardrails-info');
            const explanation = document.getElementById('guardrails-explanation');
            const hint = document.getElementById('guardrails-hint');

            if (value === '0') {{
                info.className = 'info-box danger';
                explanation.innerHTML = '<strong>Disabled:</strong> All commands will be executed without safety checks. Only use this for testing or if you have other security measures in place.';
                hint.textContent = 'Safety checks completely disabled';
            }} else if (value < 30) {{
                info.className = 'info-box';
                explanation.innerHTML = '<strong>Strict:</strong> Only very low-risk commands (score < ' + value + ') are allowed. May block legitimate automations - best for high-security environments.';
                hint.textContent = 'Very restrictive - many commands may be blocked';
            }} else if (value < 50) {{
                info.className = 'info-box';
                explanation.innerHTML = '<strong>Cautious:</strong> Only low-risk commands (score < ' + value + ') are allowed. Safer for homes with children or shared access.';
                hint.textContent = 'Only clearly safe commands allowed';
            }} else if (value < 70) {{
                info.className = 'info-box warning';
                explanation.innerHTML = '<strong>Balanced:</strong> Commands with risk score < ' + value + ' are allowed. Good default for most homes.';
                hint.textContent = 'Medium and high-risk commands blocked';
            }} else if (value < 90) {{
                info.className = 'info-box warning';
                explanation.innerHTML = '<strong>Permissive:</strong> Most commands (score < ' + value + ') are allowed. Good for advanced users who understand their smart home setup.';
                hint.textContent = 'Only high-risk commands blocked';
            }} else {{
                info.className = 'info-box danger';
                explanation.innerHTML = '<strong>Very Permissive:</strong> Almost all commands are allowed. Only the most dangerous commands (score >= ' + value + ') are blocked.';
                hint.textContent = 'Only extremely high-risk commands blocked';
            }}
        }}

        function buildLimitsPayload() {{
            return {{
                limits: {{
                    max_tokens_per_response: parseInt(document.getElementById('max-tokens').value),
                    requests_per_minute: parseInt(document.getElementById('requests-per-minute').value),
                    guardrails_threshold: parseInt(document.getElementById('guardrails-threshold').value),
                    history_backfill_days: parseInt(document.getElementById('history-backfill-days').value),
                    cleanup_retention_days: parseInt(document.getElementById('cleanup-retention-days').value)
                }}
            }};
        }}

        async function saveLimits() {{
            const btn = document.getElementById('save-btn');
            const status = document.getElementById('save-status');

            btn.innerHTML = '<span class="loading"></span>Saving...';
            btn.disabled = true;

            const limits = buildLimitsPayload();

            try {{
                const res = await fetch('/api/setup/save-limits', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(limits)
                }});

                const data = await res.json();

                if (data.success) {{
                    status.className = 'status-message success';
                    status.textContent = 'Settings saved successfully!';
                    btn.innerHTML = 'Save Changes';
                    btn.disabled = false;
                }} else {{
                    status.className = 'status-message error';
                    status.textContent = data.detail || 'Failed to save settings';
                    btn.innerHTML = 'Save Changes';
                    btn.disabled = false;
                }}
            }} catch (e) {{
                status.className = 'status-message error';
                status.textContent = 'Error saving settings. Please try again.';
                btn.innerHTML = 'Save Changes';
                btn.disabled = false;
            }}
        }}

        async function saveAndBackfill() {{
            const btn = document.getElementById('backfill-now-btn');
            const status = document.getElementById('save-status');

            btn.innerHTML = '<span class="loading"></span>Backfilling...';
            btn.disabled = true;

            const limits = buildLimitsPayload();

            try {{
                const saveRes = await fetch('/api/setup/save-limits', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(limits)
                }});

                const saveData = await saveRes.json();
                if (!saveData.success) {{
                    status.className = 'status-message error';
                    status.textContent = saveData.detail || 'Failed to save settings before backfill';
                    btn.innerHTML = 'Save &amp; Backfill Now';
                    btn.disabled = false;
                    return;
                }}
                
                const syncRes = await fetch('/api/patterns/sync?full=true', {{ method: 'POST' }});
                const syncData = await syncRes.json();
                
                if (syncData.success) {{
                    status.className = 'status-message success';
                    status.textContent = 'Backfilled ' + syncData.events_synced + ' events successfully!';
                }} else {{
                    status.className = 'status-message error';
                    status.textContent = syncData.error || 'Failed to run backfill';
                }}
            }} catch (e) {{
                status.className = 'status-message error';
                status.textContent = 'Error during save and backfill. Please try again.';
            }} finally {{
                btn.innerHTML = 'Save &amp; Backfill Now';
                btn.disabled = false;
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

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {{
            const storedTheme = localStorage.getItem('theme');
            if (storedTheme === 'dark') {{
                setTheme(true);
            }} else {{
                setTheme(false);
            }}

            // Initialize guardrails UI
            updateGuardrailsUI('{prefill_guardrails}');
        }});
    </script>
</body>
</html>'''


def get_setup_html(existing_config: Optional[StoredConfig] = None) -> str:
    """Generate setup wizard HTML.

    Args:
        existing_config: If provided, pre-fills the form for settings mode.

    Returns:
        HTML string for the setup wizard.
    """
    is_settings = existing_config is not None
    title = "Settings" if is_settings else "Setup Wizard"

    # Pre-fill values if editing
    prefill_provider = existing_config.provider.provider.value if existing_config else ""
    prefill_model = existing_config.provider.model if existing_config else ""
    prefill_host = existing_config.provider.host or "" if existing_config else ""
    prefill_max_tokens = existing_config.limits.max_tokens_per_response if existing_config else 4096
    prefill_rpm = existing_config.limits.requests_per_minute if existing_config else 20
    prefill_guardrails = getattr(existing_config.limits, 'guardrails_threshold', 70) if existing_config else 70
    prefill_backfill = getattr(existing_config.limits, 'history_backfill_days', 7) if existing_config else 7
    prefill_ha_url = existing_config.home_assistant.url if existing_config else ""

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TaraHome AI Assistant - {title}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}

        :root {{
            --background: #fdfbf7;
            --foreground: #4a4137;
            --primary: #ff9b85;
            --primary-dark: #f48171;
            --primary-foreground: #ffffff;
            --secondary: #d4c5f9;
            --accent: #b8e6d5;
            --info: #a7d7f0;
            --warning: #ffd89b;
            --error: #ffb3ba;
            --success: #c7e8b5;
            --muted: #f5f2ed;
            --muted-foreground: #8a8378;
            --card: #ffffff;
            --border: #e8e4dc;
            --input-background: #faf8f4;
            --shadow-sm: 0 2px 4px rgba(0, 0, 0, 0.04);
            --shadow-md: 0 10px 24px rgba(0, 0, 0, 0.08);
            --radius-lg: 18px;
            --radius-xl: 24px;
        }}

        body.dark {{
            --background: #2a2520;
            --foreground: #f5f2ed;
            --primary: #ff9b85;
            --primary-dark: #f48171;
            --primary-foreground: #2a2520;
            --secondary: #b8a8e8;
            --accent: #92cdb8;
            --info: #8fc7e3;
            --warning: #ffca7f;
            --error: #ff9ba4;
            --success: #b5dd9f;
            --muted: #3d3832;
            --muted-foreground: #a69d92;
            --card: #33302b;
            --border: #4a453f;
            --input-background: #3d3832;
            --shadow-sm: 0 2px 4px rgba(0, 0, 0, 0.35);
            --shadow-md: 0 10px 24px rgba(0, 0, 0, 0.35);
        }}

        body {{
            font-family: 'Outfit', system-ui, sans-serif;
            background: radial-gradient(circle at top left, #fff6f0 0%, #fdfbf7 40%, #f8f2eb 100%);
            min-height: 100vh;
            color: var(--foreground);
        }}

        body.dark {{
            background: radial-gradient(circle at top left, #3a322b 0%, #2a2520 45%, #231f1a 100%);
        }}

        .container {{
            max-width: 720px;
            margin: 0 auto;
            padding: 48px 20px 72px;
        }}

        .settings-topbar {{
            display: flex;
            justify-content: flex-end;
            margin-bottom: 12px;
        }}

        .theme-toggle {{
            border: none;
            background: var(--muted);
            border-radius: 12px;
            padding: 8px 12px;
            cursor: pointer;
            font-size: 0.85rem;
            color: var(--foreground);
        }}

        header {{
            text-align: center;
            margin-bottom: 36px;
        }}

        header h1 {{
            font-size: 2rem;
            font-weight: 600;
            background: linear-gradient(120deg, var(--primary), var(--secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}

        header p {{
            color: var(--muted-foreground);
            margin-top: 10px;
        }}

        .progress {{
            display: flex;
            justify-content: center;
            gap: 12px;
            margin-bottom: 32px;
            flex-wrap: wrap;
        }}

        .progress-step {{
            width: 40px;
            height: 40px;
            border-radius: 50%;
            background: var(--muted);
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            transition: all 0.3s;
            position: relative;
            color: var(--muted-foreground);
            box-shadow: var(--shadow-sm);
        }}

        .progress-step.active {{
            background: linear-gradient(135deg, var(--primary), var(--secondary));
            color: #fff;
        }}

        .progress-step.completed {{
            background: var(--success);
            color: #3d4a3a;
        }}

        .progress-step.completed::after {{
            content: "\2713";
        }}

        .progress-line {{
            width: 36px;
            height: 2px;
            background: rgba(74, 65, 55, 0.15);
            align-self: center;
        }}

        .progress-line.completed {{
            background: var(--success);
        }}

        .step {{
            display: none;
            animation: fadeIn 0.3s ease;
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: var(--radius-xl);
            padding: 28px;
            box-shadow: var(--shadow-md);
        }}

        .step.active {{
            display: block;
        }}

        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}

        .step h2 {{
            font-size: 1.5rem;
            margin-bottom: 8px;
        }}

        .step p.subtitle {{
            color: var(--muted-foreground);
            margin-bottom: 24px;
        }}

        .form-group {{
            margin-bottom: 20px;
        }}

        label {{
            display: block;
            margin-bottom: 8px;
            color: var(--muted-foreground);
            font-size: 0.9rem;
        }}

        input[type="text"],
        input[type="password"],
        input[type="url"],
        input[type="number"],
        select {{
            width: 100%;
            padding: 14px 16px;
            border: 1px solid var(--border);
            border-radius: 14px;
            background: var(--input-background);
            color: var(--foreground);
            font-size: 1rem;
            outline: none;
            transition: border-color 0.3s, box-shadow 0.3s;
            font-family: 'DM Sans', system-ui, sans-serif;
        }}

        input:focus, select:focus {{
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(255, 155, 133, 0.2);
        }}

        input::placeholder {{
            color: #b3aaa0;
        }}

        .radio-group {{
            display: flex;
            flex-direction: column;
            gap: 12px;
        }}

        .radio-option {{
            padding: 18px;
            border: 1px solid var(--border);
            border-radius: 16px;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 15px;
            background: var(--card);
        }}

        .radio-option:hover {{
            border-color: rgba(255, 155, 133, 0.5);
            box-shadow: var(--shadow-sm);
        }}

        .radio-option.selected {{
            border-color: var(--primary);
            background: rgba(255, 155, 133, 0.12);
        }}

        .radio-option input {{
            display: none;
        }}

        .radio-dot {{
            width: 22px;
            height: 22px;
            border: 2px solid rgba(74, 65, 55, 0.3);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
        }}

        .radio-option.selected .radio-dot {{
            border-color: var(--primary);
        }}

        .radio-option.selected .radio-dot::after {{
            content: "";
            width: 10px;
            height: 10px;
            background: var(--primary);
            border-radius: 50%;
        }}

        .radio-content h3 {{
            font-size: 1rem;
            margin-bottom: 4px;
        }}

        .radio-content p {{
            font-size: 0.85rem;
            color: var(--muted-foreground);
        }}

        .slider-group {{
            margin-bottom: 24px;
        }}

        .slider-header {{
            display: flex;
            justify-content: space-between;
            margin-bottom: 10px;
            align-items: center;
        }}

        .slider-value {{
            background: rgba(255, 155, 133, 0.2);
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.85rem;
            color: var(--primary-dark);
        }}

        input[type="range"] {{
            width: 100%;
            height: 8px;
            border-radius: 4px;
            background: rgba(74, 65, 55, 0.15);
            outline: none;
            -webkit-appearance: none;
        }}

        input[type="range"]::-webkit-slider-thumb {{
            -webkit-appearance: none;
            width: 22px;
            height: 22px;
            border-radius: 50%;
            background: linear-gradient(135deg, var(--primary), var(--secondary));
            cursor: pointer;
        }}

        .btn {{
            padding: 12px 24px;
            border: none;
            border-radius: 14px;
            font-size: 0.95rem;
            cursor: pointer;
            transition: all 0.2s;
            font-family: 'Outfit', system-ui, sans-serif;
        }}

        .btn-primary {{
            background: var(--primary);
            color: #fff;
            box-shadow: var(--shadow-sm);
        }}

        .btn-primary:hover {{
            transform: translateY(-1px);
            background: var(--primary-dark);
        }}

        .btn-primary:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }}

        .btn-secondary {{
            background: var(--muted);
            color: var(--foreground);
            border: 1px solid var(--border);
        }}

        .btn-secondary:hover {{
            background: #efeae2;
        }}

        .btn-group {{
            display: flex;
            gap: 12px;
            margin-top: 24px;
            flex-wrap: wrap;
        }}

        .btn-validate {{
            background: rgba(199, 232, 181, 0.4);
            color: #3d4a3a;
            border: 1px solid rgba(199, 232, 181, 0.8);
        }}

        .btn-validate:hover {{
            background: rgba(199, 232, 181, 0.6);
        }}

        .status-message {{
            padding: 14px;
            border-radius: 12px;
            margin-top: 16px;
            display: none;
            font-family: 'DM Sans', system-ui, sans-serif;
        }}

        .status-message.success {{
            background: rgba(199, 232, 181, 0.35);
            border: 1px solid rgba(199, 232, 181, 0.8);
            color: #3d4a3a;
            display: block;
        }}

        .status-message.error {{
            background: rgba(255, 179, 186, 0.35);
            border: 1px solid rgba(255, 179, 186, 0.8);
            color: #6b3b3f;
            display: block;
        }}

        .status-message.info {{
            background: rgba(167, 215, 240, 0.35);
            border: 1px solid rgba(167, 215, 240, 0.8);
            color: #35566a;
            display: block;
        }}

        .summary-card {{
            background: var(--muted);
            border-radius: 16px;
            padding: 16px;
            margin-bottom: 12px;
            border: 1px solid var(--border);
        }}

        .summary-card h3 {{
            font-size: 0.85rem;
            color: var(--muted-foreground);
            margin-bottom: 6px;
        }}

        .summary-card p {{
            font-size: 1rem;
        }}

        .loading {{
            display: inline-block;
            width: 18px;
            height: 18px;
            border: 2px solid rgba(74, 65, 55, 0.2);
            border-radius: 50%;
            border-top-color: var(--primary);
            animation: spin 1s linear infinite;
            margin-right: 8px;
        }}

        @keyframes spin {{
            to {{ transform: rotate(360deg); }}
        }}

        .hidden {{
            display: none !important;
        }}

        .ollama-fields {{
            display: none;
        }}

        .api-key-fields {{
            display: none;
        }}

        .openai-compatible-fields {{
            display: none;
        }}

        .limit-section {{
            margin-bottom: 28px;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--border);
        }}

        .limit-section:last-of-type {{
            border-bottom: none;
            margin-bottom: 0;
            padding-bottom: 0;
        }}

        .limit-title {{
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 6px;
            color: var(--foreground);
        }}

        .limit-description {{
            color: var(--muted-foreground);
            font-size: 0.85rem;
            margin-bottom: 16px;
            line-height: 1.5;
        }}

        .slider-hint {{
            color: var(--muted-foreground);
            font-size: 0.8rem;
            margin-top: 8px;
        }}

        .info-box {{
            background: rgba(167, 215, 240, 0.2);
            border: 1px solid rgba(167, 215, 240, 0.4);
            border-radius: 12px;
            padding: 12px;
            margin-top: 12px;
        }}

        .info-box.warning {{
            background: rgba(255, 216, 155, 0.2);
            border-color: rgba(255, 216, 155, 0.5);
        }}

        .info-box.danger {{
            background: rgba(255, 179, 186, 0.2);
            border-color: rgba(255, 179, 186, 0.5);
        }}

        .info-box p {{
            font-size: 0.85rem;
            line-height: 1.4;
            margin: 0;
        }}

        @media (max-width: 640px) {{
            .step {{
                padding: 22px;
            }}

            .btn-group {{
                flex-direction: column;
                align-items: stretch;
            }}
        }}
    </style>

</head>
<body>
    <div class="container">
        <div class="settings-topbar">
            <button class="theme-toggle" onclick="toggleTheme()" id="theme-toggle">Dark mode</button>
        </div>
        <header>
            <h1>TaraHome AI Assistant</h1>
            <p>{"Configure your settings" if is_settings else "Let's get you set up"}</p>
            {"<p style='margin-top: 12px;'><a href='/settings/limits' style='color: var(--primary); font-size: 0.9rem;'>Just need to adjust limits? &rarr; Quick Settings</a></p>" if is_settings else ""}
        </header>

        <div class="progress">
            <div class="progress-step active" data-step="1">1</div>
            <div class="progress-line"></div>
            <div class="progress-step" data-step="2">2</div>
            <div class="progress-line"></div>
            <div class="progress-step" data-step="3">3</div>
            <div class="progress-line"></div>
            <div class="progress-step" data-step="4">4</div>
            <div class="progress-line"></div>
            <div class="progress-step" data-step="5">5</div>
        </div>

        <!-- Step 1: Provider Selection -->
        <div class="step active" data-step="1">
            <h2>Choose AI Provider</h2>
            <p class="subtitle">Select which AI service you want to use</p>

            <div class="radio-group">
                <label class="radio-option {"selected" if prefill_provider == "anthropic" else ""}" onclick="selectProvider('anthropic')">
                    <input type="radio" name="provider" value="anthropic" {"checked" if prefill_provider == "anthropic" else ""}>
                    <div class="radio-dot"></div>
                    <div class="radio-content">
                        <h3>Claude (Anthropic)</h3>
                        <p>Advanced reasoning, great for complex automations</p>
                    </div>
                </label>

                <label class="radio-option {"selected" if prefill_provider == "openai" else ""}" onclick="selectProvider('openai')">
                    <input type="radio" name="provider" value="openai" {"checked" if prefill_provider == "openai" else ""}>
                    <div class="radio-dot"></div>
                    <div class="radio-content">
                        <h3>GPT (OpenAI)</h3>
                        <p>Versatile and widely used, good all-around choice</p>
                    </div>
                </label>

                <label class="radio-option {"selected" if prefill_provider == "ollama" else ""}" onclick="selectProvider('ollama')">
                    <input type="radio" name="provider" value="ollama" {"checked" if prefill_provider == "ollama" else ""}>
                    <div class="radio-dot"></div>
                    <div class="radio-content">
                        <h3>Ollama (Local)</h3>
                        <p>Run AI locally, no API key needed</p>
                        <p style="font-size: 0.75rem; color: var(--warning); margin-top: 4px;">⚠️ Use a model with tool calling support (e.g. llama3.1, mistral-nemo)</p>
                    </div>
                </label>

                <label class="radio-option {"selected" if prefill_provider == "google" else ""}" onclick="selectProvider('google')">
                    <input type="radio" name="provider" value="google" {"checked" if prefill_provider == "google" else ""}>
                    <div class="radio-dot"></div>
                    <div class="radio-content">
                        <h3>Gemini (Google)</h3>
                        <p>Google's latest AI models, great performance</p>
                    </div>
                </label>

                <label class="radio-option {"selected" if prefill_provider == "openai_compatible" else ""}" onclick="selectProvider('openai_compatible')">
                    <input type="radio" name="provider" value="openai_compatible" {"checked" if prefill_provider == "openai_compatible" else ""}>
                    <div class="radio-dot"></div>
                    <div class="radio-content">
                        <h3>OpenAI Compatible</h3>
                        <p>OpenWebUI, llama.cpp, LM Studio, vLLM, LocalAI</p>
                    </div>
                </label>
            </div>

            <div class="btn-group">
                <button class="btn btn-primary" onclick="goToStep(2)" id="step1-next" {"" if prefill_provider else "disabled"}>Next</button>
            </div>
        </div>

        <!-- Step 2: API Credentials -->
        <div class="step" data-step="2">
            <h2>API Credentials</h2>
            <p class="subtitle" id="step2-subtitle">Enter your API key</p>

            <div class="api-key-fields" id="api-key-section">
                <div class="form-group">
                    <label for="api-key">API Key</label>
                    <input type="password" id="api-key" placeholder="sk-... or your API key">
                </div>
            </div>

            <div class="ollama-fields" id="ollama-section">
                <div class="form-group">
                    <label for="ollama-host">Ollama Host URL</label>
                    <input type="url" id="ollama-host" placeholder="http://localhost:11434" value="{prefill_host or 'http://localhost:11434'}">
                </div>
            </div>

            <div class="openai-compatible-fields" id="openai-compatible-section">
                <div class="form-group">
                    <label for="openai-compatible-host">Base URL</label>
                    <input type="url" id="openai-compatible-host" placeholder="https://your-server.com/v1 or http://localhost:8080/v1" value="{prefill_host if prefill_provider == 'openai_compatible' else ''}">
                    <p style="font-size: 0.75rem; color: var(--muted-foreground); margin-top: 6px;">
                        OpenWebUI: https://your-domain/api/v1 | llama.cpp: http://localhost:8080/v1
                    </p>
                </div>
                <div class="form-group">
                    <label for="openai-compatible-key">API Key <span style="color: var(--muted-foreground);">(optional)</span></label>
                    <input type="password" id="openai-compatible-key" placeholder="Leave empty if not required">
                </div>
            </div>

            <button class="btn btn-validate" onclick="validateProvider()" id="validate-provider-btn">
                Validate Connection
            </button>

            <div id="provider-status" class="status-message"></div>

            <div class="form-group hidden" id="model-section">
                <label for="model-select">Select Model</label>
                <select id="model-select">
                    <option value="">Select a model...</option>
                </select>
            </div>

            <div class="btn-group">
                <button class="btn btn-secondary" onclick="goToStep(1)">Back</button>
                <button class="btn btn-primary" onclick="goToStep(3)" id="step2-next" disabled>Next</button>
            </div>
        </div>

        <!-- Step 3: Limits -->
        <div class="step" data-step="3">
            <h2>Configure Limits</h2>
            <p class="subtitle">Set usage limits and safety thresholds</p>

            <!-- Response Length -->
            <div class="limit-section">
                <h3 class="limit-title">Response Length</h3>
                <p class="limit-description">
                    Controls the maximum length of AI responses. Higher values allow more detailed answers
                    but increase API costs and response time.
                </p>
                <div class="slider-group">
                    <div class="slider-header">
                        <label>Max Tokens per Response</label>
                        <span class="slider-value" id="tokens-value">{prefill_max_tokens}</span>
                    </div>
                    <input type="range" id="max-tokens" min="500" max="16000" step="500" value="{prefill_max_tokens}"
                           oninput="document.getElementById('tokens-value').textContent = this.value">
                    <p class="slider-hint">
                        <strong>500-1500:</strong> Concise &nbsp;|&nbsp;
                        <strong>2000-4000:</strong> Balanced &nbsp;|&nbsp;
                        <strong>8000+:</strong> Detailed
                    </p>
                </div>
            </div>

            <!-- Rate Limiting -->
            <div class="limit-section">
                <h3 class="limit-title">Rate Limiting</h3>
                <p class="limit-description">
                    Limits requests per minute to prevent runaway API costs. Applies across all users of this instance.
                </p>
                <div class="slider-group">
                    <div class="slider-header">
                        <label>Requests per Minute</label>
                        <span class="slider-value" id="rpm-value">{prefill_rpm}</span>
                    </div>
                    <input type="range" id="requests-per-minute" min="5" max="60" step="5" value="{prefill_rpm}"
                           oninput="document.getElementById('rpm-value').textContent = this.value">
                    <p class="slider-hint">
                        <strong>5-10:</strong> Conservative &nbsp;|&nbsp;
                        <strong>15-30:</strong> Normal &nbsp;|&nbsp;
                        <strong>40+:</strong> High throughput
                    </p>
                </div>
            </div>

            <!-- Safety Guardrails -->
            <div class="limit-section">
                <h3 class="limit-title">Safety Guardrails</h3>
                <p class="limit-description">
                    The AI evaluates each Home Assistant command with a risk score (0-100). Commands above this threshold are blocked,
                    protecting against harmful automations like unlocking doors or disabling alarms.
                </p>
                <div class="slider-group">
                    <div class="slider-header">
                        <label>Risk Threshold</label>
                        <span class="slider-value" id="guardrails-value">{prefill_guardrails}</span>
                    </div>
                    <input type="range" id="guardrails-threshold" min="0" max="100" step="5" value="{prefill_guardrails}"
                           oninput="updateGuardrailsLabel(this.value)">
                    <p class="slider-hint" id="guardrails-hint">
                        Commands scoring above this value will be blocked
                    </p>
                </div>
                <div class="info-box" id="guardrails-info">
                    <p id="guardrails-desc">Balanced protection for most homes.</p>
                </div>
            </div>

            <!-- Pattern Learning -->
            <div class="limit-section">
                <h3 class="limit-title">Pattern Learning</h3>
                <div class="form-group">
                    <label for="history-backfill-days">Initial History Backfill (Days)</label>
                    <input type="number" id="history-backfill-days" min="0" max="3650" step="1" value="{prefill_backfill}">
                    <p class="slider-hint">
                        How far back the first sync pulls Home Assistant history. Default 7 days. Increase for more history to learn from (0 = as far back as available; limited by your HA recorder retention).
                    </p>
                </div>
            </div>

            <div class="btn-group">
                <button class="btn btn-secondary" onclick="goToStep(2)">Back</button>
                <button class="btn btn-primary" onclick="goToStep(4)">Next</button>
            </div>
        </div>

        <!-- Step 4: Home Assistant -->
        <div class="step" data-step="4">
            <h2>Connect Home Assistant</h2>
            <p class="subtitle">Enter your Home Assistant details</p>

            <div class="form-group">
                <label for="ha-url">Home Assistant URL</label>
                <input type="url" id="ha-url" placeholder="http://192.168.1.100:8123" value="{prefill_ha_url}">
                <p style="color: #666; font-size: 0.8rem; margin-top: 5px;">
                    Use your Home Assistant's IP address (e.g., <code>http://192.168.1.100:8123</code>) rather than <code>homeassistant.local</code>, which may not resolve inside Docker.
                </p>
            </div>

            <div class="form-group">
                <label for="ha-token">Long-Lived Access Token</label>
                <input type="password" id="ha-token" placeholder="Your access token">
                <p style="color: #666; font-size: 0.8rem; margin-top: 5px;">
                    Create one in HA: Profile &rarr; Long-Lived Access Tokens
                </p>
            </div>

            <button class="btn btn-validate" onclick="validateHA()" id="validate-ha-btn">
                Test Connection
            </button>

            <div id="ha-status" class="status-message"></div>

            <div class="btn-group">
                <button class="btn btn-secondary" onclick="goToStep(3)">Back</button>
                <button class="btn btn-primary" onclick="goToStep(5)" id="step4-next" disabled>Next</button>
            </div>
        </div>

        <!-- Step 5: Summary -->
        <div class="step" data-step="5">
            <h2>Review & Save</h2>
            <p class="subtitle">Confirm your configuration</p>

            <div class="summary-card">
                <h3>AI Provider</h3>
                <p id="summary-provider">-</p>
            </div>

            <div class="summary-card">
                <h3>Model</h3>
                <p id="summary-model">-</p>
            </div>

            <div class="summary-card">
                <h3>Limits</h3>
                <p id="summary-limits">-</p>
            </div>

            <div class="summary-card">
                <h3>Home Assistant</h3>
                <p id="summary-ha">-</p>
            </div>

            <div id="save-status" class="status-message"></div>

            <div class="btn-group">
                <button class="btn btn-secondary" onclick="goToStep(4)">Back</button>
                <button class="btn btn-primary" onclick="saveConfig()" id="save-btn">
                    Save & Continue
                </button>
            </div>
        </div>
    </div>

    <script>
        // State
        let currentStep = 1;
        let selectedProvider = '{prefill_provider}';
        let validatedProvider = {'true' if is_settings else 'false'};
        let validatedHA = {'true' if is_settings else 'false'};
        let availableModels = [];

        // Provider selection
        function selectProvider(provider) {{
            selectedProvider = provider;
            validatedProvider = false;

            // Update UI
            document.querySelectorAll('.radio-option').forEach(opt => opt.classList.remove('selected'));
            document.querySelector(`input[value="${{provider}}"]`).closest('.radio-option').classList.add('selected');
            document.getElementById('step1-next').disabled = false;

            // Reset step 2
            document.getElementById('step2-next').disabled = true;
            document.getElementById('model-section').classList.add('hidden');
            document.getElementById('provider-status').className = 'status-message';
        }}

        // Navigation
        function goToStep(step) {{
            // Update step visibility
            document.querySelectorAll('.step').forEach(s => s.classList.remove('active'));
            document.querySelector(`.step[data-step="${{step}}"]`).classList.add('active');

            // Update progress
            document.querySelectorAll('.progress-step').forEach((ps, i) => {{
                ps.classList.remove('active', 'completed');
                if (i + 1 < step) ps.classList.add('completed');
                if (i + 1 === step) ps.classList.add('active');
            }});

            document.querySelectorAll('.progress-line').forEach((pl, i) => {{
                pl.classList.toggle('completed', i + 1 < step);
            }});

            // Step-specific setup
            if (step === 2) {{
                setupStep2();
            }} else if (step === 5) {{
                updateSummary();
            }}

            currentStep = step;
        }}

        function setupStep2() {{
            const isOllama = selectedProvider === 'ollama';
            const isOpenAICompatible = selectedProvider === 'openai_compatible';
            const needsApiKey = !isOllama && !isOpenAICompatible;

            document.getElementById('api-key-section').style.display = needsApiKey ? 'block' : 'none';
            document.getElementById('ollama-section').style.display = isOllama ? 'block' : 'none';
            document.getElementById('openai-compatible-section').style.display = isOpenAICompatible ? 'block' : 'none';

            if (selectedProvider === 'anthropic') {{
                document.getElementById('step2-subtitle').textContent = 'Enter your Anthropic API key';
                document.getElementById('api-key').placeholder = 'sk-ant-...';
            }} else if (selectedProvider === 'openai') {{
                document.getElementById('step2-subtitle').textContent = 'Enter your OpenAI API key';
                document.getElementById('api-key').placeholder = 'sk-...';
            }} else if (selectedProvider === 'google') {{
                document.getElementById('step2-subtitle').textContent = 'Enter your Google AI API key';
                document.getElementById('api-key').placeholder = 'AIza...';
            }} else if (selectedProvider === 'openai_compatible') {{
                document.getElementById('step2-subtitle').textContent = 'Configure your OpenAI-compatible server';
            }} else {{
                document.getElementById('step2-subtitle').textContent = 'Configure your local Ollama instance';
            }}
        }}

        // Validation
        async function validateProvider() {{
            const btn = document.getElementById('validate-provider-btn');
            const status = document.getElementById('provider-status');

            btn.innerHTML = '<span class="loading"></span>Validating...';
            btn.disabled = true;

            try {{
                const body = {{ provider: selectedProvider }};
                if (selectedProvider === 'ollama') {{
                    body.host = document.getElementById('ollama-host').value;
                }} else if (selectedProvider === 'openai_compatible') {{
                    body.host = document.getElementById('openai-compatible-host').value;
                    const apiKey = document.getElementById('openai-compatible-key').value;
                    if (apiKey) body.api_key = apiKey;
                }} else {{
                    body.api_key = document.getElementById('api-key').value;
                }}

                const res = await fetch('/api/setup/validate/provider', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(body)
                }});

                const data = await res.json();

                if (data.valid) {{
                    status.className = 'status-message success';
                    status.textContent = 'Connection successful!';
                    validatedProvider = true;

                    // Populate models
                    availableModels = data.models;
                    const modelSelect = document.getElementById('model-select');
                    modelSelect.innerHTML = '<option value="">Select a model...</option>';
                    data.models.forEach(model => {{
                        const opt = document.createElement('option');
                        opt.value = model;
                        opt.textContent = model;
                        modelSelect.appendChild(opt);
                    }});

                    // Pre-select first model or existing
                    if ('{prefill_model}' && data.models.includes('{prefill_model}')) {{
                        modelSelect.value = '{prefill_model}';
                    }} else if (data.models.length > 0) {{
                        modelSelect.value = data.models[0];
                    }}

                    document.getElementById('model-section').classList.remove('hidden');
                    document.getElementById('step2-next').disabled = false;

                    if (data.error) {{
                        status.className = 'status-message info';
                        status.textContent = data.error;
                    }}
                }} else {{
                    status.className = 'status-message error';
                    status.textContent = data.error || 'Validation failed';
                    validatedProvider = false;
                }}
            }} catch (e) {{
                status.className = 'status-message error';
                status.textContent = 'Connection error. Please check your network.';
                validatedProvider = false;
            }}

            btn.innerHTML = 'Validate Connection';
            btn.disabled = false;
        }}

        async function validateHA() {{
            const btn = document.getElementById('validate-ha-btn');
            const status = document.getElementById('ha-status');

            btn.innerHTML = '<span class="loading"></span>Testing...';
            btn.disabled = true;

            try {{
                const res = await fetch('/api/setup/validate/home-assistant', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        url: document.getElementById('ha-url').value,
                        token: document.getElementById('ha-token').value
                    }})
                }});

                const data = await res.json();

                if (data.valid) {{
                    status.className = 'status-message success';
                    status.textContent = `Connected! Home Assistant version: ${{data.version}}`;
                    validatedHA = true;
                    document.getElementById('step4-next').disabled = false;
                }} else {{
                    status.className = 'status-message error';
                    status.textContent = data.error || 'Connection failed';
                    validatedHA = false;
                }}
            }} catch (e) {{
                status.className = 'status-message error';
                status.textContent = 'Connection error. Please check your network.';
                validatedHA = false;
            }}

            btn.innerHTML = 'Test Connection';
            btn.disabled = false;
        }}

        function updateSummary() {{
            const providerNames = {{
                'openai': 'OpenAI (GPT)',
                'anthropic': 'Anthropic (Claude)',
                'ollama': 'Ollama (Local)',
                'google': 'Google (Gemini)'
            }};

            document.getElementById('summary-provider').textContent = providerNames[selectedProvider] || selectedProvider;
            document.getElementById('summary-model').textContent = document.getElementById('model-select').value || 'Not selected';
            const guardrails = document.getElementById('guardrails-threshold').value;
            const guardrailsText = guardrails === '0' ? 'disabled' : 'threshold ' + guardrails;
            document.getElementById('summary-limits').textContent =
                'Max ' + document.getElementById('max-tokens').value + ' tokens, ' + document.getElementById('requests-per-minute').value + ' req/min, safety ' + guardrailsText;
            document.getElementById('summary-ha').textContent = document.getElementById('ha-url').value || 'Not configured';
        }}

        function updateGuardrailsLabel(value) {{
            document.getElementById('guardrails-value').textContent = value;
            const info = document.getElementById('guardrails-info');
            const desc = document.getElementById('guardrails-desc');
            const hint = document.getElementById('guardrails-hint');

            if (value === '0') {{
                info.className = 'info-box danger';
                desc.innerHTML = '<strong>Disabled:</strong> All commands will be executed without safety checks. Only use this for testing or if you have other security measures in place.';
                hint.textContent = 'Safety checks completely disabled';
            }} else if (value < 30) {{
                info.className = 'info-box';
                desc.innerHTML = '<strong>Strict:</strong> Only very low-risk commands (score < ' + value + ') are allowed. May block legitimate automations - best for high-security environments.';
                hint.textContent = 'Very restrictive - many commands may be blocked';
            }} else if (value < 50) {{
                info.className = 'info-box';
                desc.innerHTML = '<strong>Cautious:</strong> Only low-risk commands (score < ' + value + ') are allowed. Safer for homes with children or shared access.';
                hint.textContent = 'Only clearly safe commands allowed';
            }} else if (value < 70) {{
                info.className = 'info-box warning';
                desc.innerHTML = '<strong>Balanced:</strong> Commands with risk score < ' + value + ' are allowed. Good default for most homes.';
                hint.textContent = 'Medium and high-risk commands blocked';
            }} else if (value < 90) {{
                info.className = 'info-box warning';
                desc.innerHTML = '<strong>Permissive:</strong> Most commands (score < ' + value + ') are allowed. Good for advanced users who understand their smart home setup.';
                hint.textContent = 'Only high-risk commands blocked';
            }} else {{
                info.className = 'info-box danger';
                desc.innerHTML = '<strong>Very Permissive:</strong> Almost all commands are allowed. Only the most dangerous commands (score >= ' + value + ') are blocked.';
                hint.textContent = 'Only extremely high-risk commands blocked';
            }}
        }}

        async function saveConfig() {{
            const btn = document.getElementById('save-btn');
            const status = document.getElementById('save-status');

            btn.innerHTML = '<span class="loading"></span>Saving...';
            btn.disabled = true;

            const config = {{
                provider: {{
                    provider: selectedProvider,
                    model: document.getElementById('model-select').value
                }},
                limits: {{
                    max_tokens_per_response: parseInt(document.getElementById('max-tokens').value),
                    requests_per_minute: parseInt(document.getElementById('requests-per-minute').value),
                    guardrails_threshold: parseInt(document.getElementById('guardrails-threshold').value),
                    history_backfill_days: parseInt(document.getElementById('history-backfill-days').value)
                }},
                home_assistant: {{
                    url: document.getElementById('ha-url').value,
                    token: document.getElementById('ha-token').value
                }},
                app_name: 'TaraHome AI Assistant'
            }};

            // Add provider-specific fields
            if (selectedProvider === 'ollama') {{
                config.provider.host = document.getElementById('ollama-host').value;
            }} else if (selectedProvider === 'openai_compatible') {{
                config.provider.host = document.getElementById('openai-compatible-host').value;
                const apiKey = document.getElementById('openai-compatible-key').value;
                if (apiKey) config.provider.api_key = apiKey;
            }} else {{
                config.provider.api_key = document.getElementById('api-key').value;
            }}

            try {{
                const res = await fetch('/api/setup/save', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(config)
                }});

                const data = await res.json();

                if (data.success) {{
                    status.className = 'status-message success';
                    status.textContent = 'Configuration saved! Redirecting...';
                    setTimeout(() => window.location.href = '/', 1500);
                }} else {{
                    status.className = 'status-message error';
                    status.textContent = data.detail || 'Failed to save configuration';
                    btn.innerHTML = 'Save & Continue';
                    btn.disabled = false;
                }}
            }} catch (e) {{
                status.className = 'status-message error';
                status.textContent = 'Error saving configuration';
                btn.innerHTML = 'Save & Continue';
                btn.disabled = false;
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

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {{
            const storedTheme = localStorage.getItem('theme');
            if (storedTheme === 'dark') {{
                setTheme(true);
            }} else {{
                setTheme(false);
            }}

            // Initialize guardrails UI with current value
            updateGuardrailsLabel('{prefill_guardrails}');

            if (selectedProvider) {{
                setupStep2();
                // If editing, enable next buttons
                if ({str(is_settings).lower()}) {{
                    document.getElementById('step2-next').disabled = false;
                    document.getElementById('step4-next').disabled = false;
                    document.getElementById('model-section').classList.remove('hidden');
                    // Pre-fill model
                    const modelSelect = document.getElementById('model-select');
                    const opt = document.createElement('option');
                    opt.value = '{prefill_model}';
                    opt.textContent = '{prefill_model}';
                    opt.selected = true;
                    modelSelect.appendChild(opt);
                }}
            }}
        }});
    </script>
</body>
</html>'''
