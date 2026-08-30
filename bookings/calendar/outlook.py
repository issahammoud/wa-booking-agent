from datetime import UTC, datetime, time, timedelta

import requests
from django.conf import settings
from django.utils import timezone

from bookings.availability import TimeSlot
from bookings.calendar.base import CalendarProvider, auth_header, day_bound, decode_token

CALENDAR_VIEW_URL = "https://graph.microsoft.com/v1.0/me/calendarView"
EVENTS_URL = "https://graph.microsoft.com/v1.0/me/events"
AUTHORIZE_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
OAUTH_SCOPE = "offline_access Calendars.ReadWrite"


class OutlookCalendarProvider(CalendarProvider):
    """Microsoft Graph API, via direct REST calls. The "Prefer:
    outlook.timezone" header forces every dateTime in the response to UTC,
    so we don't need to interpret Graph's separate per-event timeZone
    field."""

    def get_busy_intervals(self, connection, date_range):
        start_date, end_date = date_range
        response = requests.get(
            CALENDAR_VIEW_URL,
            headers={**auth_header(connection), "Prefer": 'outlook.timezone="UTC"'},
            params={
                "startDateTime": day_bound(start_date, time.min).isoformat(),
                "endDateTime": day_bound(end_date, time.max).isoformat(),
            },
            timeout=10,
        )
        response.raise_for_status()
        return [
            TimeSlot(
                start=_parse_utc(event["start"]["dateTime"]),
                end=_parse_utc(event["end"]["dateTime"]),
            )
            for event in response.json().get("value", [])
            if not event.get("isCancelled", False)
        ]

    def create_event(self, connection, slot, summary):
        response = requests.post(
            EVENTS_URL,
            headers=auth_header(connection),
            json={
                "subject": summary,
                "start": {"dateTime": _utc_naive_iso(slot.start), "timeZone": "UTC"},
                "end": {"dateTime": _utc_naive_iso(slot.end), "timeZone": "UTC"},
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.json()["id"]

    def refresh_access_token(self, connection):
        response = requests.post(
            TOKEN_URL,
            data={
                "client_id": settings.MICROSOFT_OAUTH_CLIENT_ID,
                "client_secret": settings.MICROSOFT_OAUTH_CLIENT_SECRET,
                "refresh_token": decode_token(connection.refresh_token),
                "grant_type": "refresh_token",
                "scope": OAUTH_SCOPE,
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        connection.access_token = data["access_token"].encode()
        connection.token_expires_at = timezone.now() + timedelta(seconds=data["expires_in"])
        update_fields = ["access_token", "token_expires_at"]
        # Microsoft rotates refresh tokens - persist the new one when given.
        if "refresh_token" in data:
            connection.refresh_token = data["refresh_token"].encode()
            update_fields.append("refresh_token")
        connection.save(update_fields=update_fields)


def _utc_naive_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _parse_utc(dt_string):
    # Graph returns dateTime without a UTC offset when the timezone is
    # forced via the Prefer header - interpret it as UTC explicitly.
    return datetime.fromisoformat(dt_string).replace(tzinfo=UTC)
