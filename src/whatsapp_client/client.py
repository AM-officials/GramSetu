"""
GramSetu — WhatsApp Client

Sends and receives media via the Meta WhatsApp Cloud API (Graph API v18.0).

Public API
──────────
send_whatsapp_message(to_number: str, message_text: str) -> dict
    Send a text message to a WhatsApp number.

download_whatsapp_media(media_id: str) -> str
    Download a WhatsApp media file to a local temp_media/ folder.
    Returns the local file path, or "" on failure (never raises).

Environment variables (loaded from .env via python-dotenv):
  WHATSAPP_API_TOKEN      : Bearer token from Meta Developer Console
  WHATSAPP_PHONE_NUMBER_ID: WhatsApp Business Account phone number ID

Meta Cloud API reference:
  POST https://graph.facebook.com/v18.0/{phone-number-id}/messages
  GET  https://graph.facebook.com/v18.0/{media-id}   → media URL
  GET  <media-url>                                    → binary bytes
"""
from __future__ import annotations

import logging
import os
import pathlib
from typing import Any, Dict

import httpx
from dotenv import load_dotenv

# Load .env on import — safe to call multiple times (idempotent)
load_dotenv()

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────

GRAPH_API_VERSION = "v18.0"
GRAPH_API_BASE = "https://graph.facebook.com"

# Timeouts
_REQUEST_TIMEOUT_SECONDS = 10.0
_MEDIA_DOWNLOAD_TIMEOUT  = 30.0    # Binary downloads can be several MB

# Local staging folder for temporary downloaded media files
_TEMP_MEDIA_DIR = pathlib.Path("/tmp/temp_media")

# WhatsApp mime type → file extension
_MIME_TO_EXT: Dict[str, str] = {
    "audio/ogg": ".ogg",
    "audio/ogg; codecs=opus": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/wav": ".wav",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
    "video/mp4": ".mp4",
}



# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────

