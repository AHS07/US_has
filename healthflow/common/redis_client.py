"""
common/redis_client.py

Thin wrapper around Redis DB 0 (slot counters + cache).
All slot-counter operations go through this module so the key schema
is defined exactly once and can be mocked cleanly in tests.

Redis DB layout (config/settings/base.py):
  DB 0 — slot-hold counters + general cache
  DB 1 — Celery broker (never touched here)

Key schema:
  slot:{slot_uuid}:remaining  →  integer, seeded from slot.capacity
"""
from __future__ import annotations

import logging

import redis
from django.conf import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis(
            host=getattr(settings, "REDIS_HOST", "redis"),
            port=int(getattr(settings, "REDIS_PORT", 6379)),
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
        )
    return _client


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------

def _slot_key(slot_id: str) -> str:
    return f"slot:{slot_id}:remaining"


# ---------------------------------------------------------------------------
# Counter operations
# ---------------------------------------------------------------------------

def slot_counter_seed(slot_id: str, capacity: int) -> None:
    """
    SET slot:{id}:remaining = capacity  (only if the key does not exist yet).
    Called when an AppointmentSlot is created so the counter is warm from
    the first hold attempt.
    """
    try:
        get_redis().setnx(_slot_key(slot_id), capacity)
    except redis.RedisError as exc:
        logger.warning("slot_counter_seed failed for slot %s: %s", slot_id, exc)


def slot_counter_decr(slot_id: str) -> int:
    """
    DECR slot:{id}:remaining.
    Returns the new value (negative means over-capacity — caller must INCR back
    and reject the hold).
    Raises RedisError propagated to caller on connection failure.
    """
    try:
        return int(get_redis().decr(_slot_key(slot_id)))
    except redis.RedisError as exc:
        logger.error("slot_counter_decr failed for slot %s: %s", slot_id, exc)
        raise


def slot_counter_incr(slot_id: str) -> int:
    """
    INCR slot:{id}:remaining  (hold abandoned / cancelled / expired).
    Best-effort — logs but does not raise on Redis failure because the
    Postgres booked_count reconciliation task will correct any drift.
    """
    try:
        return int(get_redis().incr(_slot_key(slot_id)))
    except redis.RedisError as exc:
        logger.warning("slot_counter_incr failed for slot %s: %s", slot_id, exc)
        return -1


def slot_counter_get(slot_id: str) -> int | None:
    """
    GET slot:{id}:remaining → int, or None if the key doesn't exist.
    """
    try:
        val = get_redis().get(_slot_key(slot_id))
        return int(val) if val is not None else None
    except redis.RedisError as exc:
        logger.warning("slot_counter_get failed for slot %s: %s", slot_id, exc)
        return None


def slot_counter_set(slot_id: str, value: int) -> None:
    """
    SET slot:{id}:remaining = value  (used by reconciliation task).
    """
    try:
        get_redis().set(_slot_key(slot_id), value)
    except redis.RedisError as exc:
        logger.warning("slot_counter_set failed for slot %s: %s", slot_id, exc)
