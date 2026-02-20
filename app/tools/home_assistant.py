"""Home Assistant API client and tools."""
import httpx
import time
from typing import Any
from dataclasses import dataclass
from app.config import get_settings
from app.entity_filters import get_excluded_entity_patterns, is_entity_excluded
from app.usage import get_usage_tracker


@dataclass
class HAState:
    """Represents a Home Assistant entity state."""
    entity_id: str
    state: str
    attributes: dict
    last_changed: str | None = None


class HomeAssistantClient:
    """Client for interacting with Home Assistant API."""

    def __init__(self):
        settings = get_settings()
        self.base_url = settings.ha_url.rstrip("/")
        self.token = settings.ha_token
        self.excluded_entity_patterns = get_excluded_entity_patterns()
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        """Make an HTTP request to Home Assistant."""
        start_time = time.time()
        tracker = get_usage_tracker()
        request_data = kwargs.get("json")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.request(
                    method,
                    f"{self.base_url}{endpoint}",
                    headers=self.headers,
                    timeout=30.0,
                    **kwargs
                )
                response.raise_for_status()
                response_data = response.json() if response.content else None
                duration_ms = int((time.time() - start_time) * 1000)

                # Log the request/response
                tracker.record_ha_log(
                    method=method,
                    endpoint=endpoint,
                    request_data=request_data,
                    response_data=self._truncate_response(response_data),
                    status_code=response.status_code,
                    duration_ms=duration_ms
                )

                return response_data
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                status_code = getattr(getattr(e, 'response', None), 'status_code', 0)
                tracker.record_ha_log(
                    method=method,
                    endpoint=endpoint,
                    request_data=request_data,
                    response_data=None,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    error=str(e)
                )
                raise

    def _truncate_response(self, data: Any, max_items: int = 10) -> Any:
        """Truncate large responses for logging."""
        if isinstance(data, list) and len(data) > max_items:
            return data[:max_items] + [f"... and {len(data) - max_items} more items"]
        return data
    
    async def get_states(self, include_excluded: bool = False) -> list[HAState]:
        """Get all entity states."""
        self.excluded_entity_patterns = get_excluded_entity_patterns()
        data = await self._request("GET", "/api/states")
        states = [
            HAState(
                entity_id=item["entity_id"],
                state=item["state"],
                attributes=item.get("attributes", {}),
                last_changed=item.get("last_changed")
            )
            for item in data
        ]
        if include_excluded:
            return states
        return [
            state
            for state in states
            if not is_entity_excluded(state.entity_id, self.excluded_entity_patterns)
        ]
    
    async def get_state(self, entity_id: str) -> HAState | None:
        """Get state for a specific entity."""
        self.excluded_entity_patterns = get_excluded_entity_patterns()
        if is_entity_excluded(entity_id, self.excluded_entity_patterns):
            return None

        try:
            data = await self._request("GET", f"/api/states/{entity_id}")
            return HAState(
                entity_id=data["entity_id"],
                state=data["state"],
                attributes=data.get("attributes", {}),
                last_changed=data.get("last_changed")
            )
        except httpx.HTTPStatusError:
            return None
    
    async def call_service(
        self, 
        domain: str, 
        service: str, 
        entity_id: str | None = None,
        **service_data
    ) -> dict:
        """Call a Home Assistant service."""
        self.excluded_entity_patterns = get_excluded_entity_patterns()
        if entity_id and is_entity_excluded(entity_id, self.excluded_entity_patterns):
            return {
                "success": False,
                "error": f"Entity {entity_id} is excluded from Tara processing"
            }

        data = {**service_data}
        if entity_id:
            data["entity_id"] = entity_id
        
        result = await self._request(
            "POST",
            f"/api/services/{domain}/{service}",
            json=data
        )
        return {"success": True, "result": result}
    
    async def create_automation(
        self,
        automation_id: str,
        alias: str,
        trigger: list[dict],
        action: list[dict],
        condition: list[dict] | None = None,
        mode: str = "single"
    ) -> dict:
        """Create a new automation."""
        data = {
            "alias": alias,
            "trigger": trigger,
            "action": action,
            "mode": mode,
        }
        if condition:
            data["condition"] = condition
        
        await self._request(
            "POST",
            f"/api/config/automation/config/{automation_id}",
            json=data
        )
        return {"success": True, "automation_id": automation_id}
    
    async def get_automations(self) -> list[HAState]:
        """Get all automations."""
        states = await self.get_states()
        return [s for s in states if s.entity_id.startswith("automation.")]


