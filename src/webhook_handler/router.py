"""
GramSetu — Webhook Handler: Route Definitions

Routes:
  GET  /webhook  — WhatsApp hub challenge verification
  POST /webhook  — Incoming message intake + full event-driven media routing (Req 5.1, 5.2)

Message routing:
  text   → bilingual welcome reply (Req 5.1)
  audio  → VoiceProcessor → AIReasoner → reply (Req 5.2)
  image  → DocumentProcessor → AIReasoner → reply (Req 5.2)
"""
import os
import random
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from src.webhook_handler.models import WhatsAppWebhookPayload
from src.whatsapp_client.client import download_whatsapp_media, send_whatsapp_message
from src.document_processor.processor import DocumentProcessor
from src.ai_reasoner.prompts import build_system_prompt
from src.ai_reasoner.client import invoke_claude, invoke_conversational, invoke_audio_gemini
from src.shared.session_manager import get_session, save_to_session, clear_session
from src.shared.types import ConversationStep

router = APIRouter()
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# In-memory user name registry (per-Lambda warm start)
# Maps phone_number -> registered Aadhaar name for identity verification.
# Superseded by DynamoDB session; kept as a warm-start cache.
# ──────────────────────────────────────────────────────────────────
_USER_NAMES: dict[str, str] = {}

# Single-word / very-short greetings that should return the welcome message
# rather than entering the AI conversational pipeline.
_GREETING_WORDS = frozenset({
    "hi", "hello", "hey", "start", "begin", "help", "menu",
    "नमस्ते", "हेलो", "हाय", "शुरू", "स्टार्ट", "मदद",
})

# IST = UTC+5:30
IST = timezone(timedelta(hours=5, minutes=30))

SEPARATOR = "─" * 55

# ──────────────────────────────────────────────────────────────────
# Outbound message templates (Req 5.1)
# ──────────────────────────────────────────────────────────────────

WELCOME_MESSAGE = (
    "🌱 Welcome to GramSetu!\n"
    "ग्रामसेतु में आपका स्वागत है! 🌱\n\n"
    "I can help you apply for government schemes like "
    "PM-KISAN, PMAY, MGNREGA, and PM Jan Dhan — "
    "right here on WhatsApp, in your language.\n\n"
    "मैं WhatsApp पर आपकी भाषा में सरकारी योजनाओं "
    "(पीएम-किसान, पीएमएवाई, मनरेगा, जन धन) के लिए "
    "आवेदन करने में मदद कर सकता हूँ।\n\n"
    "Please send a voice note or document photo to begin.\n"
    "शुरू करने के लिए एक वॉयस नोट या दस्तावेज़ की फ़ोटो भेजें।"
)

DOWNLOAD_FAILED_MESSAGE = (
    "⚠️ Sorry, I couldn't download your media file. Please try again.\n"
    "माफ़ करें, मैं आपकी मीडिया फ़ाइल डाउनलोड नहीं कर सका। कृपया पुनः प्रयास करें।"
)

PROCESSING_ERROR_MESSAGE = (
    "⚠️ Something went wrong while processing your message. Please try again.\n"
    "कुछ गड़बड़ हो गई। कृपया पुनः प्रयास करें।"
)

IDENTITY_MISMATCH_MESSAGE = (
    "⚠️ The name on this document does not match your registered Aadhaar name. "
    "Please upload a document in your own name to proceed.\n"
    "⚠️ इस दस्तावेज़ पर नाम आपके आधार नाम से मेल नहीं खाता। "
    "कृपया अपने नाम का दस्तावेज़ अपलोड करें।"
)

UNKNOWN_DOCUMENT_MESSAGE = (
    "❓ I couldn't identify this document. GramSetu currently supports:\n"
    "  • Aadhaar Card\n"
    "  • Income Certificate\n"
    "  • Land Record\n\n"
    "Please send a clear photo of one of these documents.\n"
    "❓ मैं इस दस्तावेज़ को पहचान नहीं सका। कृपया इनमें से किसी की स्पष्ट फ़ोटो भेजें:\n"
    "  • आधार कार्ड\n"
    "  • आय प्रमाण पत्र\n"
    "  • भूमि रिकॉर्ड"
)

