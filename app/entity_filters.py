"""Helpers for excluding Home Assistant entities from Tara processing."""

from fnmatch import fnmatchcase

from app.config import get_settings


def get_excluded_entity_patterns() -> list[str]:
    """Return normalized exclusion patterns from settings.

    Patterns support exact entity IDs and glob wildcards (for example `light.*`).
    """
    raw_value = get_settings().excluded_entities
    if not raw_value:
        return []

    separators_normalized = raw_value.replace(";", ",").replace("\n", ",")
    patterns = []
    for item in separators_normalized.split(","):
        pattern = item.strip().lower()
        if pattern:
            patterns.append(pattern)
    return patterns


def is_entity_excluded(entity_id: str, patterns: list[str]) -> bool:
    """Check whether an entity ID matches any configured exclusion pattern."""
    if not entity_id or not patterns:
        return False

    entity_id_lower = entity_id.lower()
    for pattern in patterns:
        if fnmatchcase(entity_id_lower, pattern):
            return True
    return False
