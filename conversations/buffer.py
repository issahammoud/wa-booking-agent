"""Raw Redis operations backing the per-(tenant, end_user) debounce buffer.

No Celery or business logic here on purpose - see conversations/tasks.py for
the task that uses these, and the module docstring there for the full
correctness argument (why the timestamp check + this module's transactional
drain together prevent double-processing).
"""

import time

import redis
from django.conf import settings

_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _buffer_key(tenant_id, end_user_id):
    return f"buffer:{tenant_id}:{end_user_id}:messages"


def _timestamp_key(tenant_id, end_user_id):
    return f"buffer:{tenant_id}:{end_user_id}:last_message_at"


def push_message(tenant_id, end_user_id, message_id):
    """Push a message id onto the buffer, refresh the last-message timestamp.

    Returns that timestamp, which the caller schedules the debounce check
    against.
    """
    redis_conn = _get_redis()
    key = _buffer_key(tenant_id, end_user_id)
    ts_key = _timestamp_key(tenant_id, end_user_id)
    now = time.time()
    # Generous TTL: just a safety net against orphaned keys, not a real limit
    # - the debounce window itself is what normally clears these.
    ttl = settings.DEBOUNCE_WINDOW_SECONDS * 6

    redis_conn.rpush(key, message_id)
    redis_conn.expire(key, ttl)
    redis_conn.set(ts_key, now, ex=ttl)
    return now


def get_last_message_at(tenant_id, end_user_id):
    value = _get_redis().get(_timestamp_key(tenant_id, end_user_id))
    return float(value) if value is not None else None


def peek(tenant_id, end_user_id):
    """Non-destructive read of the currently buffered message ids. For tests/debugging."""
    key = _buffer_key(tenant_id, end_user_id)
    return [int(m) for m in _get_redis().lrange(key, 0, -1)]


def drain(tenant_id, end_user_id):
    """Atomically read and clear the buffer. Returns a list of message ids (possibly empty).

    Uses a Redis transaction (MULTI/EXEC) so that if two callers race to
    drain the same buffer, Redis's single-threaded execution serializes
    their transactions: the first gets the real ids, the second gets an
    empty list. That's what actually prevents double-processing.
    """
    redis_conn = _get_redis()
    key = _buffer_key(tenant_id, end_user_id)
    ts_key = _timestamp_key(tenant_id, end_user_id)
    with redis_conn.pipeline(transaction=True) as pipe:
        pipe.lrange(key, 0, -1)
        pipe.delete(key)
        pipe.delete(ts_key)
        message_ids, _, _ = pipe.execute()
    return [int(m) for m in message_ids]
