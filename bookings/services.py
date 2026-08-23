from django.db import IntegrityError, transaction

from bookings.models import Booking


class SlotAlreadyBookedError(Exception):
    """Raised when create_booking's (tenant, scheduled_start) slot is already
    taken by a confirmed booking."""


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
        raise SlotAlreadyBookedError(
            f"Slot {slot.start} is already booked for tenant {tenant.id}"
        ) from exc
