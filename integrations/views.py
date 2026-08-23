import hashlib
import hmac

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whatsapp_webhook(request):
    if request.method == "GET":
        return _handle_verification(request)
    return _handle_incoming(request)


def _handle_verification(request):
    if (
        request.GET.get("hub.mode") == "subscribe"
        and request.GET.get("hub.verify_token") == settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN
    ):
        return HttpResponse(request.GET.get("hub.challenge", ""), content_type="text/plain")
    return HttpResponse(status=403)


def _handle_incoming(request):
    if not _has_valid_signature(request):
        return HttpResponse(status=403)
    # Payload parsing and persistence land in later commits.
    return HttpResponse(status=200)


def _has_valid_signature(request):
    signature_header = request.headers.get("X-Hub-Signature-256", "")
    if not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        settings.WHATSAPP_APP_SECRET.encode(), request.body, hashlib.sha256
    ).hexdigest()
    provided = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)
