from django.urls import path

from integrations.views import whatsapp_webhook

urlpatterns = [
    path("webhook/whatsapp/", whatsapp_webhook, name="whatsapp-webhook"),
]
