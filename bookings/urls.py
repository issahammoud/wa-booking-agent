from django.urls import path

from bookings.views import DashboardHomeView

urlpatterns = [
    path("", DashboardHomeView.as_view(), name="dashboard-home"),
]
