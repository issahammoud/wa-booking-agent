from django.db import IntegrityError, transaction

from bookings.models import Booking


class SlotUnavailableError(Exception):
    """Raised when create_booking's (tenant, scheduled_start) slot is already
    taken by a confirmed booking.

    The transaction.atomic() block below is what makes this safe under real
    concurrency, not just sequential calls: the (tenant, scheduled_start)
    UniqueConstraint is enforced by Postgres itself at INSERT time, so of two
    near-simultaneous transactions attempting the same slot, one commits and
    the other's INSERT raises IntegrityError inside its own atomic block -
    it never sees a false "still available" state to race against.
    """


def create_booking(tenant, end_user, slot, service):
    try:
        with transaction.atomic():
            return Booking.objects.create(
                tenant=tenant,
                end_user=end_user,
                service=service,
                scheduled_start=slot.start,
                scheduled_end=slot.end,
                status=Booking.Status.CONFIRMED,
            )
    except IntegrityError as exc:
        raise SlotUnavailableError(
            f"Slot {slot.start} is already booked for tenant {tenant.id}"
        ) from exc
