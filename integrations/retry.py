import logging
import time

import requests

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def call_with_retry(func, *args, max_attempts=3, base_delay=1.0, **kwargs):
    """Call func(*args, **kwargs), retrying with exponential backoff on
    retryable failures only: timeouts, connection errors, HTTP 429, and
    HTTP 5xx. Anything else (including a 401 from an expired/invalid
    token - see bookings/calendar/base.py's own refresh-before-expiry
    handling for that case) re-raises immediately, on the theory that
    retrying a request that's wrong rather than unlucky just wastes time
    and delays surfacing the real problem.

    func must raise on failure (e.g. call response.raise_for_status()
    itself) - this wrapper only decides whether to retry what func raises,
    it doesn't inspect a returned value.
    """
    last_exc = None
    for attempt in range(max_attempts):
        try:
            return func(*args, **kwargs)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status not in RETRYABLE_STATUS_CODES:
                raise
            last_exc = exc
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc

        if attempt < max_attempts - 1:
            delay = base_delay * (2**attempt)
            logger.warning(
                "Retryable failure (attempt %d/%d), retrying in %.1fs: %s",
                attempt + 1,
                max_attempts,
                delay,
                last_exc,
            )
            time.sleep(delay)

    raise last_exc
