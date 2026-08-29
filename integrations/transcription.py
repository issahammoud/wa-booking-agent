import base64
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

OPENROUTER_TRANSCRIPTION_URL = "https://openrouter.ai/api/v1/audio/transcriptions"


def transcribe_audio(audio_bytes):
    """Transcribe voice-note bytes via OpenRouter's unified transcription
    endpoint (same API key as the chat agent). WhatsApp voice notes are
    OGG/Opus.

    Returns the transcript text, or None on failure - never raises.
    """
    payload = {
        "model": settings.TRANSCRIPTION_MODEL,
        "input_audio": {
            "data": base64.b64encode(audio_bytes).decode(),
            "format": "ogg",
        },
    }
    headers = {"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"}

    try:
        response = requests.post(
            OPENROUTER_TRANSCRIPTION_URL, headers=headers, json=payload, timeout=30
        )
        response.raise_for_status()
        return response.json()["text"]
    except (requests.RequestException, KeyError, ValueError):
        logger.exception("Audio transcription failed")
        return None
