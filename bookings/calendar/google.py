from datetime import datetime, time

import requests

from bookings.availability import TimeSlot
from bookings.calendar.base import CalendarProvider, auth_header, day_bound

EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


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