# Tool definitions for the AI agent
class HomeAssistantTools:
    """Tools that the AI agent can use."""
    
    def __init__(self):
        self.client = HomeAssistantClient()
    
    def get_tool_definitions(self) -> list[dict]:
        """Get tool definitions in OpenAI function format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_entity_state",
                    "description": "Get the current state of a Home Assistant entity. Use this BEFORE executing commands to check device availability and AFTER to verify commands worked.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "entity_id": {
                                "type": "string",
                                "description": "The entity ID (e.g., 'media_player.tv', 'light.living_room')"
                            }
                        },
                        "required": ["entity_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "call_service",
                    "description": "Call a Home Assistant service to control devices (turn on/off, play media, etc.)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "domain": {
                                "type": "string",
                                "description": "Service domain (e.g., 'light', 'media_player', 'switch', 'automation')"
                            },
                            "service": {
                                "type": "string",
                                "description": "Service name (e.g., 'turn_on', 'turn_off', 'play_media', 'toggle')"
                            },
                            "entity_id": {
                                "type": "string",
                                "description": "Target entity ID"
                            },
                            "service_data": {
                                "type": "object",
                                "description": "Additional service data (e.g., brightness, media_content_id)",
                                "default": {}
                            }
                        },
                        "required": ["domain", "service", "entity_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "list_automations",
                    "description": "List all automations in Home Assistant with their current state (enabled/disabled)",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "create_automation",
                    "description": "Create a new automation in Home Assistant",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "automation_id": {
                                "type": "string",
                                "description": "Unique ID for the automation (lowercase, underscores, no spaces)"
                            },
                            "alias": {
                                "type": "string",
                                "description": "Human-readable name for the automation"
                            },
                            "trigger_type": {
                                "type": "string",
                                "enum": ["time", "state", "event"],
                                "description": "Type of trigger"
                            },
                            "trigger_value": {
                                "type": "string",
                                "description": "Trigger value (e.g., '22:00:00' for time, entity_id for state)"
                            },
                            "action_domain": {
                                "type": "string",
                                "description": "Action service domain"
                            },
                            "action_service": {
                                "type": "string",
                                "description": "Action service name"
                            },
                            "action_entity_id": {
                                "type": "string",
                                "description": "Action target entity"
                            },
                            "action_data": {
                                "type": "object",
                                "description": "Additional action data",
                                "default": {}
                            }
                        },
                        "required": ["automation_id", "alias", "trigger_type", "trigger_value", 
                                   "action_domain", "action_service", "action_entity_id"]
                    }
                }
            },
            {
                "type": "function", 
                "function": {
                    "name": "list_entities",
                    "description": "List all entities of a specific domain (e.g., all lights, all media players)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "domain": {
                                "type": "string",
                                "description": "Entity domain to list (e.g., 'light', 'media_player', 'switch')"
                            }
                        },
                        "required": ["domain"]
                    }
                }
            }
        ]
    
    async def execute_tool(self, tool_name: str, arguments: dict) -> str:
        """Execute a tool and return the result as a string."""
        try:
            if tool_name == "get_entity_state":
                state = await self.client.get_state(arguments["entity_id"])
                if state:
                    return f"Entity: {state.entity_id}\nState: {state.state}\nAttributes: {state.attributes}"
                return f"Entity {arguments['entity_id']} not found"
            
            elif tool_name == "call_service":
                entity_id = arguments.get("entity_id")
                service_data = arguments.get("service_data", {})
                excluded_patterns = get_excluded_entity_patterns()
                if entity_id and is_entity_excluded(entity_id, excluded_patterns):
                    return f"Entity {entity_id} is excluded from Tara processing"

                # Get current state before the call for pattern tracking
                old_state = None
                if entity_id:
                    try:
                        current = await self.client.get_state(entity_id)
                        old_state = current.state if current else None
                    except Exception:
                        pass

                result = await self.client.call_service(
                    domain=arguments["domain"],
                    service=arguments["service"],
                    entity_id=entity_id,
                    **service_data
                )
                if not result.get("success", False):
                    return result.get("error", "Service call blocked")

                # Record event for pattern tracking
                if entity_id:
                    try:
                        from app.patterns.collector import EventCollector
                        from app.config import get_settings

                        settings = get_settings()
                        collector = EventCollector(settings.ha_url, settings.ha_token)

                        # Determine new state based on service
                        service = arguments["service"]
                        if "turn_on" in service:
                            new_state = "on"
                        elif "turn_off" in service:
                            new_state = "off"
                        elif service in ("lock",):
                            new_state = "locked"
                        elif service in ("unlock",):
                            new_state = "unlocked"
                        elif service in ("open_cover",):
                            new_state = "open"
                        elif service in ("close_cover",):
                            new_state = "closed"
                        else:
                            new_state = service

                        collector.record_assistant_event(
                            entity_id=entity_id,
                            old_state=old_state,
                            new_state=new_state,
                            attributes=service_data,
                        )
                    except Exception:
                        # Don't fail the command if pattern tracking fails
                        pass

                return f"Service {arguments['domain']}.{arguments['service']} called successfully"
            
            elif tool_name == "list_automations":
                automations = await self.client.get_automations()
                if not automations:
                    return "No automations found"
                lines = ["Current automations:"]
                for auto in automations:
                    name = auto.attributes.get("friendly_name", auto.entity_id)
                    status = "enabled" if auto.state == "on" else "disabled"
                    lines.append(f"- {name} ({status})")
                return "\n".join(lines)
            
            elif tool_name == "create_automation":
                # Build trigger
                trigger = []
                if arguments["trigger_type"] == "time":
                    trigger = [{"platform": "time", "at": arguments["trigger_value"]}]
                elif arguments["trigger_type"] == "state":
                    trigger = [{"platform": "state", "entity_id": arguments["trigger_value"]}]
                
                # Build action
                action_data = arguments.get("action_data", {})
                action = [{
                    "service": f"{arguments['action_domain']}.{arguments['action_service']}",
                    "target": {"entity_id": arguments["action_entity_id"]},
                    "data": action_data
                }]
                
                result = await self.client.create_automation(
                    automation_id=arguments["automation_id"],
                    alias=arguments["alias"],
                    trigger=trigger,
                    action=action
                )
                return f"Automation '{arguments['alias']}' created successfully"
            
            elif tool_name == "list_entities":
                states = await self.client.get_states()
                domain = arguments["domain"]
                entities = [s for s in states if s.entity_id.startswith(f"{domain}.")]
                if not entities:
                    return f"No {domain} entities found"
                lines = [f"{domain.title()} entities:"]
                for e in entities:
                    name = e.attributes.get("friendly_name", e.entity_id)
                    lines.append(f"- {e.entity_id}: {e.state} ({name})")
                return "\n".join(lines)
            
            else:
                return f"Unknown tool: {tool_name}"
                
        except Exception as e:
            return f"Error executing {tool_name}: {str(e)}"
