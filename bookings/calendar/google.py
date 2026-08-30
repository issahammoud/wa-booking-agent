from datetime import datetime, time, timedelta

import requests
from django.conf import settings
from django.utils import timezone

from bookings.availability import TimeSlot
from bookings.calendar.base import CalendarProvider, auth_header, day_bound, decode_token

EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
OAUTH_SCOPE = "https://www.googleapis.com/auth/calendar.events"


class GoogleCalendarProvider(CalendarProvider):
    """Google Calendar API v3, via direct REST calls (no google-api-python-client
    dependency needed for two endpoints)."""

    def get_busy_intervals(self, connection, date_range):
        start_date, end_date = date_range
        response = requests.get(
            EVENTS_URL,
            headers=auth_header(connection),
            params={
                "timeMin": day_bound(start_date, time.min).isoformat(),
                "timeMax": day_bound(end_date, time.max).isoformat(),
                "singleEvents": "true",
            },
            timeout=10,
        )
        response.raise_for_status()
        return [
            TimeSlot(
                start=datetime.fromisoformat(event["start"]["dateTime"]),
                end=datetime.fromisoformat(event["end"]["dateTime"]),
            )
            for event in response.json().get("items", [])
            if event.get("status") != "cancelled" and "dateTime" in event.get("start", {})
        ]

    def create_event(self, connection, slot, summary):
        response = requests.post(
            EVENTS_URL,
            headers=auth_header(connection),
            json={
                "summary": summary,
                "start": {"dateTime": slot.start.isoformat()},
                "end": {"dateTime": slot.end.isoformat()},
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.json()["id"]

    def refresh_access_token(self, connection):
        response = requests.post(
            TOKEN_URL,
            data={
                "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                "refresh_token": decode_token(connection.refresh_token),
                "grant_type": "refresh_token",
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        connection.access_token = data["access_token"].encode()
        connection.token_expires_at = timezone.now() + timedelta(seconds=data["expires_in"])
        connection.save(update_fields=["access_token", "token_expires_at"])