# Field-ID to human-readable label mappings (for reply formatting)
_FIELD_LABELS = {
    "form_field_applicant_name_01":  ("Name", "नाम"),
    "form_field_applicant_age_01":   ("Age", "उम्र"),
    "form_field_annual_income_01":   ("Annual Income", "वार्षिक आय"),
    "form_field_aadhaar_number_01":  ("Aadhaar No.", "आधार नं."),
    "form_field_land_area_01":       ("Land Area", "भूमि क्षेत्र"),
    "form_field_bank_account_01":    ("Bank A/C", "बैंक खाता"),
}

_NEXT_DOC_PROMPT = (
    "\n\nNow please send a clear photo of your Aadhaar card. 📄\n"
    "अब कृपया अपने आधार कार्ड की स्पष्ट फ़ोटो भेजें। 📄"
)


# ──────────────────────────────────────────────────────────────────
# Private utilities
# ──────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────────
# Scheme display-name normalisation
# ──────────────────────────────────────────────────────────────────────────────
_SCHEME_DISPLAY_NAMES: dict[str, str] = {
    "pm_kisan":        "PM-KISAN Samman Nidhi",
    "ayushman_bharat": "Ayushman Bharat (PM-JAY)",
    "pmay":            "Pradhan Mantri Awas Yojana (PMAY)",
    "mgnrega":         "MGNREGA",
    "jan_dhan":        "PM Jan Dhan Yojana",
}


def _handle_submission(from_number: str, scheme_name: str, session: dict) -> None:
    """
    Simulate final application submission:
      1. Generate a mock reference number.
      2. Clear the user's DynamoDB session so they can start fresh.
      3. Send a celebratory confirmation message.
    """
    ref_number = f"GS-2026-{random.randint(100000, 999999)}"

    applicant_name = (
        session.get("name")
        or session.get("applicant_name")
        or "Applicant"
    )

    confirmation = (
        f"\U0001f389 Application Successfully Submitted! \U0001f389\n\n"
        f"Your details have been verified and forwarded to the local office.\n\n"
        f"\U0001f4c4 Applicant: {applicant_name}\n"
        f"\U0001f522 Reference Number: {ref_number}\n\n"
        f"You will receive an SMS from the portal soon."
    )

    clear_session(from_number)
    print(f"[GramSetu] Submission simulated for +{from_number}: ref={ref_number}")
    send_whatsapp_message(from_number, confirmation)


