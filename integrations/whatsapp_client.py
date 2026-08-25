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
