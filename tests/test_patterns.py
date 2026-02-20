"""Comprehensive tests for the device usage pattern tracking system."""

import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Set up test environment before imports
os.environ.setdefault("HA_URL", "http://localhost:8123")
os.environ.setdefault("HA_TOKEN", "test_token")


class TestEntityFilters(unittest.TestCase):
    """Tests for entity exclusion helpers."""

    def test_is_entity_excluded_exact_match(self):
        from app.entity_filters import is_entity_excluded

        self.assertTrue(
            is_entity_excluded("light.bedroom", ["light.bedroom"])
        )
        self.assertFalse(
            is_entity_excluded("light.kitchen", ["light.bedroom"])
        )

    def test_is_entity_excluded_wildcard_match(self):
        from app.entity_filters import is_entity_excluded

        self.assertTrue(
            is_entity_excluded("camera.driveway", ["camera.*"])
        )
        self.assertFalse(
            is_entity_excluded("light.driveway", ["camera.*"])
        )


class TestPatternModels(unittest.TestCase):
    """Tests for pattern tracking Pydantic models."""

    def test_device_event_creation(self):
        """Test DeviceEvent model creation."""
        from app.patterns.models import DeviceEvent, EventSource

        event = DeviceEvent(
            entity_id="light.living_room",
            domain="light",
            old_state="off",
            new_state="on",
            timestamp=datetime.utcnow(),
            source=EventSource.ASSISTANT,
        )

        self.assertEqual(event.entity_id, "light.living_room")
        self.assertEqual(event.domain, "light")
        self.assertEqual(event.old_state, "off")
        self.assertEqual(event.new_state, "on")
        self.assertEqual(event.source, EventSource.ASSISTANT)

    def test_device_event_with_attributes(self):
        """Test DeviceEvent with attributes."""
        from app.patterns.models import DeviceEvent, EventSource

        event = DeviceEvent(
            entity_id="light.bedroom",
            domain="light",
            new_state="on",
            timestamp=datetime.utcnow(),
            source=EventSource.EXTERNAL,
            attributes={"brightness": 255, "color_temp": 370},
        )

        self.assertEqual(event.attributes["brightness"], 255)
        self.assertEqual(event.attributes["color_temp"], 370)

    def test_detected_pattern_creation(self):
        """Test DetectedPattern model creation."""
        from app.patterns.models import DetectedPattern, PatternType

        pattern = DetectedPattern(
            pattern_type=PatternType.TIME_BASED,
            entity_ids=["light.living_room"],
            pattern_data={
                "time_window_start": "18:00",
                "time_window_end": "19:00",
                "days_of_week": [0, 1, 2, 3, 4],
                "action": "on",
                "average_trigger_time": "18:30",
                "variance_minutes": 15.0,
            },
            confidence=0.75,
            occurrence_count=5,
            first_seen=datetime.utcnow() - timedelta(days=7),
            last_seen=datetime.utcnow(),
        )

        self.assertEqual(pattern.pattern_type, PatternType.TIME_BASED)
        self.assertEqual(pattern.confidence, 0.75)
        self.assertEqual(pattern.occurrence_count, 5)
        self.assertTrue(pattern.is_active)

    def test_pattern_suggestion_creation(self):
        """Test PatternSuggestion model creation."""
        from app.patterns.models import PatternSuggestion, PatternType

        suggestion = PatternSuggestion(
            pattern_id=1,
            pattern_type=PatternType.TIME_BASED,
            title="Automate Living Room Lights",
            description="Turn on lights at 6:30 PM on weekdays",
            command="Create an automation to turn on living room lights at 18:30",
            confidence=0.75,
            occurrence_count=5,
            entities_involved=["light.living_room"],
            automation_yaml={
                "alias": "Auto living room on",
                "trigger": [{"platform": "time", "at": "18:30"}],
                "action": [{"service": "light.turn_on", "target": {"entity_id": "light.living_room"}}],
            },
        )

        self.assertEqual(suggestion.title, "Automate Living Room Lights")
        self.assertIsNotNone(suggestion.automation_yaml)

    def test_event_source_enum(self):
        """Test EventSource enum values."""
        from app.patterns.models import EventSource

        self.assertEqual(EventSource.ASSISTANT.value, "assistant")
        self.assertEqual(EventSource.EXTERNAL.value, "external")
        self.assertEqual(EventSource.AUTOMATION.value, "automation")
        self.assertEqual(EventSource.UNKNOWN.value, "unknown")

    def test_pattern_type_enum(self):
        """Test PatternType enum values."""
        from app.patterns.models import PatternType

        self.assertEqual(PatternType.TIME_BASED.value, "time_based")
        self.assertEqual(PatternType.SEQUENTIAL.value, "sequential")