def _handle_text_message(msg) -> None:
    """
    Text message handler:
      - Short greetings → WELCOME_MESSAGE
      - All other text  → AI conversational pipeline with DynamoDB session context
    """
    from_number = msg.from_
    body = (msg.text.body if msg.text else "").strip()

    # STOP command: clear session immediately and halt further processing
    if body.upper() == "STOP":
        clear_session(from_number)
        send_whatsapp_message(
            from_number,
            "\U0001f6a8 Session Cleared. All previous context and documents have been deleted. "
            "You can start a fresh application now."
        )
        print(f"[GramSetu] STOP received — session cleared for +{from_number}")
        return

    # Greeting detection: single-word or short greeting phrase
    if body.lower().rstrip("!").strip() in _GREETING_WORDS:
        result = send_whatsapp_message(from_number, WELCOME_MESSAGE)
        if result["success"]:
            print(f"[GramSetu] Welcome reply sent → +{from_number}")
        else:
            print(f"[GramSetu] WARNING: Could not send welcome reply → +{from_number}: {result.get('error')}")
        return

    # Conversational AI pipeline
    session = get_session(from_number)
    if session:
        print(f"[GramSetu] Session restored for +{from_number} ({len(session)} fields).")

    try:
        ai_response = invoke_conversational(
            user_text=body,
            previous_context=session if session else None,
        )

        if ai_response.get("error"):
            logger.error("Conversational AI error: %s", ai_response.get("error"))
            send_whatsapp_message(from_number, PROCESSING_ERROR_MESSAGE)
            return

        # Check for submission trigger BEFORE saving session (clear_session is called inside)
        submission = ai_response.get("submission_intent") or {}
        if submission.get("status") == "READY_FOR_SUBMISSION":
            scheme_name = (
                submission.get("scheme_name")
                or _SCHEME_DISPLAY_NAMES.get(
                    (session.get("stated_scheme") or "").lower(), "Government Scheme"
                )
            )
            _handle_submission(from_number, scheme_name, session)
            return

        # Persist any stated intent (e.g. the scheme the user wants to apply for)
        session_update = ai_response.get("session_update") or {}
        if session_update:
            save_to_session(from_number, session_update)
            print(f"[GramSetu] Session updated (text) for +{from_number}: {list(session_update.keys())}")

        reply = ai_response.get("reply") or PROCESSING_ERROR_MESSAGE
        send_whatsapp_message(from_number, reply)
        print(f"[GramSetu] Conversational reply sent → +{from_number}")

    except Exception as exc:
        print(f"[GramSetu] ERROR in text pipeline for +{from_number}: {exc}")
        send_whatsapp_message(from_number, PROCESSING_ERROR_MESSAGE)

def _format_timestamp(ts: str) -> str:
    """Convert Unix timestamp string to a human-readable IST string."""
    try:
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(IST)
        return dt.strftime("%Y-%m-%d %H:%M:%S IST")
    except (ValueError, OSError):
        return ts


def _get_content_preview(msg) -> str:
    """Return a readable one-liner describing the message content."""
    match msg.type:
        case "text":
            body = msg.text.body if msg.text else "(empty)"
            return f'"{body}"'
        case "audio":
            media_id = msg.audio.id if msg.audio else "unknown"
            mime = msg.audio.mime_type if msg.audio else "unknown"
            return f"[voice note] id={media_id}  mime={mime}"
        case "image":
            media_id = msg.image.id if msg.image else "unknown"
            caption = f'  caption="{msg.image.caption}"' if msg.image and msg.image.caption else ""
            return f"[image] id={media_id}{caption}"
        case "document":
            media_id = msg.document.id if msg.document else "unknown"
            fname = f'  filename="{msg.document.filename}"' if msg.document and msg.document.filename else ""
            return f"[document] id={media_id}{fname}"
        case _:
            return f"[{msg.type}] (unsupported — inspect raw payload)"


def _print_message(msg, contacts: list | None) -> None:
    """Pretty-print a received WhatsApp message to stdout."""
    contact_name = "Unknown"
    if contacts:
        for c in contacts:
            if c.wa_id == msg.from_:
                contact_name = c.profile.name
                break

    print(SEPARATOR)
    print("[GramSetu] Incoming WhatsApp Message")
    print(f"  From     : +{msg.from_} ({contact_name})")
    print(f"  Type     : {msg.type}")
    print(f"  Content  : {_get_content_preview(msg)}")
    print(f"  Msg ID   : {msg.id}")
    print(f"  Time     : {_format_timestamp(msg.timestamp)}")
    print(SEPARATOR)


def _cleanup_file(path: str) -> None:
    """Delete a temp file, logging a warning if it fails."""
    if not path:
        return
    import pathlib
    p = pathlib.Path(path)
    if p.exists():
        try:
            p.unlink()
            print(f"[GramSetu] Temp file cleaned up: {path}")
        except OSError as exc:
            print(f"[GramSetu] WARNING: Could not delete temp file {path}: {exc}")


def _format_extracted_fields(extracted: dict) -> str:
    """
    Build a human-readable summary of AI-extracted form fields.
    Returns EN+HI lines for each found field.
    """
    lines = []
    for field_id, (en_label, hi_label) in _FIELD_LABELS.items():
        val = extracted.get(field_id)
        if val is not None:
            lines.append(f"  • {en_label} / {hi_label}: {val}")
    return "\n".join(lines) if lines else "  (no fields extracted)"


