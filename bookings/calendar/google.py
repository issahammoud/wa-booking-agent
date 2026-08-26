from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import requests

from bookings.availability import TimeSlot
from bookings.calendar.base import CalendarProvider, decode_token

EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


class GoogleCalendarProvider(CalendarProvider):
    """Google Calendar API v3, via direct REST calls (no google-api-python-client
    dependency needed for two endpoints)."""

    def get_busy_intervals(self, connection, date_range):
        start_date, end_date = date_range
        response = requests.get(
            EVENTS_URL,
            headers=_auth_header(connection),
            params={
                "timeMin": _day_bound(start_date, time.min).isoformat(),
                "timeMax": _day_bound(end_date, time.max).isoformat(),
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
            headers=_auth_header(connection),
            json={
                "summary": summary,
                "start": {"dateTime": slot.start.isoformat()},
                "end": {"dateTime": slot.end.isoformat()},
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.json()["id"]


def _auth_header(connection):
    return {"Authorization": f"Bearer {decode_token(connection.access_token)}"}


def _day_bound(day: date, bound_time: time) -> datetime:
    return datetime.combine(day, bound_time, tzinfo=ZoneInfo("UTC"))
