from django.urls import path

from integrations.views import IntegrationsView, whatsapp_webhook

urlpatterns = [
    path("webhook/whatsapp/", whatsapp_webhook, name="whatsapp-webhook"),
    path("dashboard/integrations/", IntegrationsView.as_view(), name="integrations"),
]
