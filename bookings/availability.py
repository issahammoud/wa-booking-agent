from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

DEFAULT_SEARCH_DAYS = 7


@dataclass
class TimeSlot:
    start: datetime
    end: datetime


def compute_available_slots(tenant, service, date_range):
    """Real availability: tenant.working_hours minus BlockedDate minus
    existing confirmed Bookings, for each date in date_range.

    date_range is (start_date, end_date), both inclusive date objects.
    service may be None, in which case tenant.default_slot_duration_minutes
    is used instead of service.duration_minutes.
    """
    from bookings.models import BlockedDate, Booking

    start_date, end_date = date_range
    tz = ZoneInfo(tenant.timezone)
    duration = timedelta(
        minutes=service.duration_minutes if service else tenant.default_slot_duration_minutes
    )
    buffer_delta = timedelta(minutes=tenant.booking_buffer_minutes)

    blocked_dates = set(
        BlockedDate.objects.filter(tenant=tenant, date__range=(start_date, end_date)).values_list(
            "date", flat=True
        )
    )

    range_start = datetime.combine(start_date, time.min, tzinfo=tz)
    range_end = datetime.combine(end_date, time.max, tzinfo=tz)
    busy_intervals = [
        (booking.scheduled_start - buffer_delta, booking.scheduled_end + buffer_delta)
        for booking in Booking.objects.filter(
            tenant=tenant,
            status=Booking.Status.CONFIRMED,
            scheduled_start__lt=range_end,
            scheduled_end__gt=range_start,
        )
    ]

    # Booking is always the source of truth (also covers a Booking created
    # while the external write failed) - a connected calendar only ever adds
    # more busy time on top, never replaces this.
    connection = getattr(tenant, "calendar_connection", None)
    if connection is not None:
        from bookings.calendar import get_provider

        busy_intervals.extend(
            (slot.start - buffer_delta, slot.end + buffer_delta)
            for slot in get_provider(connection).get_busy_intervals(connection, date_range)
        )

    now = timezone.now()
    slots = []
    current_date = start_date
    while current_date <= end_date:
        if current_date not in blocked_dates:
            day_key = current_date.strftime("%a").lower()[:3]
            hours = tenant.working_hours.get(day_key)
            if hours:
                day_start = datetime.combine(current_date, time.fromisoformat(hours[0]), tzinfo=tz)
                day_end = datetime.combine(current_date, time.fromisoformat(hours[1]), tzinfo=tz)
                cursor = day_start
                while cursor + duration <= day_end:
                    slot_end = cursor + duration
                    if cursor >= now and not any(
                        cursor < busy_end and slot_end > busy_start
                        for busy_start, busy_end in busy_intervals
                    ):
                        slots.append(TimeSlot(start=cursor, end=slot_end))
                    cursor += duration
        current_date += timedelta(days=1)
    return slots


def check_availability(tenant, date_range=None, service=None):
    """Real computation, replacing the earlier Phase 3 hardcoded stub.

    date_range defaults to a DEFAULT_SEARCH_DAYS window starting today, in
    the tenant's own timezone.
    """
    if date_range is None:
        tz = ZoneInfo(tenant.timezone)
        today = timezone.now().astimezone(tz).date()
        date_range = (today, today + timedelta(days=DEFAULT_SEARCH_DAYS - 1))
    return compute_available_slots(tenant, service, date_range)
