from django.urls import path

from integrations.calendar_oauth import (
    google_callback,
    google_connect,
    outlook_callback,
    outlook_connect,
)
from integrations.views import IntegrationsView, whatsapp_webhook

urlpatterns = [
    path("webhook/whatsapp/", whatsapp_webhook, name="whatsapp-webhook"),
    path("dashboard/integrations/", IntegrationsView.as_view(), name="integrations"),
    path("dashboard/integrations/google/connect/", google_connect, name="calendar-google-connect"),
    path(
        "dashboard/integrations/google/callback/", google_callback, name="calendar-google-callback"
    ),
    path(
        "dashboard/integrations/outlook/connect/", outlook_connect, name="calendar-outlook-connect"
    ),
    path(
        "dashboard/integrations/outlook/callback/",
        outlook_callback,
        name="calendar-outlook-callback",
    ),
]
