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
    start_date, end_date = date_range
    tz = ZoneInfo(tenant.timezone)
    duration = timedelta(
        minutes=service.duration_minutes if service else tenant.default_slot_duration_minutes
    )
    buffer_delta = timedelta(minutes=tenant.booking_buffer_minutes)

    blocked_dates = _get_blocked_dates(tenant, date_range)
    busy_intervals = _collect_busy_intervals(tenant, date_range, tz, buffer_delta)

    now = timezone.now()
    slots = []
    current_date = start_date
    while current_date <= end_date:
        if current_date not in blocked_dates:
            slots.extend(
                _generate_day_slots(tenant, current_date, tz, duration, busy_intervals, now)
            )
        current_date += timedelta(days=1)
    return slots


def _get_blocked_dates(tenant, date_range):
    from bookings.models import BlockedDate

    start_date, end_date = date_range
    return set(
        BlockedDate.objects.filter(tenant=tenant, date__range=(start_date, end_date)).values_list(
            "date", flat=True
        )
    )


def _collect_busy_intervals(tenant, date_range, tz, buffer_delta):
    """Busy time from our own Bookings, plus - if the tenant has a connected
    external calendar - that calendar's busy time too. Booking is always the
    source of truth (also covers a Booking created while the external write
    failed); a connected calendar only ever adds more busy time on top,
    never replaces this."""
    from bookings.models import Booking

    start_date, end_date = date_range
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

    connection = getattr(tenant, "calendar_connection", None)
    if connection is not None:
        from bookings.calendar import get_provider

        busy_intervals.extend(
            (slot.start - buffer_delta, slot.end + buffer_delta)
            for slot in get_provider(connection).get_busy_intervals(connection, date_range)
        )

    return busy_intervals


def _generate_day_slots(tenant, day, tz, duration, busy_intervals, now):
    """Chop one open day into duration-sized slots, dropping any that are
    already past or collide with a busy interval. Returns [] if the tenant
    has no working hours configured for this weekday (closed)."""
    day_key = day.strftime("%a").lower()[:3]
    hours = tenant.working_hours.get(day_key)
    if not hours:
        return []

    day_start = datetime.combine(day, time.fromisoformat(hours[0]), tzinfo=tz)
    day_end = datetime.combine(day, time.fromisoformat(hours[1]), tzinfo=tz)

    slots = []
    cursor = day_start
    while cursor + duration <= day_end:
        slot_end = cursor + duration
        if cursor >= now and not _overlaps_any(cursor, slot_end, busy_intervals):
            slots.append(TimeSlot(start=cursor, end=slot_end))
        cursor += duration
    return slots


def _overlaps_any(start, end, intervals):
    return any(start < busy_end and end > busy_start for busy_start, busy_end in intervals)


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
