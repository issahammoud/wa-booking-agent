import datetime
from itertools import pairwise

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from bookings.availability import TimeSlot, check_availability
from bookings.models import BlockedDate, Booking, Service
from bookings.services import SlotAlreadyBookedError, create_booking
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


def test_check_availability_returns_consistent_fake_slots(tenant):
    slots = check_availability(tenant)

    assert len(slots) == 3
    now = timezone.now()
    for slot in slots:
        assert slot.start > now
        assert slot.end > slot.start
        assert (slot.end - slot.start) == datetime.timedelta(minutes=30)
    # Ordered, non-overlapping.
    for earlier, later in pairwise(slots):
        assert later.start > earlier.end


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

    with pytest.raises(SlotAlreadyBookedError):
        create_booking(tenant, end_user, slot, service)
