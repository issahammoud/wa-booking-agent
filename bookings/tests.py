import datetime
from itertools import pairwise
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from bookings.availability import TimeSlot, check_availability, compute_available_slots
from bookings.models import BlockedDate, Booking, Service
from bookings.services import SlotUnavailableError, create_booking
from conversations.models import EndUser


@pytest.fixture
def end_user(tenant):
    return EndUser.objects.create(tenant=tenant, phone_number="+15550000003")


@pytest.fixture
def service(tenant):
    return Service.objects.create(tenant=tenant, name="Consultation", duration_minutes=30)


def test_booking_confirmed_slot_unique_per_tenant(tenant, end_user):
    start = timezone.now()
    end = start + datetime.timedelta(minutes=30)
    Booking.objects.create(
        tenant=tenant,
        end_user=end_user,
        scheduled_start=start,
        scheduled_end=end,
        status=Booking.Status.CONFIRMED,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        Booking.objects.create(
            tenant=tenant,
            end_user=end_user,
            scheduled_start=start,
            scheduled_end=end,
            status=Booking.Status.CONFIRMED,
        )


def test_booking_same_slot_allowed_when_not_confirmed(tenant, end_user):
    start = timezone.now()
    end = start + datetime.timedelta(minutes=30)
    Booking.objects.create(
        tenant=tenant,
        end_user=end_user,
        scheduled_start=start,
        scheduled_end=end,
        status=Booking.Status.CANCELLED,
    )
    # Same (tenant, scheduled_start) but not confirmed: the partial
    # constraint doesn't apply, so a second row is allowed.
    Booking.objects.create(
        tenant=tenant,
        end_user=end_user,
        scheduled_start=start,
        scheduled_end=end,
        status=Booking.Status.CANCELLED,
    )


def test_booking_clean_rejects_end_before_start(tenant, end_user):
    start = timezone.now()
    booking = Booking(
        tenant=tenant,
        end_user=end_user,
        scheduled_start=start,
        scheduled_end=start - datetime.timedelta(minutes=1),
    )
    with pytest.raises(ValidationError):
        booking.clean()


def test_booking_clean_rejects_equal_start_and_end(tenant, end_user):
    start = timezone.now()
    booking = Booking(tenant=tenant, end_user=end_user, scheduled_start=start, scheduled_end=start)
    with pytest.raises(ValidationError):
        booking.clean()


def test_blocked_date_unique_per_tenant(tenant):
    today = datetime.date.today()
    BlockedDate.objects.create(tenant=tenant, date=today)

    with pytest.raises(IntegrityError), transaction.atomic():
        BlockedDate.objects.create(tenant=tenant, date=today)


def test_check_availability_defaults_to_empty_when_no_working_hours(tenant):
    # tenant fixture has working_hours={} (the model default) - closed every
    # day until explicitly configured, never a guessed/open-by-default set.
    assert check_availability(tenant) == []


def test_check_availability_returns_real_computed_slots(tenant):
    tenant.working_hours = {"mon": ["09:00", "12:00"]}
    tenant.timezone = "Europe/Paris"
    tenant.save()
    monday = _next_monday()

    slots = check_availability(tenant, date_range=(monday, monday))

    assert len(slots) == 6
    for slot in slots:
        assert (slot.end - slot.start) == datetime.timedelta(minutes=30)
    for earlier, later in pairwise(slots):
        assert later.start >= earlier.end


def _next_monday():
    today = timezone.now().date()
    days_ahead = (0 - today.weekday()) % 7 or 7
    return today + datetime.timedelta(days=days_ahead)


def test_compute_available_slots_empty_when_day_fully_booked(tenant, end_user):
    tenant.working_hours = {"mon": ["09:00", "10:00"]}
    tenant.timezone = "Europe/Paris"
    tenant.save()
    monday = _next_monday()
    tz = ZoneInfo("Europe/Paris")

    for hour, minute in [(9, 0), (9, 30)]:
        start = datetime.datetime(monday.year, monday.month, monday.day, hour, minute, tzinfo=tz)
        Booking.objects.create(
            tenant=tenant,
            end_user=end_user,
            scheduled_start=start,
            scheduled_end=start + datetime.timedelta(minutes=30),
            status=Booking.Status.CONFIRMED,
        )

    slots = compute_available_slots(tenant, None, (monday, monday))

    assert slots == []


def test_compute_available_slots_empty_on_blocked_date(tenant):
    tenant.working_hours = {"mon": ["09:00", "17:00"]}
    tenant.timezone = "Europe/Paris"
    tenant.save()
    monday = _next_monday()
    BlockedDate.objects.create(tenant=tenant, date=monday)

    slots = compute_available_slots(tenant, None, (monday, monday))

    assert slots == []


def test_compute_available_slots_buffer_prevents_false_gap_between_bookings(tenant, end_user):
    # Working hours 09:00-11:00, 30-min slots, 15-min buffer. Two bookings
    # leave a raw 30-minute gap (09:30-10:00) that would look like exactly
    # one free slot with no buffer - the buffer should swallow it since
    # 15 minutes on each side of both bookings overlaps that gap entirely.
    tenant.working_hours = {"mon": ["09:00", "11:00"]}
    tenant.timezone = "Europe/Paris"
    tenant.booking_buffer_minutes = 15
    tenant.save()
    monday = _next_monday()
    tz = ZoneInfo("Europe/Paris")

    for hour, minute in [(9, 0), (10, 0)]:
        start = datetime.datetime(monday.year, monday.month, monday.day, hour, minute, tzinfo=tz)
        Booking.objects.create(
            tenant=tenant,
            end_user=end_user,
            scheduled_start=start,
            scheduled_end=start + datetime.timedelta(minutes=30),
            status=Booking.Status.CONFIRMED,
        )

    slots = compute_available_slots(tenant, None, (monday, monday))

    assert slots == []


def test_compute_available_slots_uses_tenant_timezone_not_utc(tenant):
    # America/New_York is hours behind UTC - if the code accidentally used
    # UTC or server-local time instead of tenant.timezone, this slot's start
    # would not land on 09:00 local / would land on 09:00 UTC instead.
    tenant.working_hours = {"mon": ["09:00", "09:30"]}
    tenant.timezone = "America/New_York"
    tenant.save()
    monday = _next_monday()

    slots = compute_available_slots(tenant, None, (monday, monday))

    assert len(slots) == 1
    slot = slots[0]
    assert slot.start.astimezone(ZoneInfo("America/New_York")).hour == 9
    assert slot.start.astimezone(datetime.UTC).hour != 9


def test_create_booking_creates_confirmed_booking(tenant, end_user, service):
    start = timezone.now() + datetime.timedelta(days=1)
    slot = TimeSlot(start=start, end=start + datetime.timedelta(minutes=30))

    booking = create_booking(tenant, end_user, slot, service)

    assert booking.pk is not None
    assert booking.status == Booking.Status.CONFIRMED
    assert booking.scheduled_start == start
    assert booking.scheduled_end == slot.end
    assert booking.end_user == end_user
    assert booking.service == service


def test_create_booking_raises_clear_error_on_duplicate_slot(tenant, end_user, service):
    start = timezone.now() + datetime.timedelta(days=1)
    slot = TimeSlot(start=start, end=start + datetime.timedelta(minutes=30))

    create_booking(tenant, end_user, slot, service)

    with pytest.raises(SlotUnavailableError):
        create_booking(tenant, end_user, slot, service)
