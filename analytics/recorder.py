"""Asynchronous fire-and-forget analytics event queue and background batch drainer."""

import asyncio
import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from config.settings import settings
from database.collections import ANALYTICS_EVENTS
from database.connection import get_database

logger = logging.getLogger(__name__)

_event_queue: asyncio.Queue[dict[str, Any]] | None = None
_drain_task: asyncio.Task[None] | None = None
_stop_event = asyncio.Event()


def get_event_queue() -> asyncio.Queue[dict[str, Any]]:
    """Return the global event queue singleton."""
    global _event_queue
    if _event_queue is None:
        _event_queue = asyncio.Queue(maxsize=settings.ANALYTICS_QUEUE_MAX_SIZE)
    return _event_queue


def enqueue_analytics_event(event: dict[str, Any]) -> None:
    """Non-blocking push of an event into the processing queue.

    If the queue is full, the event is safely dropped and a warning is logged.
    Analytics failures must NEVER affect client response paths.
    """
    queue = get_event_queue()
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        logger.warning("Analytics event queue is full; dropping event to preserve request latency")


async def _drain_loop(db: AsyncIOMotorDatabase) -> None:
    """Continuously drain events from queue and batch insert into MongoDB."""
    queue = get_event_queue()
    batch_size = settings.ANALYTICS_BATCH_SIZE
    flush_interval = settings.ANALYTICS_FLUSH_INTERVAL_SECONDS

    while not _stop_event.is_set():
        batch: list[dict[str, Any]] = []
        deadline = asyncio.get_running_loop().time() + flush_interval

        while len(batch) < batch_size:
            timeout = max(0.01, deadline - asyncio.get_running_loop().time())
            try:
                item = await asyncio.wait_for(queue.get(), timeout=timeout)
                batch.append(item)
                queue.task_done()
            except asyncio.TimeoutError:
                break
            except Exception as exc:
                logger.error(f"Error reading from analytics queue: {exc}")
                break

        if batch:
            try:
                await db[ANALYTICS_EVENTS].insert_many(batch, ordered=False)
            except Exception as exc:
                logger.warning(f"Batch write of {len(batch)} analytics events failed: {exc}")


def start_analytics_recorder(db: AsyncIOMotorDatabase | None = None) -> None:
    """Start background drain task during application startup."""
    global _drain_task, _stop_event
    _stop_event.clear()
    database = db if db is not None else get_database()
    _drain_task = asyncio.create_task(_drain_loop(database))
    logger.info("Analytics background recorder task started")


async def stop_analytics_recorder(db: AsyncIOMotorDatabase | None = None) -> None:
    """Gracefully drain remaining queue items and cancel background task during shutdown."""
    global _drain_task, _stop_event
    _stop_event.set()
    if _drain_task:
        _drain_task.cancel()
        try:
            await _drain_task
        except asyncio.CancelledError:
            pass
        _drain_task = None

    # Flush remaining items
    queue = get_event_queue()
    database = db if db is not None else get_database()
    remaining: list[dict[str, Any]] = []
    while not queue.empty():
        try:
            item = queue.get_nowait()
            remaining.append(item)
            queue.task_done()
        except asyncio.QueueEmpty:
            break

    if remaining:
        try:
            await database[ANALYTICS_EVENTS].insert_many(remaining, ordered=False)
            logger.info(f"Flushed {len(remaining)} remaining analytics events on shutdown")
        except Exception as exc:
            logger.warning(f"Failed to flush analytics events on shutdown: {exc}")