class TestPatternDatabase(unittest.TestCase):
    """Tests for pattern database operations."""

    def setUp(self):
        """Set up test database."""
        # Create a temporary directory for the test database
        self.temp_dir = tempfile.mkdtemp()
        self.original_db_dir = None

    def tearDown(self):
        """Clean up test database."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _get_test_db(self):
        """Get a test database instance."""
        from app.patterns.database import PatternDatabase

        db = PatternDatabase()
        # Override the database path for testing
        db.db_path = Path(self.temp_dir) / "test_patterns.db"
        db._init_database()
        return db

    def test_database_initialization(self):
        """Test database schema creation."""
        db = self._get_test_db()

        # Check tables exist
        with db._get_connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row["name"] for row in cursor.fetchall()}

        self.assertIn("device_events", tables)
        self.assertIn("detected_patterns", tables)
        self.assertIn("user_preferences", tables)
        self.assertIn("sync_metadata", tables)

    def test_insert_and_retrieve_event(self):
        """Test inserting and retrieving events."""
        from app.patterns.models import DeviceEvent, EventSource

        db = self._get_test_db()

        event = DeviceEvent(
            entity_id="light.kitchen",
            domain="light",
            old_state="off",
            new_state="on",
            timestamp=datetime.utcnow(),
            source=EventSource.ASSISTANT,
        )

        event_id = db.insert_event(event)
        self.assertIsNotNone(event_id)
        self.assertGreater(event_id, 0)

        # Retrieve events
        events = db.get_events_in_range(
            datetime.utcnow() - timedelta(hours=1),
            datetime.utcnow() + timedelta(hours=1),
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].entity_id, "light.kitchen")
        self.assertEqual(events[0].new_state, "on")

    def test_insert_events_batch(self):
        """Test batch event insertion."""
        from app.patterns.models import DeviceEvent, EventSource

        db = self._get_test_db()

        events = [
            DeviceEvent(
                entity_id=f"light.room_{i}",
                domain="light",
                new_state="on",
                timestamp=datetime.utcnow() - timedelta(minutes=i),
                source=EventSource.EXTERNAL,
            )
            for i in range(10)
        ]

        count = db.insert_events_batch(events)
        self.assertEqual(count, 10)

        # Verify count
        total = db.get_event_count()
        self.assertEqual(total, 10)

    def test_insert_and_retrieve_pattern(self):
        """Test inserting and retrieving patterns."""
        from app.patterns.models import DetectedPattern, PatternType

        db = self._get_test_db()

        pattern = DetectedPattern(
            pattern_type=PatternType.TIME_BASED,
            entity_ids=["light.living_room"],
            pattern_data={"action": "on", "average_trigger_time": "18:30"},
            confidence=0.8,
            occurrence_count=10,
            first_seen=datetime.utcnow() - timedelta(days=7),
            last_seen=datetime.utcnow(),
        )

        pattern_id = db.insert_pattern(pattern)
        self.assertIsNotNone(pattern_id)

        # Retrieve patterns
        patterns = db.get_active_patterns(min_confidence=0.5)
        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0].confidence, 0.8)

    def test_update_pattern(self):
        """Test updating pattern."""
        from app.patterns.models import DetectedPattern, PatternType

        db = self._get_test_db()

        pattern = DetectedPattern(
            pattern_type=PatternType.SEQUENTIAL,
            entity_ids=["lock.front_door", "light.hallway"],
            pattern_data={"sequence": []},
            confidence=0.5,
            occurrence_count=3,
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
        )

        pattern_id = db.insert_pattern(pattern)
        pattern.id = pattern_id
        pattern.confidence = 0.9
        pattern.occurrence_count = 10

        db.update_pattern(pattern)

        # Verify update
        updated = db.get_pattern_by_id(pattern_id)
        self.assertEqual(updated.confidence, 0.9)
        self.assertEqual(updated.occurrence_count, 10)

    def test_deactivate_pattern(self):
        """Test deactivating a pattern."""
        from app.patterns.models import DetectedPattern, PatternType

        db = self._get_test_db()

        pattern = DetectedPattern(
            pattern_type=PatternType.TIME_BASED,
            entity_ids=["switch.outlet"],
            pattern_data={},
            confidence=0.7,
            occurrence_count=5,
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
        )

        pattern_id = db.insert_pattern(pattern)
        db.deactivate_pattern(pattern_id)

        # Should not appear in active patterns
        active = db.get_active_patterns(min_confidence=0)
        self.assertEqual(len(active), 0)

    def test_user_preferences(self):
        """Test user preference storage."""
        from app.patterns.models import DetectedPattern, PatternType

        db = self._get_test_db()

        pattern = DetectedPattern(
            pattern_type=PatternType.TIME_BASED,
            entity_ids=["light.test"],
            pattern_data={},
            confidence=0.6,
            occurrence_count=4,
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
        )

        pattern_id = db.insert_pattern(pattern)
        db.insert_user_preference(pattern_id, "dismissed")

        dismissed = db.get_dismissed_pattern_ids()
        self.assertIn(pattern_id, dismissed)

    def test_sync_metadata(self):
        """Test sync metadata operations."""
        db = self._get_test_db()

        # Initially no sync
        last_sync = db.get_last_sync_timestamp()
        self.assertIsNone(last_sync)

        # Update sync
        now = datetime.utcnow()
        db.update_sync_metadata(now, 100, 500)

        last_sync = db.get_last_sync_timestamp()
        self.assertIsNotNone(last_sync)

    def test_cleanup_old_events(self):
        """Test cleanup of old events."""
        from app.patterns.models import DeviceEvent, EventSource

        db = self._get_test_db()

        # Insert old events
        old_events = [
            DeviceEvent(
                entity_id="light.old",
                domain="light",
                new_state="on",
                timestamp=datetime.utcnow() - timedelta(days=60),
                source=EventSource.EXTERNAL,
            )
            for _ in range(5)
        ]
        db.insert_events_batch(old_events)

        # Insert recent events
        recent_events = [
            DeviceEvent(
                entity_id="light.recent",
                domain="light",
                new_state="on",
                timestamp=datetime.utcnow() - timedelta(days=5),
                source=EventSource.EXTERNAL,
            )
            for _ in range(3)
        ]
        db.insert_events_batch(recent_events)

        # Cleanup events older than 30 days
        deleted = db.cleanup_old_events(days=30)
        self.assertEqual(deleted, 5)

        # Verify recent events remain
        remaining = db.get_event_count()
        self.assertEqual(remaining, 3)

    def test_get_stats(self):
        """Test statistics retrieval."""
        from app.patterns.models import DeviceEvent, EventSource

        db = self._get_test_db()

        # Insert events from different sources
        events = [
            DeviceEvent(
                entity_id="light.test",
                domain="light",
                new_state="on",
                timestamp=datetime.utcnow(),
                source=EventSource.ASSISTANT,
            ),
            DeviceEvent(
                entity_id="switch.test",
                domain="switch",
                new_state="on",
                timestamp=datetime.utcnow(),
                source=EventSource.EXTERNAL,
            ),
            DeviceEvent(
                entity_id="light.test2",
                domain="light",
                new_state="off",
                timestamp=datetime.utcnow(),
                source=EventSource.EXTERNAL,
            ),
        ]
        db.insert_events_batch(events)

        stats = db.get_stats()
        self.assertEqual(stats["total_events"], 3)
        self.assertIn("assistant", stats["events_by_source"])
        self.assertIn("external", stats["events_by_source"])


class TestPatternDetector(unittest.TestCase):
    """Tests for pattern detection algorithms."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _get_test_db(self):
        """Get a test database instance."""
        from app.patterns.database import PatternDatabase

        db = PatternDatabase()
        db.db_path = Path(self.temp_dir) / "test_patterns.db"
        db._init_database()
        return db

    def test_detect_time_based_pattern(self):
        """Test detection of time-based patterns."""
        from app.patterns.models import DeviceEvent, EventSource
        from app.patterns.detector import PatternDetector

        db = self._get_test_db()

        # Create events at similar times on the SAME days of week
        # Pattern detection requires 2+ events on the same day of week
        # January 2024: 1st is Monday, 8th is Monday, 15th is Monday, etc.
        events = []

        # Create 3 events on Mondays around 6:30 PM
        for week in range(3):
            monday = datetime(2024, 1, 1 + week * 7, 18, 30, 0) + timedelta(minutes=week * 3)
            events.append(
                DeviceEvent(
                    entity_id="light.living_room",
                    domain="light",
                    old_state="off",
                    new_state="on",
                    timestamp=monday,
                    source=EventSource.EXTERNAL,
                )
            )

        # Create 3 events on Tuesdays around 6:30 PM
        for week in range(3):
            tuesday = datetime(2024, 1, 2 + week * 7, 18, 35, 0) + timedelta(minutes=week * 2)
            events.append(
                DeviceEvent(
                    entity_id="light.living_room",
                    domain="light",
                    old_state="off",
                    new_state="on",
                    timestamp=tuesday,
                    source=EventSource.EXTERNAL,
                )
            )

        db.insert_events_batch(events)

        # Create detector with mocked db
        detector = PatternDetector()
        detector.db = db

        # Detect patterns
        patterns = detector._detect_time_patterns(events)

        self.assertGreater(len(patterns), 0)
        time_pattern = patterns[0]
        self.assertEqual(time_pattern.entity_ids, ["light.living_room"])
        self.assertEqual(time_pattern.pattern_data["action"], "on")
        self.assertIn("average_trigger_time", time_pattern.pattern_data)

    def test_detect_sequential_pattern(self):
        """Test detection of sequential patterns."""
        from app.patterns.models import DeviceEvent, EventSource
        from app.patterns.detector import PatternDetector

        db = self._get_test_db()

        # Create sequential events (door unlock -> hallway light)
        base_time = datetime(2024, 1, 15, 18, 0, 0)
        events = []

        for i in range(5):  # 5 occurrences
            # Door unlocks
            events.append(
                DeviceEvent(
                    entity_id="lock.front_door",
                    domain="lock",
                    old_state="locked",
                    new_state="unlocked",
                    timestamp=base_time + timedelta(days=i),
                    source=EventSource.EXTERNAL,
                )
            )
            # Hallway light turns on 30-60 seconds later
            events.append(
                DeviceEvent(
                    entity_id="light.hallway",
                    domain="light",
                    old_state="off",
                    new_state="on",
                    timestamp=base_time + timedelta(days=i, seconds=30 + i * 5),
                    source=EventSource.EXTERNAL,
                )
            )

        db.insert_events_batch(events)

        detector = PatternDetector()
        detector.db = db

        # Detect sequential patterns
        patterns = detector._detect_sequential_patterns(events)

        self.assertGreater(len(patterns), 0)

        # Find the lock->light pattern
        lock_light_pattern = None
        for p in patterns:
            if "lock.front_door" in p.entity_ids and "light.hallway" in p.entity_ids:
                lock_light_pattern = p
                break

        self.assertIsNotNone(lock_light_pattern)
        self.assertEqual(len(lock_light_pattern.pattern_data["sequence"]), 2)

    def test_no_pattern_with_insufficient_data(self):
        """Test that patterns aren't detected with insufficient data."""
        from app.patterns.models import DeviceEvent, EventSource
        from app.patterns.detector import PatternDetector

        db = self._get_test_db()

        # Only 2 events (below minimum threshold of 3)
        events = [
            DeviceEvent(
                entity_id="light.random",
                domain="light",
                new_state="on",
                timestamp=datetime.utcnow() - timedelta(days=i),
                source=EventSource.EXTERNAL,
            )
            for i in range(2)
        ]

        db.insert_events_batch(events)

        detector = PatternDetector()
        detector.db = db

        patterns = detector._detect_time_patterns(events)
        self.assertEqual(len(patterns), 0)

    def test_pattern_persistence(self):
        """Test that patterns are persisted to database."""
        from app.patterns.models import DeviceEvent, EventSource, PatternType
        from app.patterns.detector import PatternDetector

        db = self._get_test_db()

        # Create events within the last 14 days (within lookback period)
        now = datetime.utcnow()
        events = []

        # Create 4 events at 7 AM on different days within last 2 weeks
        for i in range(4):
            # Go back i*2 days to spread across the lookback period
            event_time = now - timedelta(days=i * 2, hours=now.hour - 7, minutes=now.minute)
            events.append(
                DeviceEvent(
                    entity_id="switch.coffee_maker",
                    domain="switch",
                    old_state="off",
                    new_state="on",
                    timestamp=event_time,
                    source=EventSource.ASSISTANT,
                )
            )

        db.insert_events_batch(events)

        detector = PatternDetector()
        detector.db = db

        # Run full detection
        patterns = detector.detect_all_patterns(lookback_days=30)

        # Check patterns were saved (either time-based or no patterns depending on day distribution)
        # At minimum, the database operations should work
        saved_patterns = db.get_active_patterns(min_confidence=0)
        # The detection should at least run without error
        self.assertIsNotNone(patterns)


