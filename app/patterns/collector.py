"""Event collection from Home Assistant History API and assistant commands."""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import httpx

from app.entity_filters import get_excluded_entity_patterns, is_entity_excluded
from app.patterns.database import get_pattern_db
from app.patterns.models import DeviceEvent, EventSource

logger = logging.getLogger(__name__)


class EventCollector:
    """Collects device events from multiple sources."""

    # Domains we track for pattern detection
    TRACKED_DOMAINS = {
        "light",
        "switch",
        "fan",
        "cover",
        "lock",
        "climate",
        "media_player",
        "automation",
        "scene",
        "script",
        "input_boolean",
        "vacuum",
        "humidifier",
    }

    def __init__(self, ha_url: str, ha_token: str):
        self.ha_url = ha_url.rstrip("/")
        self.ha_token = ha_token
        self.db = get_pattern_db()
        self.excluded_entity_patterns = get_excluded_entity_patterns()

    def record_assistant_event(
        self,
        entity_id: str,
        old_state: Optional[str],
        new_state: str,
        attributes: Optional[dict] = None,
    ) -> Optional[int]:
        """Record an event triggered by the assistant. Returns event ID."""
        if is_entity_excluded(entity_id, self.excluded_entity_patterns):
            logger.debug(f"Skipping excluded assistant event: {entity_id}")
            return None

        domain = entity_id.split(".")[0] if "." in entity_id else "unknown"

        event = DeviceEvent(
            entity_id=entity_id,
            domain=domain,
            old_state=old_state,
            new_state=new_state,
            timestamp=datetime.utcnow(),
            source=EventSource.ASSISTANT,
            attributes=attributes or {},
        )

        event_id = self.db.insert_event(event)
        logger.debug(f"Recorded assistant event: {entity_id} -> {new_state}")
        return event_id

    async def _get_tracked_entity_ids(self, client: httpx.AsyncClient) -> list[str]:
        """Fetch all entity IDs that match our tracked domains."""
        try:
            response = await client.get(
                f"{self.ha_url}/api/states",
                headers={
                    "Authorization": f"Bearer {self.ha_token}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            states = response.json()

            # Filter to tracked domains
            entity_ids = []
            for state in states:
                entity_id = state.get("entity_id", "")
                domain = entity_id.split(".")[0] if "." in entity_id else ""
                if (
                    domain in self.TRACKED_DOMAINS
                    and not is_entity_excluded(entity_id, self.excluded_entity_patterns)
                ):
                    entity_ids.append(entity_id)

            return entity_ids
        except Exception as e:
            logger.warning(f"Failed to fetch entity IDs: {e}")
            return []

    async def sync_from_history_api(
        self,
        hours_back: int = 24,
        entity_ids: Optional[list[str]] = None,
    ) -> tuple[int, Optional[str]]:
        """
        Fetch state changes from Home Assistant History API.

        Returns: (count_synced, error_message or None)
        """
        start_time = time.time()
        self.excluded_entity_patterns = get_excluded_entity_patterns()

        # Determine start timestamp - use last sync or fall back to hours_back
        last_sync = self.db.get_last_sync_timestamp()
        if last_sync:
            # Add small overlap to avoid missing events
            start_ts = last_sync - timedelta(minutes=5)
        else:
            # First sync: fetch 7 days of history for better pattern detection
            # Pattern detection needs multiple occurrences across different days
            start_ts = datetime.utcnow() - timedelta(days=7)
            logger.info("First sync: fetching 7 days of history for pattern detection")

        end_ts = datetime.utcnow()

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # If no entity_ids provided, fetch tracked entities from HA
                if not entity_ids:
                    entity_ids = await self._get_tracked_entity_ids(client)
                    if not entity_ids:
                        logger.info("No tracked entities found in Home Assistant")
                        duration_ms = int((time.time() - start_time) * 1000)
                        self.db.update_sync_metadata(end_ts, 0, duration_ms)
                        return 0, None

                # Home Assistant History API endpoint
                # https://developers.home-assistant.io/docs/api/rest/#get-apihistoryperiodtimestamp
                url = f"{self.ha_url}/api/history/period/{start_ts.isoformat()}"
                params = {
                    "end_time": end_ts.isoformat(),
                    "minimal_response": "true",
                    "significant_changes_only": "true",
                    "filter_entity_id": ",".join(entity_ids),
                }

                response = await client.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.ha_token}",
                        "Content-Type": "application/json",
                    },
                    params=params,
                )
                response.raise_for_status()
                history_data = response.json()

            # Parse and filter events
            events = self._parse_history_data(history_data)

            # Deduplicate against existing events
            events = self._deduplicate_events(events)

            if events:
                self.db.insert_events_batch(events)

            duration_ms = int((time.time() - start_time) * 1000)
            self.db.update_sync_metadata(end_ts, len(events), duration_ms)

            logger.info(f"Synced {len(events)} events in {duration_ms}ms")
            return len(events), None

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            logger.error(f"History API error: {error_msg}")
            duration_ms = int((time.time() - start_time) * 1000)
            self.db.update_sync_metadata(datetime.utcnow(), 0, duration_ms, error_msg)
            return 0, error_msg

        except Exception as e:
            error_msg = str(e)
            logger.exception(f"Sync error: {error_msg}")
            duration_ms = int((time.time() - start_time) * 1000)
            self.db.update_sync_metadata(datetime.utcnow(), 0, duration_ms, error_msg)
            return 0, error_msg

    def _parse_history_data(self, history_data: list) -> list[DeviceEvent]:
        """Parse Home Assistant history API response into DeviceEvents."""
        events = []

        # History API returns list of entity histories
        # Each element is a list of states for one entity
        for entity_history in history_data:
            if not entity_history:
                continue

            # Get entity_id from first state
            first_state = entity_history[0]
            entity_id = first_state.get("entity_id", "")
            domain = entity_id.split(".")[0] if "." in entity_id else "unknown"

            # Skip domains we don't track
            if domain not in self.TRACKED_DOMAINS:
                continue
            if is_entity_excluded(entity_id, self.excluded_entity_patterns):
                continue

            # Process state changes
            prev_state = None
            for state_obj in entity_history:
                current_state = state_obj.get("state", "")

                # Skip unavailable/unknown states
                if current_state in ("unavailable", "unknown", ""):
                    continue

                timestamp_str = state_obj.get("last_changed", "")

                # Skip if state didn't actually change
                if current_state == prev_state:
                    continue

                # Parse timestamp
                try:
                    # Handle various timestamp formats from HA
                    timestamp_str = timestamp_str.replace("Z", "+00:00")
                    if "." in timestamp_str and "+" in timestamp_str:
                        # Truncate microseconds if needed
                        base, tz = timestamp_str.rsplit("+", 1)
                        if "." in base:
                            base = base[:26]  # Keep up to 6 decimal places
                        timestamp_str = f"{base}+{tz}"
                    timestamp = datetime.fromisoformat(timestamp_str)
                    # Convert to UTC naive datetime for consistency
                    if timestamp.tzinfo is not None:
                        timestamp = timestamp.replace(tzinfo=None)
                except (ValueError, AttributeError):
                    continue

                # Determine source from context
                context = state_obj.get("context", {})
                source = self._determine_source(context)

                event = DeviceEvent(
                    entity_id=entity_id,
                    domain=domain,
                    old_state=prev_state,
                    new_state=current_state,
                    timestamp=timestamp,
                    source=source,
                    context_user_id=context.get("user_id"),
                    context_parent_id=context.get("parent_id"),
                    attributes=state_obj.get("attributes", {}),
                )
                events.append(event)
                prev_state = current_state

        return events

    def _determine_source(self, context: dict) -> EventSource:
        """Determine event source from HA context."""
        if not context:
            return EventSource.UNKNOWN

        # If there's a user_id, it was triggered by a user/frontend
        if context.get("user_id"):
            return EventSource.EXTERNAL

        # If there's a parent_id, it was triggered by an automation
        if context.get("parent_id"):
            return EventSource.AUTOMATION

        return EventSource.UNKNOWN

    def _deduplicate_events(self, events: list[DeviceEvent]) -> list[DeviceEvent]:
        """Remove events that already exist in the database."""
        if not events:
            return []

        # Get existing events in the time range of new events
        min_ts = min(e.timestamp for e in events)
        max_ts = max(e.timestamp for e in events)

        existing = self.db.get_events_in_range(
            min_ts - timedelta(minutes=1),
            max_ts + timedelta(minutes=1),
        )

        # Create set of (entity_id, timestamp, new_state) for quick lookup
        existing_keys = {
            (e.entity_id, e.timestamp.isoformat()[:19], e.new_state)
            for e in existing
        }

        # Filter out duplicates
        unique_events = [
            e
            for e in events
            if (e.entity_id, e.timestamp.isoformat()[:19], e.new_state)
            not in existing_keys
        ]

        if len(unique_events) < len(events):
            logger.debug(
                f"Deduplicated {len(events) - len(unique_events)} events"
            )

        return unique_events


def get_event_collector(ha_url: str, ha_token: str) -> EventCollector:
    """Create an EventCollector instance."""
    return EventCollector(ha_url, ha_token)
