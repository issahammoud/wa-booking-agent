import datetime
import logging
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.signing import BadSignature, SignatureExpired, dumps, loads
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from bookings.calendar.google import AUTHORIZE_URL as GOOGLE_AUTHORIZE_URL
from bookings.calendar.google import OAUTH_SCOPE as GOOGLE_SCOPE
from bookings.calendar.google import TOKEN_URL as GOOGLE_TOKEN_URL
from bookings.calendar.outlook import AUTHORIZE_URL as MICROSOFT_AUTHORIZE_URL
from bookings.calendar.outlook import OAUTH_SCOPE as MICROSOFT_SCOPE
from bookings.calendar.outlook import TOKEN_URL as MICROSOFT_TOKEN_URL
from integrations.models import CalendarConnection

logger = logging.getLogger(__name__)

STATE_SALT = "calendar-oauth"
STATE_MAX_AGE = 600  # seconds - long enough for a real consent flow, no longer


def _require_tenant(request):
    return getattr(request.user, "tenant", None)


def _make_state(tenant_id):
    return dumps({"tenant_id": tenant_id}, salt=STATE_SALT)


def _read_tenant_id(state):
    if not state:
        return None
    try:
        data = loads(state, salt=STATE_SALT, max_age=STATE_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    return data.get("tenant_id")


def _store_connection(tenant_id, provider, token_response):
    expires_at = timezone.now() + datetime.timedelta(seconds=token_response["expires_in"])
    CalendarConnection.objects.update_or_create(
        tenant_id=tenant_id,
        defaults={
            "provider": provider,
            "external_calendar_id": "primary",
            "access_token": token_response["access_token"].encode(),
            "refresh_token": token_response.get("refresh_token", "").encode(),
            "token_expires_at": expires_at,
            "scopes": token_response.get("scope", "").split(),
        },
    )


@login_required
def google_connect(request):
    tenant = _require_tenant(request)
    if tenant is None:
        return HttpResponseForbidden("Only tenant staff can connect a calendar.")

    redirect_uri = request.build_absolute_uri(reverse("calendar-google-callback"))
    params = {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": _make_state(tenant.id),
    }
    return redirect(f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}")


@login_required
def google_callback(request):
    tenant_id = _read_tenant_id(request.GET.get("state"))
    if tenant_id is None:
        return HttpResponseBadRequest("Invalid or expired OAuth state.")
    code = request.GET.get("code")
    if not code:
        return HttpResponseBadRequest("Missing authorization code.")

    redirect_uri = request.build_absolute_uri(reverse("calendar-google-callback"))
    response = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=10,
    )
    response.raise_for_status()
    _store_connection(tenant_id, "google", response.json())
    return redirect("integrations")


@login_required
def outlook_connect(request):
    tenant = _require_tenant(request)
    if tenant is None:
        return HttpResponseForbidden("Only tenant staff can connect a calendar.")

    redirect_uri = request.build_absolute_uri(reverse("calendar-outlook-callback"))
    params = {
        "client_id": settings.MICROSOFT_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": MICROSOFT_SCOPE,
        "state": _make_state(tenant.id),
    }
    return redirect(f"{MICROSOFT_AUTHORIZE_URL}?{urlencode(params)}")


@login_required
def outlook_callback(request):
    tenant_id = _read_tenant_id(request.GET.get("state"))
    if tenant_id is None:
        return HttpResponseBadRequest("Invalid or expired OAuth state.")
    code = request.GET.get("code")
    if not code:
        return HttpResponseBadRequest("Missing authorization code.")

    redirect_uri = request.build_absolute_uri(reverse("calendar-outlook-callback"))
    response = requests.post(
        MICROSOFT_TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.MICROSOFT_OAUTH_CLIENT_ID,
            "client_secret": settings.MICROSOFT_OAUTH_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "scope": MICROSOFT_SCOPE,
        },
        timeout=10,
    )
    response.raise_for_status()
    _store_connection(tenant_id, "outlook", response.json())
    return redirect("integrations")
