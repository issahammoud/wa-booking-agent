from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from core.views import health_check

urlpatterns = [
    path("health/", health_check, name="health-check"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
]
