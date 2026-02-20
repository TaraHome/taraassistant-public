"""Entity index cache for Home Assistant devices."""
import asyncio
import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List
import httpx

from app.setup.encryption import EncryptionManager
from app.entity_filters import get_excluded_entity_patterns, is_entity_excluded


@dataclass
class EntityInfo:
    """Compact entity information."""
    entity_id: str
    domain: str
    friendly_name: str
    device_class: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EntityIndex:
    """Cached entity index with metadata."""
    entities: List[EntityInfo]
    last_refreshed: str
    ha_url: str
    entity_count: int

    def to_dict(self) -> dict:
        return {
            "entities": [e.to_dict() for e in self.entities],
            "last_refreshed": self.last_refreshed,
            "ha_url": self.ha_url,
            "entity_count": self.entity_count
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EntityIndex":
        entities = [EntityInfo(**e) for e in data.get("entities", [])]
        return cls(
            entities=entities,
            last_refreshed=data.get("last_refreshed", ""),
            ha_url=data.get("ha_url", ""),
            entity_count=data.get("entity_count", len(entities))
        )


class EntityCache:
    """Encrypted cache for Home Assistant entity index."""

    CACHE_DIR = Path("data")
    CACHE_FILE = "entities.enc"
    FETCH_TIMEOUT = 10.0  # seconds

    def __init__(self, passphrase: Optional[str] = None):
        self.encryption = EncryptionManager(passphrase)
        self.cache_path = self.CACHE_DIR / self.CACHE_FILE
        self._index: Optional[EntityIndex] = None
        self._excluded_entity_patterns = get_excluded_entity_patterns()

    def exists(self) -> bool:
        """Check if entity cache exists."""
        return self.cache_path.exists()

    def save(self, index: EntityIndex) -> None:
        """Save entity index encrypted to disk."""
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)

        data = {
            "index": index.to_dict(),
            "version": "1.0"
        }

        encrypted = self.encryption.encrypt(json.dumps(data))
        self.cache_path.write_bytes(encrypted)

        # Set restrictive permissions
        try:
            os.chmod(self.cache_path, 0o600)
        except OSError:
            pass  # Windows doesn't support chmod

        self._index = index

    def load(self) -> Optional[EntityIndex]:
        """Load entity index from cache."""
        if self._index:
            return self._index

        if not self.exists():
            return None

        try:
            encrypted = self.cache_path.read_bytes()
            decrypted = self.encryption.decrypt(encrypted)
            data = json.loads(decrypted)
            self._index = EntityIndex.from_dict(data["index"])
            return self._index
        except Exception:
            return None

    def clear_memory_cache(self) -> None:
        """Clear in-memory cache to force reload from disk."""
        self._index = None

    def delete(self) -> bool:
        """Delete entity cache file."""
        if self.exists():
            self.cache_path.unlink()
            self._index = None
            return True
        return False

    async def fetch_and_cache(
        self,
        ha_url: str,
        ha_token: str,
        background: bool = False
    ) -> tuple[bool, Optional[str]]:
        """
        Fetch entities from Home Assistant and cache them.

        Args:
            ha_url: Home Assistant base URL
            ha_token: Long-lived access token
            background: If True, don't raise on failure

        Returns:
            Tuple of (success, error_message)
        """
        ha_url = ha_url.rstrip("/")
        self._excluded_entity_patterns = get_excluded_entity_patterns()

        try:
            async with httpx.AsyncClient(timeout=self.FETCH_TIMEOUT) as client:
                response = await client.get(
                    f"{ha_url}/api/states",
                    headers={
                        "Authorization": f"Bearer {ha_token}",
                        "Content-Type": "application/json"
                    }
                )
                response.raise_for_status()
                states = response.json()

            # Build compact entity index
            entities = []
            for state in states:
                entity_id = state.get("entity_id", "")
                if not entity_id:
                    continue
                if is_entity_excluded(entity_id, self._excluded_entity_patterns):
                    continue

                domain = entity_id.split(".")[0] if "." in entity_id else "unknown"
                attributes = state.get("attributes", {})

                entities.append(EntityInfo(
                    entity_id=entity_id,
                    domain=domain,
                    friendly_name=attributes.get("friendly_name", entity_id),
                    device_class=attributes.get("device_class")
                ))

            # Create index
            index = EntityIndex(
                entities=entities,
                last_refreshed=datetime.utcnow().isoformat(),
                ha_url=ha_url,
                entity_count=len(entities)
            )

            # Save to encrypted cache
            self.save(index)

            return True, None

        except httpx.TimeoutException:
            error = "Entity fetch timed out after 10 seconds"
            if not background:
                return False, error
            return False, error

        except Exception as e:
            error = f"Failed to fetch entities: {str(e)}"
            if not background:
                return False, error
            return False, error

    def get_entities_by_domain(self, domain: str) -> List[EntityInfo]:
        """Get all entities for a specific domain."""
        index = self.load()
        if not index:
            return []
        return [e for e in index.entities if e.domain == domain]

    def search_entities(self, query: str) -> List[EntityInfo]:
        """Search entities by name or ID."""
        index = self.load()
        if not index:
            return []

        query_lower = query.lower()
        return [
            e for e in index.entities
            if query_lower in e.entity_id.lower()
            or query_lower in e.friendly_name.lower()
        ]

    def get_formatted_device_list(self, domains: Optional[List[str]] = None) -> str:
        """
        Get a formatted device list for the AI system prompt.

        Args:
            domains: List of domains to include. If None, uses sensible defaults.

        Returns:
            Formatted string of devices grouped by domain.
        """
        if domains is None:
            domains = [
                "media_player", "light", "switch", "fan", "climate",
                "cover", "lock", "automation", "scene", "script",
                "camera", "vacuum", "sensor", "binary_sensor"
            ]

        index = self.load()
        if not index:
            return "No entity cache available. Use list_entities tool to discover devices."

        # Group by domain
        by_domain = {}
        for entity in index.entities:
            if entity.domain in domains:
                if entity.domain not in by_domain:
                    by_domain[entity.domain] = []
                by_domain[entity.domain].append(entity)

        # Format output
        lines = []
        for domain in sorted(by_domain.keys()):
            entities = by_domain[domain]
            lines.append(f"**{domain}:** ({len(entities)} entities)")

            # Show up to 15 per domain, prioritize by device_class
            shown = sorted(entities, key=lambda e: (e.device_class is None, e.friendly_name))[:15]
            for e in shown:
                dc = f" [{e.device_class}]" if e.device_class else ""
                lines.append(f"  - {e.friendly_name}: `{e.entity_id}`{dc}")

            if len(entities) > 15:
                lines.append(f"  ... and {len(entities) - 15} more")

        if not lines:
            return "No relevant devices found in cache."

        # Add refresh timestamp
        lines.append(f"\n_Entity cache last updated: {index.last_refreshed}_")

        return "\n".join(lines)


async def refresh_entity_cache(ha_url: str, ha_token: str) -> tuple[bool, Optional[str]]:
    """
    Helper function to refresh the entity cache.

    Args:
        ha_url: Home Assistant base URL
        ha_token: Long-lived access token

    Returns:
        Tuple of (success, error_message)
    """
    cache = EntityCache()
    return await cache.fetch_and_cache(ha_url, ha_token)


# Global singleton instance
_entity_cache_instance: Optional[EntityCache] = None


def get_entity_cache() -> EntityCache:
    """Get the global entity cache instance."""
    global _entity_cache_instance
    if _entity_cache_instance is None:
        _entity_cache_instance = EntityCache()
    return _entity_cache_instance