def _build_audio_reply(transcription_text: str, extracted: dict) -> str:
    """
    Build the WhatsApp reply for a successfully processed voice note.
    Shows a snippet of the transcript, the extracted fields, and the next prompt.
    """
    excerpt = transcription_text[:120].strip()
    if len(transcription_text) > 120:
        excerpt += "…"

    fields_summary = _format_extracted_fields(extracted)
    needs_followup = extracted.get("needs_followup", [])

    reply = (
        f"🎙️ Received your voice message!\n"
        f"आपका वॉयस संदेश मिल गया!\n\n"
        f"I heard: \"{excerpt}\"\n\n"
        f"📋 Details found:\n{fields_summary}\n"
    )

    if needs_followup:
        reply += _NEXT_DOC_PROMPT
    else:
        reply += (
            "\n\n✅ All details collected!"
            "\nसभी विवरण मिल गए!"
            "\n\nPlease send your Aadhaar card photo. 📄"
            "\nकृपया अपना आधार कार्ड फ़ोटो भेजें। 📄"
        )
    return reply


def _build_document_reply(doc_type: str, extracted: dict) -> str:
    """
    Build the WhatsApp reply for a successfully processed document image.
    Uses the AI-generated user_friendly_message when available,
    otherwise falls back to a generic summary.
    """
    # Prefer the AI-generated bilingual message
    ai_message = extracted.get("user_friendly_message")
    if ai_message and isinstance(ai_message, str) and ai_message.strip():
        return ai_message

    # Fallback: build from extracted fields
    fields_summary = _format_extracted_fields(extracted)
    doc_label = doc_type.replace("_", " ").title()

    reply = (
        f"📄 Document received: {doc_label}\n"
        f"दस्तावेज़ मिला: {doc_label}\n\n"
        f"📋 Details found:\n{fields_summary}\n"
        f"\n\nGreat! Now please send your income or land record document."
        f"\nशानदार! अब कृपया अपना आय या भूमि रिकॉर्ड दस्तावेज़ भेजें।"
    )
    return reply


# ──────────────────────────────────────────────────────────────────
# Req 5.2: Media message handlers
# ──────────────────────────────────────────────────────────────────

def _handle_audio_message(msg) -> None:
    """
    Voice note processing pipeline (Gemini-native audio):
      download → get_session → invoke_audio_gemini → save_to_session → reply → cleanup

    The audio file is passed directly to the Gemini multimodal model, which
    transcribes it, extracts the user's intent, cross-references the DynamoDB
    session context, and returns a contextual bilingual reply.
    """
    from_number = msg.from_
    media_id    = msg.audio.id if msg.audio else ""

    print(f"[GramSetu] Processing audio: id={media_id} from={from_number}")

    local_path = download_whatsapp_media(media_id)
    if not local_path:
        print(f"[GramSetu] Audio download failed for id={media_id}")
        send_whatsapp_message(from_number, DOWNLOAD_FAILED_MESSAGE)
        return

    try:
        # ── Load session context ───────────────────────────────────
        session = get_session(from_number)
        if session:
            print(f"[GramSetu] Session restored for +{from_number} ({len(session)} fields).")

        # ── Gemini native audio transcription + intent handling ────
        ai_response = invoke_audio_gemini(
            audio_path=local_path,
            previous_context=session if session else None,
        )

        if ai_response.get("error"):
            logger.error("Audio AI error: %s", ai_response.get("error"))
            send_whatsapp_message(from_number, PROCESSING_ERROR_MESSAGE)
            return

        # ── Persist intent and transcription to session ────────────
        session_update = ai_response.get("session_update") or {}
        transcription = ai_response.get("transcription")
        if transcription and isinstance(transcription, str):
            session_update["last_transcription"] = transcription
        if session_update:
            save_to_session(from_number, session_update)
            print(f"[GramSetu] Session updated (audio) for +{from_number}: {list(session_update.keys())}")

        reply = ai_response.get("reply") or PROCESSING_ERROR_MESSAGE
        send_whatsapp_message(from_number, reply)
        print(f"[GramSetu] Audio reply sent → +{from_number}")

    except Exception as exc:
        print(f"[GramSetu] ERROR in audio pipeline for id={media_id}: {exc}")
        send_whatsapp_message(from_number, PROCESSING_ERROR_MESSAGE)

    finally:
        _cleanup_file(local_path)


