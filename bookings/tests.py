import datetime

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from bookings.models import BlockedDate, Booking
from conversations.models import EndUser


@pytest.fixture
def end_user(tenant):
    return EndUser.objects.create(tenant=tenant, phone_number="+15550000003")


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
