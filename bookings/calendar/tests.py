import datetime
from unittest.mock import Mock, patch

import pytest
import requests

from bookings.availability import TimeSlot
from bookings.calendar import get_provider
from bookings.calendar.google import GoogleCalendarProvider
from bookings.calendar.outlook import OutlookCalendarProvider
from integrations.models import CalendarConnection


@pytest.fixture
def google_connection(tenant):
    return CalendarConnection.objects.create(
        tenant=tenant,
        provider="google",
        external_calendar_id="primary",
        access_token=b"fake-google-token",
        refresh_token=b"fake-refresh",
        token_expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1),
    )


@pytest.fixture
def outlook_connection(other_tenant):
    return CalendarConnection.objects.create(
        tenant=other_tenant,
        provider="outlook",
        external_calendar_id="primary",
        access_token=b"fake-outlook-token",
        refresh_token=b"fake-refresh",
        token_expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1),
    )


def test_get_provider_dispatches_by_connection_provider(google_connection, outlook_connection):
    assert isinstance(get_provider(google_connection), GoogleCalendarProvider)
    assert isinstance(get_provider(outlook_connection), OutlookCalendarProvider)


def test_get_provider_raises_for_unknown_provider(tenant):
    connection = CalendarConnection(tenant=tenant, provider="internal")
    with pytest.raises(ValueError):
        get_provider(connection)


def test_google_get_busy_intervals_parses_events(google_connection):
    fake_response = Mock()
    fake_response.json.return_value = {
        "items": [
            {
                "status": "confirmed",
                "start": {"dateTime": "2026-09-01T10:00:00+02:00"},
                "end": {"dateTime": "2026-09-01T10:30:00+02:00"},
            },
            {
                "status": "cancelled",
                "start": {"dateTime": "2026-09-01T11:00:00+02:00"},
                "end": {"dateTime": "2026-09-01T11:30:00+02:00"},
            },
        ]
    }
    fake_response.raise_for_status = Mock()

    with patch("bookings.calendar.google.requests.get", return_value=fake_response) as mock_get:
        result = GoogleCalendarProvider().get_busy_intervals(
            google_connection, (datetime.date(2026, 9, 1), datetime.date(2026, 9, 1))
        )

    assert mock_get.call_args.kwargs["headers"]["Authorization"] == "Bearer fake-google-token"
    assert result == [
        TimeSlot(
            start=datetime.datetime.fromisoformat("2026-09-01T10:00:00+02:00"),
            end=datetime.datetime.fromisoformat("2026-09-01T10:30:00+02:00"),
        )
    ]


def test_google_create_event_returns_external_id(google_connection):
    fake_response = Mock()
    fake_response.json.return_value = {"id": "google-event-123"}
    fake_response.raise_for_status = Mock()
    slot = TimeSlot(
        start=datetime.datetime(2026, 9, 1, 10, 0, tzinfo=datetime.UTC),
        end=datetime.datetime(2026, 9, 1, 10, 30, tzinfo=datetime.UTC),
    )

    with patch("bookings.calendar.google.requests.post", return_value=fake_response):
        event_id = GoogleCalendarProvider().create_event(
            google_connection, slot, "Booking: Consult"
        )

    assert event_id == "google-event-123"


def test_google_get_busy_intervals_raises_on_http_error(google_connection):
    with patch("bookings.calendar.google.requests.get", side_effect=requests.ConnectionError):
        with pytest.raises(requests.ConnectionError):
            GoogleCalendarProvider().get_busy_intervals(
                google_connection, (datetime.date(2026, 9, 1), datetime.date(2026, 9, 1))
            )