def _handle_document_message(msg) -> None:
    """
    Document / image processing pipeline:
      download → DocumentProcessor (quality check) → AIReasoner (classify + extract)
      → identity verification → WhatsApp reply → cleanup
    Handles both 'image' (photos) and 'document' (PDF/files) message types.
    """
    from_number = msg.from_
    # Resolve media_id from whichever sub-object is present
    if msg.image:
        media_id = msg.image.id
    elif msg.document:
        media_id = msg.document.id
    else:
        media_id = ""

    print(f"[GramSetu] Processing image: id={media_id} from={from_number}")

    # ── Load session — accumulated data from previous documents ───
    session = get_session(from_number)
    if session:
        print(f"[GramSetu] Session restored for +{from_number} ({len(session)} fields).")

    local_path = download_whatsapp_media(media_id)
    if not local_path:
        print(f"[GramSetu] Image download failed for id={media_id}")
        send_whatsapp_message(from_number, DOWNLOAD_FAILED_MESSAGE)
        return

    # ── Immediate acknowledgement — user sees this while AI processes ─
    send_whatsapp_message(
        from_number,
        "🖼️ Document received! Please wait a moment while GramSetu analyzes the information...",
    )

    try:
        # ── DocumentProcessor — image quality gate only ───────────
        dp     = DocumentProcessor()
        result = dp.process_document(image_url=local_path, user_id=from_number)

        if not result.success:
            # Quality issue — guide the user to retake
            quality_errors = "\n".join(result.errors) if result.errors else ""
            reply = (
                f"📷 {quality_errors}\n\n"
                "Please send a clearer photo of your document.\n"
                "कृपया अपने दस्तावेज़ की स्पष्ट फ़ोटो भेजें।"
            )
            print(f"[GramSetu] Document extraction failed: {result.errors}")
            send_whatsapp_message(from_number, reply)
            return

        # ── AIReasoner — universal classifier + extractor ─────────
        system_prompt = build_system_prompt(
            user_language="hi-IN",
            current_step=ConversationStep.COLLECTING_DOCUMENTS,
            target_scheme="pm-kisan",
        )
        # Prefer the session-backed name over the in-memory fallback
        registered_name = session.get("name") or _USER_NAMES.get(from_number)
        extracted = invoke_claude(
            system_prompt=system_prompt,
            user_input=str(result.extracted_data or {}),
            image_path=local_path,
            registered_name=registered_name,
            previous_context=session if session else None,
        )

        # ── Handle AI errors ──────────────────────────────────────
        if extracted.get("error"):
            logger.error("AI extraction error: %s", extracted.get("error"))
            send_whatsapp_message(from_number, PROCESSING_ERROR_MESSAGE)
            return

        # ── Dynamic document type from AI response ────────────────
        doc_type = extracted.get("document_type", "unknown")
        print(f"[GramSetu] Doc extraction OK: type={doc_type}")

        # ── Handle unknown document type ──────────────────────────
        if doc_type == "unknown":
            print(f"[GramSetu] Unknown document type from={from_number}")
            send_whatsapp_message(from_number, UNKNOWN_DOCUMENT_MESSAGE)
            return

        # ── Identity verification & Aadhaar name storage ──────────
        identity_info = extracted.get("identity_verification", {})
        extracted_name = identity_info.get("extracted_name", "")

        if doc_type == "aadhaar" and extracted_name:
            # Store the Aadhaar name for future identity checks (in-memory + session)
            _USER_NAMES[from_number] = extracted_name
            print(f"[GramSetu] Stored Aadhaar name for +{from_number}: {extracted_name}")

        elif registered_name and extracted_name:
            # Check for identity mismatch on non-Aadhaar documents
            confidence = identity_info.get("confidence_score", "High")
            if confidence == "Low":
                print(
                    f"[GramSetu] Identity mismatch: registered='{registered_name}' "
                    f"vs document='{extracted_name}'"
                )
                send_whatsapp_message(from_number, IDENTITY_MISMATCH_MESSAGE)
                return

        # ── Persist extracted data to session ─────────────────────
        extracted_fields = extracted.get("extracted_data") or {}
        if extracted_fields:
            save_to_session(from_number, extracted_fields)
            print(f"[GramSetu] Session updated for +{from_number}: {list(extracted_fields.keys())}")

        # ── Send AI-generated reply ───────────────────────────────
        reply = _build_document_reply(doc_type, extracted)
        send_whatsapp_message(from_number, reply)

    except Exception as exc:
        print(f"[GramSetu] ERROR in document pipeline for id={media_id}: {exc}")
        send_whatsapp_message(from_number, PROCESSING_ERROR_MESSAGE)

    finally:
        _cleanup_file(local_path)


