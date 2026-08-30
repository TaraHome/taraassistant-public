"""Background task scheduling for pattern detection and sync."""

import asyncio
import logging
from typing import Optional

from app.patterns.collector import EventCollector
from app.patterns.database import get_pattern_db
from app.patterns.detector import get_pattern_detector

logger = logging.getLogger(__name__)


class PatternScheduler:
    """Manages background tasks for pattern tracking."""

    # Sync from HA History API every hour
    SYNC_INTERVAL_SECONDS = 60 * 60  # 1 hour

    # Run pattern detection every 6 hours
    DETECTION_INTERVAL_SECONDS = 60 * 60 * 6  # 6 hours

    # Clean up old events every 24 hours
    CLEANUP_INTERVAL_SECONDS = 60 * 60 * 24  # 24 hours

    # Initial delay before first detection (let some data accumulate)
    INITIAL_DETECTION_DELAY = 60  # 1 minute

    def __init__(self, ha_url: str, ha_token: str):
        self.ha_url = ha_url
        self.ha_token = ha_token
        self._sync_task: Optional[asyncio.Task] = None
        self._detection_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

    def start(self) -> None:
        """Start background tasks."""
        if self._running:
            logger.warning("Pattern scheduler already running")
            return

        self._running = True
        self._sync_task = asyncio.create_task(self._sync_loop())
        self._detection_task = asyncio.create_task(self._detection_loop())
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Pattern scheduler started")

    def stop(self) -> None:
        """Stop background tasks."""
        self._running = False

        for task in [self._sync_task, self._detection_task, self._cleanup_task]:
            if task:
                task.cancel()

        self._sync_task = None
        self._detection_task = None
        self._cleanup_task = None
        logger.info("Pattern scheduler stopped")

    async def _sync_loop(self) -> None:
        """Periodically sync events from Home Assistant."""
        # Initial sync immediately
        await self._run_sync()

        while self._running:
            try:
                await asyncio.sleep(self.SYNC_INTERVAL_SECONDS)
                if not self._running:
                    break
                await self._run_sync()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Sync loop error: {e}")
                # Wait before retrying
                await asyncio.sleep(60)

    async def _detection_loop(self) -> None:
        """Periodically run pattern detection."""
        # Initial delay to let some data accumulate
        await asyncio.sleep(self.INITIAL_DETECTION_DELAY)

        while self._running:
            try:
                await self._run_detection()
                await asyncio.sleep(self.DETECTION_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Detection loop error: {e}")
                await asyncio.sleep(60)

    async def _cleanup_loop(self) -> None:
        """Periodically clean up old events."""
        # Wait a bit before first cleanup
        await asyncio.sleep(self.CLEANUP_INTERVAL_SECONDS / 2)

        while self._running:
            try:
                await self._run_cleanup()
                await asyncio.sleep(self.CLEANUP_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Cleanup loop error: {e}")
                await asyncio.sleep(60)

    async def _run_sync(self) -> tuple[int, Optional[str]]:
        """Execute a sync from Home Assistant history."""
        try:
            collector = EventCollector(self.ha_url, self.ha_token)
            count, error = await collector.sync_from_history_api()

            if error:
                logger.warning(f"History sync error: {error}")
            else:
                logger.info(f"Synced {count} events from Home Assistant")

            return count, error
        except Exception as e:
            logger.exception(f"Sync failed: {e}")
            return 0, str(e)

    async def _run_detection(self) -> int:
        """Execute pattern detection."""
        try:
            detector = get_pattern_detector()
            patterns = detector.detect_all_patterns()
            logger.info(f"Detected {len(patterns)} patterns")
            return len(patterns)
        except Exception as e:
            logger.exception(f"Detection failed: {e}")
            return 0

    async def _run_cleanup(self) -> int:
        """Execute cleanup of old events."""
        try:
            from app.config import get_settings
            db = get_pattern_db()
            cleanup_retention_days = get_settings().cleanup_retention_days
            if cleanup_retention_days <= 0:
                logger.debug("Cleanup retention is 0 (never delete); skipping cleanup")
                return 0
            deleted = db.cleanup_old_events(days=cleanup_retention_days)
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old events")
            return deleted
        except Exception as e:
            logger.exception(f"Cleanup failed: {e}")
            return 0

    # Manual trigger methods for API endpoints

    async def run_sync_now(self) -> tuple[int, Optional[str]]:
        """Trigger an immediate sync. Returns (count, error)."""
        return await self._run_sync()

    async def run_detection_now(self) -> int:
        """Trigger immediate pattern detection. Returns pattern count."""
        return await self._run_detection()


# Singleton instance
_scheduler: Optional[PatternScheduler] = None


def get_pattern_scheduler(
    ha_url: Optional[str] = None, ha_token: Optional[str] = None
) -> Optional[PatternScheduler]:
    """
    Get the global pattern scheduler instance.

    Must provide ha_url and ha_token on first call to initialize.
    Returns None if not initialized and no credentials provided.
    """
    global _scheduler

    if _scheduler is None:
        if ha_url and ha_token:
            _scheduler = PatternScheduler(ha_url, ha_token)
        else:
            return None

    return _scheduler


def init_pattern_scheduler(ha_url: str, ha_token: str) -> PatternScheduler:
    """Initialize and return the pattern scheduler."""
    global _scheduler
    _scheduler = PatternScheduler(ha_url, ha_token)
    return _scheduler


def stop_pattern_scheduler() -> None:
    """Stop the global pattern scheduler if running."""
    global _scheduler
    if _scheduler:
        _scheduler.stop()
        _scheduler = None