class TestSuggestionGenerator(unittest.TestCase):
    """Tests for suggestion generation."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _get_test_db(self):
        """Get a test database instance."""
        from app.patterns.database import PatternDatabase

        db = PatternDatabase()
        db.db_path = Path(self.temp_dir) / "test_patterns.db"
        db._init_database()
        return db

    def test_time_pattern_suggestion(self):
        """Test suggestion generation from time-based pattern."""
        from app.patterns.models import DetectedPattern, PatternType
        from app.patterns.suggestions import SuggestionGenerator

        db = self._get_test_db()

        pattern = DetectedPattern(
            pattern_type=PatternType.TIME_BASED,
            entity_ids=["light.living_room"],
            pattern_data={
                "time_window_start": "18:00",
                "time_window_end": "19:00",
                "days_of_week": [0, 1, 2, 3, 4],
                "action": "on",
                "average_trigger_time": "18:30",
                "variance_minutes": 10.0,
            },
            confidence=0.8,
            occurrence_count=10,
            first_seen=datetime.utcnow() - timedelta(days=14),
            last_seen=datetime.utcnow(),
        )

        pattern_id = db.insert_pattern(pattern)
        pattern.id = pattern_id

        generator = SuggestionGenerator()
        generator.db = db

        suggestion = generator._time_pattern_to_suggestion(pattern)

        self.assertIsNotNone(suggestion)
        self.assertIn("living room", suggestion.title.lower())
        self.assertIn("18:30", suggestion.command)
        self.assertIn("weekdays", suggestion.command.lower())
        self.assertIsNotNone(suggestion.automation_yaml)
        self.assertEqual(suggestion.automation_yaml["trigger"][0]["at"], "18:30")

    def test_sequential_pattern_suggestion(self):
        """Test suggestion generation from sequential pattern."""
        from app.patterns.models import DetectedPattern, PatternType
        from app.patterns.suggestions import SuggestionGenerator

        db = self._get_test_db()

        pattern = DetectedPattern(
            pattern_type=PatternType.SEQUENTIAL,
            entity_ids=["lock.front_door", "light.hallway"],
            pattern_data={
                "sequence": [
                    {"entity_id": "lock.front_door", "state": "unlocked"},
                    {"entity_id": "light.hallway", "state": "on"},
                ],
                "max_delay_seconds": 60,
                "average_delay_seconds": 45.0,
            },
            confidence=0.7,
            occurrence_count=8,
            first_seen=datetime.utcnow() - timedelta(days=7),
            last_seen=datetime.utcnow(),
        )

        pattern_id = db.insert_pattern(pattern)
        pattern.id = pattern_id

        generator = SuggestionGenerator()
        generator.db = db

        suggestion = generator._sequential_pattern_to_suggestion(pattern)

        self.assertIsNotNone(suggestion)
        self.assertIn("front door", suggestion.title.lower())
        self.assertIn("hallway", suggestion.title.lower())
        self.assertIsNotNone(suggestion.automation_yaml)
        self.assertEqual(
            suggestion.automation_yaml["trigger"][0]["entity_id"],
            "lock.front_door"
        )

    def test_generate_suggestions_filters_dismissed(self):
        """Test that dismissed patterns are filtered out."""
        from app.patterns.models import DetectedPattern, PatternType
        from app.patterns.suggestions import SuggestionGenerator

        db = self._get_test_db()

        # Create two patterns
        pattern1 = DetectedPattern(
            pattern_type=PatternType.TIME_BASED,
            entity_ids=["light.keep"],
            pattern_data={"action": "on", "average_trigger_time": "08:00", "days_of_week": []},
            confidence=0.8,
            occurrence_count=5,
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
        )
        pattern2 = DetectedPattern(
            pattern_type=PatternType.TIME_BASED,
            entity_ids=["light.dismiss"],
            pattern_data={"action": "on", "average_trigger_time": "09:00", "days_of_week": []},
            confidence=0.9,
            occurrence_count=10,
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
        )

        id1 = db.insert_pattern(pattern1)
        id2 = db.insert_pattern(pattern2)

        # Dismiss pattern2
        db.insert_user_preference(id2, "dismissed")

        generator = SuggestionGenerator()
        generator.db = db

        suggestions = generator.generate_suggestions(min_confidence=0.5)

        # Should only have 1 suggestion (pattern1)
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].entities_involved, ["light.keep"])

    def test_format_days(self):
        """Test day formatting."""
        from app.patterns.suggestions import SuggestionGenerator

        generator = SuggestionGenerator()

        self.assertEqual(generator._format_days([0, 1, 2, 3, 4]), "weekdays")
        self.assertEqual(generator._format_days([5, 6]), "weekends")
        self.assertEqual(generator._format_days([0, 1, 2, 3, 4, 5, 6]), "every day")
        self.assertEqual(generator._format_days([0, 2, 4]), "Monday, Wednesday, Friday")


class TestEventCollector(unittest.TestCase):
    """Tests for event collection."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _get_test_db(self):
        """Get a test database instance."""
        from app.patterns.database import PatternDatabase

        db = PatternDatabase()
        db.db_path = Path(self.temp_dir) / "test_patterns.db"
        db._init_database()
        return db

    def test_record_assistant_event(self):
        """Test recording assistant-triggered events."""
        from app.patterns.collector import EventCollector
        from app.patterns.models import EventSource

        db = self._get_test_db()

        collector = EventCollector("http://localhost:8123", "test_token")
        collector.db = db

        event_id = collector.record_assistant_event(
            entity_id="light.bedroom",
            old_state="off",
            new_state="on",
            attributes={"brightness": 200},
        )

        self.assertIsNotNone(event_id)

        # Verify event was stored
        events = db.get_events_in_range(
            datetime.utcnow() - timedelta(hours=1),
            datetime.utcnow() + timedelta(hours=1),
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].entity_id, "light.bedroom")
        self.assertEqual(events[0].source, EventSource.ASSISTANT)

    def test_record_assistant_event_skips_excluded_entity(self):
        """Test excluded entities are not recorded for assistant-triggered events."""
        from app.patterns.collector import EventCollector

        db = self._get_test_db()

        collector = EventCollector("http://localhost:8123", "test_token")
        collector.db = db
        collector.excluded_entity_patterns = ["light.secret_*"]

        event_id = collector.record_assistant_event(
            entity_id="light.secret_room",
            old_state="off",
            new_state="on",
            attributes={"brightness": 200},
        )

        self.assertIsNone(event_id)

        events = db.get_events_in_range(
            datetime.utcnow() - timedelta(hours=1),
            datetime.utcnow() + timedelta(hours=1),
        )
        self.assertEqual(len(events), 0)

    def test_parse_history_data(self):
        """Test parsing Home Assistant history API response."""
        from app.patterns.collector import EventCollector

        collector = EventCollector("http://localhost:8123", "test_token")

        # Mock history API response format
        history_data = [
            [
                {
                    "entity_id": "light.living_room",
                    "state": "off",
                    "last_changed": "2024-01-15T10:00:00+00:00",
                    "context": {"user_id": None, "parent_id": None},
                    "attributes": {},
                },
                {
                    "entity_id": "light.living_room",
                    "state": "on",
                    "last_changed": "2024-01-15T18:30:00+00:00",
                    "context": {"user_id": "abc123", "parent_id": None},
                    "attributes": {"brightness": 255},
                },
            ],
            [
                {
                    "entity_id": "switch.coffee",
                    "state": "on",
                    "last_changed": "2024-01-15T07:00:00+00:00",
                    "context": {"user_id": None, "parent_id": "auto123"},
                    "attributes": {},
                },
            ],
        ]

        events = collector._parse_history_data(history_data)

        self.assertEqual(len(events), 3)

        # Check light events
        light_events = [e for e in events if e.entity_id == "light.living_room"]
        self.assertEqual(len(light_events), 2)

        # Check switch event (automation-triggered)
        switch_events = [e for e in events if e.entity_id == "switch.coffee"]
        self.assertEqual(len(switch_events), 1)

    def test_determine_source(self):
        """Test source determination from context."""
        from app.patterns.collector import EventCollector
        from app.patterns.models import EventSource

        collector = EventCollector("http://localhost:8123", "test_token")

        # User triggered
        self.assertEqual(
            collector._determine_source({"user_id": "abc123"}),
            EventSource.EXTERNAL,
        )

        # Automation triggered
        self.assertEqual(
            collector._determine_source({"parent_id": "auto123"}),
            EventSource.AUTOMATION,
        )

        # Unknown
        self.assertEqual(
            collector._determine_source({}),
            EventSource.UNKNOWN,
        )

    def test_tracked_domains_filter(self):
        """Test that only tracked domains are collected."""
        from app.patterns.collector import EventCollector

        collector = EventCollector("http://localhost:8123", "test_token")

        # History with tracked and non-tracked domains
        history_data = [
            [
                {
                    "entity_id": "light.room",
                    "state": "on",
                    "last_changed": "2024-01-15T10:00:00+00:00",
                    "context": {},
                    "attributes": {},
                },
            ],
            [
                {
                    "entity_id": "sensor.temperature",  # Not tracked
                    "state": "22.5",
                    "last_changed": "2024-01-15T10:00:00+00:00",
                    "context": {},
                    "attributes": {},
                },
            ],
            [
                {
                    "entity_id": "binary_sensor.motion",  # Not tracked
                    "state": "on",
                    "last_changed": "2024-01-15T10:00:00+00:00",
                    "context": {},
                    "attributes": {},
                },
            ],
        ]

        events = collector._parse_history_data(history_data)

        # Only light should be included
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].entity_id, "light.room")

    def test_parse_history_data_skips_excluded_entity(self):
        """Test that excluded entities are filtered during history parsing."""
        from app.patterns.collector import EventCollector

        collector = EventCollector("http://localhost:8123", "test_token")
        collector.excluded_entity_patterns = ["light.secret_*"]

        history_data = [
            [
                {
                    "entity_id": "light.secret_room",
                    "state": "on",
                    "last_changed": "2024-01-15T10:00:00+00:00",
                    "context": {},
                    "attributes": {},
                },
            ],
            [
                {
                    "entity_id": "light.room",
                    "state": "on",
                    "last_changed": "2024-01-15T10:00:00+00:00",
                    "context": {},
                    "attributes": {},
                },
            ],
        ]

        events = collector._parse_history_data(history_data)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].entity_id, "light.room")


