from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.views.generic import ListView

from bookings.models import Booking
from core.mixins import TenantScopedMixin


class DashboardHomeView(LoginRequiredMixin, TenantScopedMixin, ListView):
    """Staff dashboard landing page: each tenant's upcoming confirmed bookings."""

    model = Booking
    context_object_name = "bookings"
    template_name = "bookings/dashboard_home.html"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(status=Booking.Status.CONFIRMED, scheduled_start__gte=timezone.now())
            .order_by("scheduled_start")
        )
