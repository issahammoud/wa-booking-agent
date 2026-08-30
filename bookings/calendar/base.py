from abc import ABC, abstractmethod
from datetime import UTC, date, datetime, time, timedelta

from django.utils import timezone

# Refresh this far ahead of actual expiry, so a slow request never straddles
# the token dying mid-call.
REFRESH_BUFFER = timedelta(minutes=5)


def decode_token(token):
    """CalendarConnection.access_token/refresh_token are currently stored as
    plain bytes (no encryption implemented yet - same as
    Tenant.whatsapp_access_token)."""
    if isinstance(token, bytes | memoryview):
        return bytes(token).decode()
    return token


def auth_header(connection):
    """Refresh-aware: every real call to a provider's API goes through this,
    so it's the single place that keeps access_token from ever going stale
    without needing a separate periodic task."""
    if connection.token_expires_at <= timezone.now() + REFRESH_BUFFER:
        from bookings.calendar import get_provider

        get_provider(connection).refresh_access_token(connection)
    return {"Authorization": f"Bearer {decode_token(connection.access_token)}"}


def day_bound(day: date, bound_time: time) -> datetime:
    return datetime.combine(day, bound_time, tzinfo=UTC)


class CalendarProvider(ABC):
    """Shared contract for every external calendar integration.

    A failed API call is allowed to raise (never silently treated as "no
    busy time") - a connected calendar we can't currently reach is a reason
    to stop and surface the problem, not to fall back to a state that could
    double-book over something the doctor's real calendar already shows as
    busy.
    """

    @abstractmethod
    def get_busy_intervals(self, connection, date_range):
        """Return existing events on the external calendar overlapping
        date_range (a (start_date, end_date) tuple of dates), as a list of
        bookings.availability.TimeSlot."""

    @abstractmethod
    def create_event(self, connection, slot, summary):
        """Create an event on the external calendar for slot, returning its
        external event id (str)."""

    @abstractmethod
    def refresh_access_token(self, connection):
        """Exchange connection.refresh_token for a new access_token, persisting
        the new token and token_expires_at onto connection. Called by
        auth_header() when the current token is at/near expiry - never call
        this directly outside that check."""
