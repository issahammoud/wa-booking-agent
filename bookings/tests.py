import datetime
import threading
from itertools import pairwise
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.urls import reverse
from django.utils import timezone

from bookings.availability import TimeSlot, check_availability, compute_available_slots
from bookings.models import BlockedDate, Booking, Service
from bookings.services import SlotUnavailableError, create_booking
from conversations.models import EndUser
from integrations.models import CalendarConnection
from tenants.models import Tenant


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


@pytest.fixture
def calendar_connection(tenant):
    return CalendarConnection.objects.create(
        tenant=tenant,
        provider="google",
        external_calendar_id="primary",
        access_token=b"fake-token",
        refresh_token=b"fake-refresh",
        token_expires_at=timezone.now() + datetime.timedelta(hours=1),
    )


def test_compute_available_slots_excludes_external_busy_time_when_connected(
    tenant, calendar_connection
):
    tenant.working_hours = {"mon": ["09:00", "10:00"]}
    tenant.timezone = "Europe/Paris"
    tenant.save()
    monday = _next_monday()
    tz = ZoneInfo("Europe/Paris")
    external_busy = TimeSlot(
        start=datetime.datetime(monday.year, monday.month, monday.day, 9, 0, tzinfo=tz),
        end=datetime.datetime(monday.year, monday.month, monday.day, 9, 30, tzinfo=tz),
    )

    # No Booking rows at all - this busy time exists only on the external
    # calendar, proving it's genuinely additive, not derived from Booking.
    with patch("bookings.calendar.get_provider") as mock_get_provider:
        mock_get_provider.return_value.get_busy_intervals.return_value = [external_busy]
        slots = compute_available_slots(tenant, None, (monday, monday))

    assert slots == [
        TimeSlot(
            start=datetime.datetime(monday.year, monday.month, monday.day, 9, 30, tzinfo=tz),
            end=datetime.datetime(monday.year, monday.month, monday.day, 10, 0, tzinfo=tz),
        )
    ]


def test_compute_available_slots_unaffected_when_no_calendar_connected(tenant):
    tenant.working_hours = {"mon": ["09:00", "10:00"]}
    tenant.timezone = "Europe/Paris"
    tenant.save()
    monday = _next_monday()

    slots = compute_available_slots(tenant, None, (monday, monday))

    assert len(slots) == 2


def test_create_booking_syncs_to_connected_external_calendar(
    tenant, end_user, service, calendar_connection
):
    start = timezone.now() + datetime.timedelta(days=1)
    slot = TimeSlot(start=start, end=start + datetime.timedelta(minutes=30))

    with patch("bookings.calendar.get_provider") as mock_get_provider:
        mock_get_provider.return_value.create_event.return_value = "external-id-123"
        booking = create_booking(tenant, end_user, slot, service)

    booking.refresh_from_db()
    assert booking.external_event_id == "external-id-123"


def test_create_booking_survives_external_sync_failure(
    tenant, end_user, service, calendar_connection
):
    start = timezone.now() + datetime.timedelta(days=1)
    slot = TimeSlot(start=start, end=start + datetime.timedelta(minutes=30))

    with patch("bookings.calendar.get_provider") as mock_get_provider:
        mock_get_provider.return_value.create_event.side_effect = Exception("API down")
        booking = create_booking(tenant, end_user, slot, service)

    booking.refresh_from_db()
    assert booking.status == Booking.Status.CONFIRMED
    assert booking.external_event_id == ""


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


@pytest.mark.django_db(transaction=True)
def test_create_booking_concurrent_requests_only_one_succeeds():
    # transaction=True (real commits, separate connections per thread) so
    # this genuinely exercises overlapping database transactions - not just
    # two sequential calls, which the DB-level constraint alone can't prove
    # is race-safe. Built inline rather than via the `tenant`/`end_user`
    # fixtures, which depend on the plain `db` fixture and would conflict
    # with `transaction=True` on the same test.
    tenant = Tenant.objects.create(business_name="Concurrency Test", vertical=Tenant.Vertical.OTHER)
    end_user = EndUser.objects.create(tenant=tenant, phone_number="+15550001234")
    service = Service.objects.create(tenant=tenant, name="Consult", duration_minutes=30)
    start = timezone.now() + datetime.timedelta(days=1)
    slot = TimeSlot(start=start, end=start + datetime.timedelta(minutes=30))

    barrier = threading.Barrier(2)
    results = []

    def attempt():
        barrier.wait()
        try:
            results.append(("ok", create_booking(tenant, end_user, slot, service)))
        except SlotUnavailableError as exc:
            results.append(("error", exc))
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    outcomes = [outcome for outcome, _ in results]
    assert outcomes.count("ok") == 1
    assert outcomes.count("error") == 1
    assert Booking.objects.filter(tenant=tenant, scheduled_start=start).count() == 1


def test_dashboard_shows_only_own_tenant_upcoming_bookings(
    client, tenant, other_tenant, end_user, service, staff_user
):
    other_end_user = EndUser.objects.create(tenant=other_tenant, phone_number="+15550004321")
    start = timezone.now() + datetime.timedelta(days=1)
    own_booking = Booking.objects.create(
        tenant=tenant,
        end_user=end_user,
        service=service,
        scheduled_start=start,
        scheduled_end=start + datetime.timedelta(minutes=30),
    )
    other_booking = Booking.objects.create(
        tenant=other_tenant,
        end_user=other_end_user,
        scheduled_start=start,
        scheduled_end=start + datetime.timedelta(minutes=30),
    )

    client.force_login(staff_user)
    response = client.get(reverse("dashboard-home"))

    visible = list(response.context["bookings"])
    assert own_booking in visible
    assert other_booking not in visible


def test_dashboard_excludes_past_and_non_confirmed_bookings(
    tenant, end_user, service, staff_user, client
):
    past_start = timezone.now() - datetime.timedelta(days=1)
    cancelled_start = timezone.now() + datetime.timedelta(days=2)
    Booking.objects.create(
        tenant=tenant,
        end_user=end_user,
        service=service,
        scheduled_start=past_start,
        scheduled_end=past_start + datetime.timedelta(minutes=30),
    )
    Booking.objects.create(
        tenant=tenant,
        end_user=end_user,
        service=service,
        status=Booking.Status.CANCELLED,
        scheduled_start=cancelled_start,
        scheduled_end=cancelled_start + datetime.timedelta(minutes=30),
    )

    client.force_login(staff_user)
    response = client.get(reverse("dashboard-home"))

    assert list(response.context["bookings"]) == []


def test_platform_admin_sees_all_tenants_upcoming_bookings(
    client, tenant, other_tenant, end_user, service, platform_admin_user
):
    other_end_user = EndUser.objects.create(tenant=other_tenant, phone_number="+15550004322")
    start = timezone.now() + datetime.timedelta(days=1)
    own_booking = Booking.objects.create(
        tenant=tenant,
        end_user=end_user,
        service=service,
        scheduled_start=start,
        scheduled_end=start + datetime.timedelta(minutes=30),
    )
    other_booking = Booking.objects.create(
        tenant=other_tenant,
        end_user=other_end_user,
        scheduled_start=start,
        scheduled_end=start + datetime.timedelta(minutes=30),
    )

    client.force_login(platform_admin_user)
    response = client.get(reverse("dashboard-home"))

    visible = list(response.context["bookings"])
    assert own_booking in visible
    assert other_booking in visible