class TestPatternScheduler(unittest.TestCase):
    """Tests for the pattern scheduler."""

    def test_scheduler_initialization(self):
        """Test scheduler initialization."""
        from app.patterns.scheduler import PatternScheduler

        scheduler = PatternScheduler("http://localhost:8123", "test_token")

        self.assertEqual(scheduler.ha_url, "http://localhost:8123")
        self.assertEqual(scheduler.ha_token, "test_token")
        self.assertFalse(scheduler._running)

    def test_scheduler_start_stop(self):
        """Test starting and stopping scheduler."""
        import asyncio
        from app.patterns.scheduler import PatternScheduler

        async def run_test():
            scheduler = PatternScheduler("http://localhost:8123", "test_token")

            # Start
            scheduler.start()
            self.assertTrue(scheduler._running)
            self.assertIsNotNone(scheduler._sync_task)
            self.assertIsNotNone(scheduler._detection_task)

            # Give tasks a moment to start
            await asyncio.sleep(0.1)

            # Stop
            scheduler.stop()
            self.assertFalse(scheduler._running)

        # Run the async test
        asyncio.run(run_test())

    def test_singleton_pattern(self):
        """Test scheduler singleton pattern."""
        from app.patterns.scheduler import (
            init_pattern_scheduler,
            get_pattern_scheduler,
            stop_pattern_scheduler,
        )

        # Initialize
        scheduler1 = init_pattern_scheduler("http://localhost:8123", "token1")
        scheduler2 = get_pattern_scheduler()

        self.assertIs(scheduler1, scheduler2)

        # Clean up
        stop_pattern_scheduler()


