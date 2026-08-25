from dataclasses import dataclass
from datetime import datetime, timedelta

from django.utils import timezone

SLOT_DURATION_MINUTES = 30


@dataclass
class TimeSlot:
    start: datetime
    end: datetime


def check_availability(tenant, date_range=None):
    """STUB: returns 3 hardcoded future slots regardless of input.

    Real calendar-based computation replaces this in a later phase.
    """
    base = timezone.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return [
        TimeSlot(
            start=base + timedelta(days=offset),
            end=base + timedelta(days=offset, minutes=SLOT_DURATION_MINUTES),
        )
        for offset in range(3)
    ]