# ---------------------------------------------------------------------------
# GET /webhook  — Hub challenge verification
# ---------------------------------------------------------------------------

@router.get(
    "/webhook",
    response_class=PlainTextResponse,
    summary="WhatsApp Webhook Verification",
    description=(
        "WhatsApp calls this endpoint with a challenge string when you register or refresh a webhook. "
        "We verify the token from the WHATSAPP_VERIFY_TOKEN env var and echo back the challenge."
    ),
)
async def verify_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
) -> PlainTextResponse:
    expected_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "gramsetu_dev")

    if hub_mode == "subscribe" and hub_verify_token == expected_token:
        print(f"[GramSetu] Webhook verified successfully (challenge={hub_challenge})")
        return PlainTextResponse(content=hub_challenge or "", status_code=200)

    print(
        f"[GramSetu] Webhook verification FAILED "
        f"(mode={hub_mode!r}, token={hub_verify_token!r})"
    )
    raise HTTPException(status_code=403, detail="Webhook verification failed")


# ---------------------------------------------------------------------------
# POST /webhook  — Incoming messages
# ---------------------------------------------------------------------------

@router.post(
    "/webhook",
    summary="Receive WhatsApp Messages",
    description=(
        "WhatsApp POSTs all incoming messages, delivery receipts, and read receipts here. "
        "Routes text → welcome, audio → VoiceProcessor, image → DocumentProcessor."
    ),
)
async def receive_webhook(payload: WhatsAppWebhookPayload) -> dict:
    if payload.object != "whatsapp_business_account":
        print(f"[GramSetu] Received non-WA object type: {payload.object!r} — skipping.")
        return {"status": "ok"}

    message_count = 0

    for entry in payload.entry:
        for change in entry.changes:
            if change.field != "messages":
                continue

            value    = change.value
            messages = value.messages or []
            contacts = value.contacts or []

            for msg in messages:
                _print_message(msg, contacts)
                message_count += 1

                # ── text → greeting or conversational AI ─────────
                if msg.type == "text":
                    _handle_text_message(msg)

                # ── Req 5.2: audio → VoiceProcessor pipeline ──────
                elif msg.type == "audio":
                    _handle_audio_message(msg)

                # ── Req 5.2: image / document → DocumentProcessor pipeline ───
                elif msg.type in ("image", "document"):
                    _handle_document_message(msg)

                # ── Unhandled types (video, sticker, etc.) ────────
                else:
                    print(f"[GramSetu] Unhandled message type: {msg.type!r} — skipping.")

    if message_count == 0:
        print("[GramSetu] Received status update (no new messages)")

    return {"status": "ok"}
