"""
Notas de voz: ElevenLabs (texto a voz) + subida del audio a Meta.

El audio se pide en OGG/Opus, que es el formato que WhatsApp muestra como
nota de voz. Se sube a la Cloud API de Meta (/media) y se devuelve el
media_id; n8n manda después el mensaje tipo "audio" con ese id.

Todo se configura con los ELEVENLABS_* y WHATSAPP_* de .env.example.
"""

import os
import re

import httpx

ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"
ELEVENLABS_MODEL = os.environ.get("ELEVENLABS_MODEL") or "eleven_flash_v2_5"
ELEVENLABS_OUTPUT_FORMAT = os.environ.get("ELEVENLABS_OUTPUT_FORMAT") or "opus_48000_64"
ELEVENLABS_LANGUAGE = os.environ.get("ELEVENLABS_LANGUAGE") or "es"
META_GRAPH_API_VERSION = os.environ.get("META_GRAPH_API_VERSION") or "v20.0"
TIMEOUT = 30.0

# Lo que no se puede leer en voz alta: emojis, markdown y links.
_EMOJI = re.compile(
    "[\U0001f000-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff️‍]"
)
_MARKDOWN = re.compile(r"[*_~`#>]")
_URL = re.compile(r"https?://\S+|www\.\S+")
_SPACES = re.compile(r"[ \t]+")


def clean_for_speech(text: str) -> str:
    text = _URL.sub("el link que te dejo por escrito", text)
    text = _EMOJI.sub("", text)
    text = _MARKDOWN.sub("", text)
    text = text.replace("•", "")
    return _SPACES.sub(" ", text).strip()


def _mime_type() -> str:
    if ELEVENLABS_OUTPUT_FORMAT.startswith("opus"):
        return "audio/ogg"
    if ELEVENLABS_OUTPUT_FORMAT.startswith("mp3"):
        return "audio/mpeg"
    raise RuntimeError(f"ELEVENLABS_OUTPUT_FORMAT no soportado por WhatsApp: {ELEVENLABS_OUTPUT_FORMAT}")


def synthesize(text: str, voice_id: str | None = None) -> bytes:
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    voice_id = voice_id or os.environ.get("ELEVENLABS_VOICE_ID")
    if not api_key or not voice_id:
        raise RuntimeError("Faltan ELEVENLABS_API_KEY o ELEVENLABS_VOICE_ID")
    response = httpx.post(
        f"{ELEVENLABS_API_BASE}/text-to-speech/{voice_id}",
        params={"output_format": ELEVENLABS_OUTPUT_FORMAT},
        json={
            "text": text,
            "model_id": ELEVENLABS_MODEL,
            "language_code": ELEVENLABS_LANGUAGE,
        },
        headers={"xi-api-key": api_key},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.content


def upload_to_whatsapp(audio: bytes, phone_number_id: str | None = None) -> str:
    token = os.environ.get("WHATSAPP_ACCESS_TOKEN")
    phone_number_id = phone_number_id or os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
    if not token or not phone_number_id:
        raise RuntimeError("Faltan WHATSAPP_ACCESS_TOKEN o WHATSAPP_PHONE_NUMBER_ID")
    mime_type = _mime_type()
    extension = "ogg" if mime_type == "audio/ogg" else "mp3"
    response = httpx.post(
        f"https://graph.facebook.com/{META_GRAPH_API_VERSION}/{phone_number_id}/media",
        data={"messaging_product": "whatsapp", "type": mime_type},
        files={"file": (f"respuesta.{extension}", audio, mime_type)},
        headers={"Authorization": f"Bearer {token}"},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["id"]