def send_whatsapp_message(to_number: str, message_text: str) -> Dict[str, Any]:
    """
    Send a text message to a WhatsApp number via the Meta Cloud API.

    Parameters
    ──────────
    to_number    : Recipient's phone number in E.164 format, e.g. "919876543210"
                   (with or without leading "+"; Meta accepts both).
    message_text : Plain-text body of the message (≤ 4096 characters).

    Returns
    ───────
    dict with:
      {"success": True,  "message_id": str, "status_code": int}   on success
      {"success": False, "error": str,      "status_code": int}    on HTTP error
      {"success": False, "error": str,      "status_code": None}   on network/env error

    Never raises an exception — all errors are captured and returned.
    """
    # ── 1. Read credentials from environment ─────────────────────
    access_token = os.getenv("WHATSAPP_API_TOKEN")
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

    if not access_token:
        msg = "WHATSAPP_API_TOKEN is not set. Cannot send WhatsApp message."
        logger.error(msg)
        return {"success": False, "error": msg, "status_code": None}

    if not phone_number_id:
        msg = "WHATSAPP_PHONE_NUMBER_ID is not set. Cannot send WhatsApp message."
        logger.error(msg)
        return {"success": False, "error": msg, "status_code": None}

    # ── 2. Build request ──────────────────────────────────────────
    url = f"{GRAPH_API_BASE}/{GRAPH_API_VERSION}/{phone_number_id}/messages"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number.replace("+", ""),
        "type": "text",
        "text": {
            "preview_url": False,
            "body": message_text,
        },
    }

    # ── 3. Make the HTTP request ──────────────────────────────────
    try:
        response = httpx.post(
            url,
            headers=headers,
            json=payload,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as exc:
        msg = f"WhatsApp API request timed out after {_REQUEST_TIMEOUT_SECONDS}s: {exc}"
        logger.error(msg)
        return {"success": False, "error": msg, "status_code": None}
    except httpx.ConnectError as exc:
        msg = f"WhatsApp API network connection error: {exc}"
        logger.error(msg)
        return {"success": False, "error": msg, "status_code": None}
    except httpx.HTTPError as exc:
        msg = f"WhatsApp API HTTP error: {exc}"
        logger.error(msg)
        return {"success": False, "error": msg, "status_code": None}
    except Exception as exc:  # noqa: BLE001 — safety net, never crash the webhook
        msg = f"Unexpected error sending WhatsApp message: {exc}"
        logger.exception(msg)
        return {"success": False, "error": msg, "status_code": None}

    # ── 4. Parse response ─────────────────────────────────────────
    status_code = response.status_code

    if status_code not in (200, 201):
        error_detail = _extract_error(response)
        msg = f"WhatsApp API returned HTTP {status_code}: {error_detail}"
        logger.error(msg)
        return {"success": False, "error": msg, "status_code": status_code}

    # Success — extract the message ID from Meta's response
    try:
        body = response.json()
        message_id = body.get("messages", [{}])[0].get("id", "unknown")
    except Exception:
        message_id = "unknown"

    logger.info("WhatsApp message sent → %s  id=%s", to_number, message_id)
    return {"success": True, "message_id": message_id, "status_code": status_code}


# ─────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────

def _extract_error(response: httpx.Response) -> str:
    """
    Pull a human-readable error string from a Meta Graph API error response.

    Meta error shape:
      {"error": {"message": "...", "type": "...", "code": 190, ...}}
    """
    try:
        body = response.json()
        error_obj = body.get("error", {})
        return (
            f"[code={error_obj.get('code', '?')}] "
            f"{error_obj.get('message', response.text[:200])}"
        )
    except Exception:
        return response.text[:200]


# ─────────────────────────────────────────────────────────────────
# Media download
# ─────────────────────────────────────────────────────────────────

def download_whatsapp_media(media_id: str) -> str:
    """
    Download a WhatsApp media file from Meta's CDN to a local temp_media/ folder.

    Two-step Meta Cloud API flow:
      1. GET /v18.0/{media_id}          → JSON: {"url": "...", "mime_type": "...", ...}
      2. GET <url>  (Bearer token)      → binary file bytes

    Parameters
    ──────────
    media_id : The WhatsApp media ID from the incoming message object.

    Returns
    ───────
    str  : Absolute or relative path to the saved temp file on success.
    ""   : Empty string on any failure (missing token, network error, HTTP error, etc.).

    Never raises — all errors are caught and logged.
    """
    access_token = os.getenv("WHATSAPP_API_TOKEN")
    if not access_token:
        logger.error("WHATSAPP_API_TOKEN not set — cannot download media id=%s", media_id)
        return ""

    headers = {"Authorization": f"Bearer {access_token}"}

    # ── Step 1: Resolve media metadata (URL + mime_type) ─────────
    metadata_url = f"{GRAPH_API_BASE}/{GRAPH_API_VERSION}/{media_id}"
    try:
        meta_resp = httpx.get(
            metadata_url, headers=headers, timeout=_REQUEST_TIMEOUT_SECONDS
        )
    except Exception as exc:
        logger.error("Failed to fetch media metadata for id=%s: %s", media_id, exc)
        return ""

    if meta_resp.status_code != 200:
        logger.error(
            "Media metadata request failed: HTTP %s for id=%s",
            meta_resp.status_code, media_id,
        )
        return ""

    try:
        meta = meta_resp.json()
        media_url  = meta["url"]
        mime_type  = meta.get("mime_type", "application/octet-stream")
    except (KeyError, ValueError) as exc:
        logger.error("Could not parse media metadata for id=%s: %s", media_id, exc)
        return ""

    # ── Step 2: Download the binary ───────────────────────────────
    try:
        dl_resp = httpx.get(
            media_url, headers=headers, timeout=_MEDIA_DOWNLOAD_TIMEOUT, follow_redirects=True
        )
    except Exception as exc:
        logger.error("Failed to download media url=%s: %s", media_url, exc)
        return ""

    if dl_resp.status_code != 200:
        logger.error(
            "Media download returned HTTP %s for id=%s", dl_resp.status_code, media_id
        )
        return ""

    # ── Step 3: Save to temp_media/ ──────────────────────────────
    ext = _MIME_TO_EXT.get(mime_type.split(";")[0].strip(), ".bin")
    _TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    local_path = _TEMP_MEDIA_DIR / f"{media_id}{ext}"

    try:
        local_path.write_bytes(dl_resp.content)
    except OSError as exc:
        logger.error("Could not write media to %s: %s", local_path, exc)
        return ""

    logger.info("Media downloaded: id=%s → %s (%d bytes)", media_id, local_path, len(dl_resp.content))
    return str(local_path)

