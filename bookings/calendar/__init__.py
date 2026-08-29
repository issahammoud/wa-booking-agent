from bookings.calendar.google import GoogleCalendarProvider
from bookings.calendar.outlook import OutlookCalendarProvider

_PROVIDERS = {
    "google": GoogleCalendarProvider(),
    "outlook": OutlookCalendarProvider(),
}


def get_provider(connection):
    provider = _PROVIDERS.get(connection.provider)
    if provider is None:
        raise ValueError(f"Unknown calendar provider: {connection.provider!r}")
    return provider