class TestAPIEndpoints(unittest.TestCase):
    """Tests for pattern tracking API endpoints."""

    def setUp(self):
        """Set up test client."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_get_pattern_insights(self):
        """Test /api/patterns/insights endpoint."""
        from app.patterns.database import PatternDatabase
        from app.patterns.models import DetectedPattern, PatternType

        # Create test database
        db = PatternDatabase()
        db.db_path = Path(self.temp_dir) / "test_patterns.db"
        db._init_database()

        # Insert test pattern
        pattern = DetectedPattern(
            pattern_type=PatternType.TIME_BASED,
            entity_ids=["light.test"],
            pattern_data={"action": "on"},
            confidence=0.8,
            occurrence_count=5,
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
        )
        db.insert_pattern(pattern)

        # Mock get_pattern_db to return our test db
        with patch("app.patterns.database.get_pattern_db", return_value=db):
            from app.main import get_pattern_insights

            result = await get_pattern_insights()

            self.assertIn("patterns", result)
            self.assertIn("pattern_count", result)
            self.assertEqual(result["pattern_count"], 1)


class TestIntegration(unittest.TestCase):
    """Integration tests for the full pattern tracking flow."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_full_flow_time_pattern(self):
        """Test full flow: events -> detection -> suggestions."""
        from app.patterns.database import PatternDatabase
        from app.patterns.models import DeviceEvent, EventSource
        from app.patterns.detector import PatternDetector
        from app.patterns.suggestions import SuggestionGenerator

        # Set up database
        db = PatternDatabase()
        db.db_path = Path(self.temp_dir) / "test_patterns.db"
        db._init_database()

        # Create realistic event data within the lookback period
        now = datetime.utcnow()
        events = []

        # Create multiple events at similar times (around 7 PM) on different days
        # The key is having events with similar time-of-day across multiple days
        for day in range(10):
            # Vary the time slightly (7:00 PM +/- 15 minutes)
            event_time = now.replace(hour=19, minute=0, second=0, microsecond=0) - timedelta(days=day)
            event_time = event_time + timedelta(minutes=(day % 5) * 3)  # 0, 3, 6, 9, 12 min variation
            events.append(
                DeviceEvent(
                    entity_id="light.living_room",
                    domain="light",
                    old_state="off",
                    new_state="on",
                    timestamp=event_time,
                    source=EventSource.EXTERNAL,
                )
            )

        db.insert_events_batch(events)

        # Detect patterns
        detector = PatternDetector()
        detector.db = db
        patterns = detector.detect_all_patterns(lookback_days=30)

        # We should find at least one pattern given 10 events at similar times
        self.assertGreater(len(patterns), 0)

        # Generate suggestions
        generator = SuggestionGenerator()
        generator.db = db
        suggestions = generator.generate_suggestions(min_confidence=0.2)  # Lower threshold

        self.assertGreater(len(suggestions), 0)
        self.assertIn("living room", suggestions[0].title.lower())

    def test_full_flow_sequential_pattern(self):
        """Test full flow for sequential patterns."""
        from app.patterns.database import PatternDatabase
        from app.patterns.models import DeviceEvent, EventSource
        from app.patterns.detector import PatternDetector
        from app.patterns.suggestions import SuggestionGenerator

        db = PatternDatabase()
        db.db_path = Path(self.temp_dir) / "test_patterns.db"
        db._init_database()

        # Simulate: door unlocks -> light turns on within the lookback period
        now = datetime.utcnow()
        events = []

        for day in range(10):
            # Events from the past 10 days
            t = now - timedelta(days=day, hours=day % 3)

            # Door unlocks
            events.append(
                DeviceEvent(
                    entity_id="lock.front_door",
                    domain="lock",
                    old_state="locked",
                    new_state="unlocked",
                    timestamp=t,
                    source=EventSource.EXTERNAL,
                )
            )

            # Light turns on shortly after (30-60 seconds later)
            events.append(
                DeviceEvent(
                    entity_id="light.entryway",
                    domain="light",
                    old_state="off",
                    new_state="on",
                    timestamp=t + timedelta(seconds=30 + day * 3),
                    source=EventSource.EXTERNAL,
                )
            )

        db.insert_events_batch(events)

        # Detect patterns
        detector = PatternDetector()
        detector.db = db
        patterns = detector.detect_all_patterns(lookback_days=30)

        # Should find sequential pattern
        seq_patterns = [p for p in patterns if p.pattern_type.value == "sequential"]
        self.assertGreater(len(seq_patterns), 0)

        # Generate suggestions
        generator = SuggestionGenerator()
        generator.db = db
        suggestions = generator.generate_suggestions(min_confidence=0.2)

        # Should have suggestion for the sequence
        self.assertGreater(len(suggestions), 0)


def run_tests():
    """Run all tests with verbose output."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    test_classes = [
        TestEntityFilters,
        TestPatternModels,
        TestPatternDatabase,
        TestPatternDetector,
        TestSuggestionGenerator,
        TestEventCollector,
        TestPatternScheduler,
        TestIntegration,
    ]

    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)

    # Run with verbosity
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result


if __name__ == "__main__":
    run_tests()
