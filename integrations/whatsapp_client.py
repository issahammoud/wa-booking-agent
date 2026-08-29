import logging

import requests

logger = logging.getLogger(__name__)

WHATSAPP_API_VERSION = "v21.0"


def send_text_message(tenant, to_phone_number, text):
    """POST a text message via the WhatsApp Cloud API.

    Returns the parsed JSON response on success, or None on failure - never
    raises, so a WhatsApp API outage can't crash the caller.

    NOTE: tenant.whatsapp_access_token is currently stored as plain bytes
    (no encryption implemented yet - see Tenant model docs).
    """
    access_token = tenant.whatsapp_access_token
    if isinstance(access_token, bytes | memoryview):
        access_token = bytes(access_token).decode()

    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{tenant.phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {access_token}"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone_number,
        "type": "text",
        "text": {"body": text},
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
    except requests.RequestException:
        logger.exception(
            "Failed to send WhatsApp message to %s for tenant=%s", to_phone_number, tenant.id
        )
        return None
    return response.json()


def download_media(tenant, media_id):
    """Download a media attachment (e.g. a voice note) from the WhatsApp
    Cloud API. Two-step Graph API flow: resolve the media id to a short-
    lived signed URL, then fetch that URL with the same bearer token.

    Returns the raw bytes on success, or None on failure - never raises.
    """
    access_token = tenant.whatsapp_access_token
    if isinstance(access_token, bytes | memoryview):
        access_token = bytes(access_token).decode()
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        meta_response = requests.get(
            f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{media_id}",
            headers=headers,
            timeout=10,
        )
        meta_response.raise_for_status()
        media_url = meta_response.json()["url"]

        content_response = requests.get(media_url, headers=headers, timeout=10)
        content_response.raise_for_status()
    except (requests.RequestException, KeyError):
        logger.exception("Failed to download media id=%s for tenant=%s", media_id, tenant.id)
        return None
    return content_response.content