def test_outlook_get_busy_intervals_parses_events(outlook_connection):
    fake_response = Mock()
    fake_response.json.return_value = {
        "value": [
            {
                "isCancelled": False,
                "start": {"dateTime": "2026-09-01T10:00:00.0000000"},
                "end": {"dateTime": "2026-09-01T10:30:00.0000000"},
            },
            {
                "isCancelled": True,
                "start": {"dateTime": "2026-09-01T11:00:00.0000000"},
                "end": {"dateTime": "2026-09-01T11:30:00.0000000"},
            },
        ]
    }
    fake_response.raise_for_status = Mock()

    with patch("bookings.calendar.outlook.requests.get", return_value=fake_response) as mock_get:
        result = OutlookCalendarProvider().get_busy_intervals(
            outlook_connection, (datetime.date(2026, 9, 1), datetime.date(2026, 9, 1))
        )

    assert mock_get.call_args.kwargs["headers"]["Authorization"] == "Bearer fake-outlook-token"
    assert result == [
        TimeSlot(
            start=datetime.datetime(2026, 9, 1, 10, 0, tzinfo=datetime.UTC),
            end=datetime.datetime(2026, 9, 1, 10, 30, tzinfo=datetime.UTC),
        )
    ]


def test_outlook_create_event_returns_external_id(outlook_connection):
    fake_response = Mock()
    fake_response.json.return_value = {"id": "outlook-event-456"}
    fake_response.raise_for_status = Mock()
    slot = TimeSlot(
        start=datetime.datetime(2026, 9, 1, 10, 0, tzinfo=datetime.UTC),
        end=datetime.datetime(2026, 9, 1, 10, 30, tzinfo=datetime.UTC),
    )

    with patch("bookings.calendar.outlook.requests.post", return_value=fake_response):
        event_id = OutlookCalendarProvider().create_event(
            outlook_connection, slot, "Booking: Consult"
        )

    assert event_id == "outlook-event-456"


def test_google_refresh_access_token_updates_connection(google_connection):
    fake_response = Mock()
    fake_response.json.return_value = {"access_token": "new-google-token", "expires_in": 3600}
    fake_response.raise_for_status = Mock()

    with patch("bookings.calendar.google.requests.post", return_value=fake_response) as mock_post:
        GoogleCalendarProvider().refresh_access_token(google_connection)

    assert mock_post.call_args.kwargs["data"]["refresh_token"] == "fake-refresh"
    assert mock_post.call_args.kwargs["data"]["grant_type"] == "refresh_token"
    google_connection.refresh_from_db()
    assert bytes(google_connection.access_token) == b"new-google-token"
    assert google_connection.token_expires_at > datetime.datetime.now(datetime.UTC)


def test_outlook_refresh_access_token_rotates_refresh_token_when_given(outlook_connection):
    fake_response = Mock()
    fake_response.json.return_value = {
        "access_token": "new-outlook-token",
        "refresh_token": "rotated-refresh",
        "expires_in": 3600,
    }
    fake_response.raise_for_status = Mock()

    with patch("bookings.calendar.outlook.requests.post", return_value=fake_response):
        OutlookCalendarProvider().refresh_access_token(outlook_connection)

    outlook_connection.refresh_from_db()
    assert bytes(outlook_connection.access_token) == b"new-outlook-token"
    assert bytes(outlook_connection.refresh_token) == b"rotated-refresh"


def test_auth_header_refreshes_when_token_expired(google_connection):
    google_connection.token_expires_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
        minutes=1
    )
    google_connection.save()
    fake_response = Mock()
    fake_response.json.return_value = {"access_token": "refreshed-token", "expires_in": 3600}
    fake_response.raise_for_status = Mock()

    with patch("bookings.calendar.google.requests.post", return_value=fake_response):
        from bookings.calendar.base import auth_header

        header = auth_header(google_connection)

    assert header == {"Authorization": "Bearer refreshed-token"}


def test_auth_header_skips_refresh_when_token_still_valid(google_connection):
    with patch(
        "bookings.calendar.google.GoogleCalendarProvider.refresh_access_token"
    ) as mock_refresh:
        from bookings.calendar.base import auth_header

        header = auth_header(google_connection)

    mock_refresh.assert_not_called()
    assert header == {"Authorization": "Bearer fake-google-token"}
