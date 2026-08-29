import logging

from django.db import IntegrityError, transaction

from bookings.models import Booking

logger = logging.getLogger(__name__)


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
            booking = Booking.objects.create(
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

    # Outside the transaction: a slow/failed external call shouldn't hold a
    # DB lock, and a failed sync is a recoverable follow-up, not a reason to
    # fail a booking that's already confirmed locally (same failure-tolerance
    # precedent as the outbound WhatsApp send policy in Sprint 4).
    connection = getattr(tenant, "calendar_connection", None)
    if connection is not None:
        from bookings.calendar import get_provider

        try:
            external_event_id = get_provider(connection).create_event(
                connection, slot, summary=f"Booking: {service.name if service else 'Appointment'}"
            )
        except Exception:
            logger.exception(
                "Failed to sync booking id=%s to external calendar for tenant=%s",
                booking.id,
                tenant.id,
            )
        else:
            booking.external_event_id = external_event_id
            booking.save(update_fields=["external_event_id"])

    return booking
