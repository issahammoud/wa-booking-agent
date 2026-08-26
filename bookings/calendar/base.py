from abc import ABC, abstractmethod
from datetime import UTC, date, datetime, time


def decode_token(token):
    """CalendarConnection.access_token/refresh_token are currently stored as
    plain bytes (no encryption implemented yet - same as
    Tenant.whatsapp_access_token)."""
    if isinstance(token, bytes | memoryview):
        return bytes(token).decode()
    return token


def auth_header(connection):
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
