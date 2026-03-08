"""
GramSetu — AI Reasoner: Google Gemini Multimodal Client

Uses google-generativeai + PIL to pass document images directly to Gemini Flash
for universal document classification, OCR extraction, identity verification,
and eligibility analysis in a single multimodal call.

Public API
──────────
invoke_claude(system_prompt, user_input, image_path=None, registered_name=None) → dict
    Drop-in replacement — identical signature to prior Bedrock/NVIDIA clients
    (with added registered_name for identity verification).

Environment variable
────────────────────
GEMINI_API_KEY (required) — Google AI Studio / Gemini API key

Refs: design.md §4.1, requirements.md §Req-3
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

import google.generativeai as genai
from PIL import Image

from src.ai_reasoner.prompts import AVAILABLE_YOJNAS

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# Client initialisation (module-level, re-used across warm invocations)
# ─────────────────────────────────────────────────────────────────

_MODEL_NAME = "gemini-3.1-flash-lite-preview"   # switched from gemini-2.5-flash to avoid quota limits

def _get_model() -> genai.GenerativeModel:
    """Configure the Gemini client and return a GenerativeModel instance."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise KeyError("GEMINI_API_KEY environment variable is not set.")
    genai.configure(api_key=api_key)
    model_name = os.getenv("GEMINI_MODEL", _MODEL_NAME)
    return genai.GenerativeModel(model_name)


# ─────────────────────────────────────────────────────────────────
# Response parsing
# ─────────────────────────────────────────────────────────────────

def _parse_response(raw_text: str) -> Dict[str, Any]:
    """
    Safely parse Gemini's output into a Python dict.
    Strips optional ```json ... ``` markdown fences before json.loads().
    On failure returns {"error": "JSON parse failed", "raw": <text>}.
    """
    cleaned = raw_text.strip()
    # Strip any ```json or ``` markdown formatting Gemini may wrap the response in
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        # Remove first line (```json) and last line (```)
        if len(lines) >= 2:
            # Find the closing ``` — it may not be the very last line
            end_idx = len(lines) - 1
            while end_idx > 0 and not lines[end_idx].strip().startswith("```"):
                end_idx -= 1
            cleaned = "\n".join(lines[1:end_idx]).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning(
            "Gemini returned non-JSON output — returning raw text.\n%.500s", raw_text
        )
        return {"error": "JSON parse failed", "raw": raw_text}


# ─────────────────────────────────────────────────────────────────
# Prompt construction
# ─────────────────────────────────────────────────────────────────

def _build_classifier_prompt(
    system_prompt: str,
    registered_name: Optional[str] = None,
    previous_context: Optional[dict] = None,
) -> str:
    """
    Build a universal document classifier + extractor prompt for Gemini.

    Instructs Gemini to:
    1. Identify the document type (aadhaar, income_certificate, land_record, or unknown)
    2. Extract relevant fields from the document
    3. Verify identity against a registered name (if provided)
    4. Determine eligibility for government schemes
    5. Generate a user-friendly WhatsApp message
    """
    identity_context = ""
    if registered_name:
        identity_context = (
            f"\n## IDENTITY VERIFICATION CONTEXT\n"
            f"The user's registered Aadhaar name is: \"{registered_name}\"\n"
            f"Compare the name on this document against the registered name above.\n"
            f"If the names do NOT match, set identity_verification.confidence_score to \"Low\" "
            f"and note the mismatch in the user_friendly_message.\n"
            f"If names match (allowing for minor transliteration differences), "
            f"set confidence_score to \"High\".\n"
        )

    session_context = ""
    if previous_context:
        import json as _json
        session_context = (
            f"\n## PREVIOUS SESSION DATA\n"
            f"The user has already provided the following information in this session. "
            f"DO NOT ask the user for documents they have already provided below. "
            f"Use these values (especially their Aadhaar name) to cross-verify the new document.\n"
            f"```json\n{_json.dumps(previous_context, ensure_ascii=False, indent=2)}\n```\n"
        )

    return (
        f"You are GramSetu, a universal document classifier and data extractor for Indian "
        f"government documents. You help rural Indian citizens apply for government schemes.\n\n"
        f"## TASK\n"
        f"Analyze the provided document image. Classify its type, extract all relevant data, "
        f"verify identity, determine scheme eligibility, and compose a helpful reply message.\n\n"
        f"## AVAILABLE GOVERNMENT SCHEMES\n{AVAILABLE_YOJNAS}\n"
        f"{identity_context}\n"
        f"{session_context}"
        f"## ADDITIONAL CONTEXT\n{system_prompt}\n\n"
        f"## STRICT OUTPUT FORMAT\n"
        f"You MUST return ONLY a valid JSON object with this EXACT schema. "
        f"Do NOT wrap it in markdown code fences. Do NOT add any text before or after the JSON.\n\n"
        f'{{\n'
        f'  "document_type": "aadhaar | income_certificate | land_record | bank_passbook | caste_certificate | ration_card | crop_certificate | unknown",\n'
        f'  "extracted_data": {{\n'
        f'    "name": "Full name as printed on document",\n'
        f'    "father_name": "Father\'s name if present, else null",\n'
        f'    "dob": "Date of birth if present, else null",\n'
        f'    "gender": "Gender if present, else null",\n'
        f'    "address": "Full address if present, else null",\n'
        f'    "aadhaar_number_masked": "XXXX XXXX last4 if Aadhaar, else null",\n'
        f'    "annual_income_inr": "Annual income as integer if income cert, else null",\n'
        f'    "issuing_authority": "Authority name if present, else null",\n'
        f'    "certificate_number": "Certificate/document number if present, else null",\n'
        f'    "land_area": "Land area if land record, else null",\n'
        f'    "land_type": "Agricultural/Residential etc if land record, else null",\n'
        f'    "district": "District name if present, else null",\n'
        f'    "state": "State name if present, else null",\n'
        f'    "account_number": "Bank account number if bank passbook, else null",\n'
        f'    "ifsc_code": "IFSC code if bank passbook, else null",\n'
        f'    "caste_category": "SC/ST/OBC if caste certificate, else null",\n'
        f'    "head_of_household": "Head of household name if ration card, else null",\n'
        f'    "family_members_count": "Number of family members if ration card, else null"\n'
        f'  }},\n'
        f'  "identity_verification": {{\n'
        f'    "extracted_name": "Name as read from the document",\n'
        f'    "confidence_score": "High | Low"\n'
        f'  }},\n'
        f'  "eligibility_summary": {{\n'
        f'    "is_eligible": true,\n'
        f'    "reason": "Brief explanation of eligibility determination"\n'
        f'  }},\n'
        f'  "user_friendly_message": "A helpful 1-2 sentence bilingual message (English + Hindi) for the WhatsApp user explaining what was extracted and what to do next."\n'
        f'}}\n\n'
        f"## RULES\n"
        f"- For document_type, choose ONLY from: aadhaar, income_certificate, land_record, bank_passbook, caste_certificate, ration_card, crop_certificate, unknown\n"
        f"- If you cannot identify the document, set document_type to \"unknown\"\n"
        f"- For bank_passbook: extract account_number and ifsc_code\n"
        f"- For caste_certificate: extract caste_category (must be one of: SC, ST, OBC)\n"
        f"- For ration_card: extract head_of_household (name of the primary cardholder) and family_members_count (integer)\n"
        f"- Set extracted_data fields to null if not found on the document\n"
        f"- For eligibility_summary.is_eligible, use true/false/null (null if insufficient data)\n"
        f"- The user_friendly_message MUST be bilingual (English + Hindi)\n"
        f"- NEVER fabricate data — extract only what is visible on the document\n"
    )


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────

def invoke_claude(
    system_prompt: str,
    user_input: str,
    image_path: Optional[str] = None,
    registered_name: Optional[str] = None,
    previous_context: Optional[dict] = None,
) -> Dict[str, Any]:
    """
    Call Google Gemini (multimodal) and return a parsed JSON dict.

    The function name is kept as `invoke_claude` for drop-in compatibility
    with all existing call sites in router.py and the Lambda handler.

    Parameters
    ──────────
    system_prompt    : GramSetu system prompt (used as context in the prompt text).
    user_input       : Raw text from the user (transcription or typed message).
    image_path       : Optional absolute path to a document image under /tmp/.
                       If provided, PIL opens the image and passes it to Gemini
                       alongside the prompt for multimodal OCR extraction.
    registered_name  : Optional name from user's Aadhaar card, used for identity
                       verification against subsequent documents.
    previous_context : Optional dict of extracted fields accumulated across the
                       user's current 15-minute session. Prevents Gemini from
                       asking for documents that were already uploaded.

    Returns
    ───────
    dict — Gemini's JSON response parsed into a Python dict.
    Expected keys: document_type, extracted_data, identity_verification,
                   eligibility_summary, user_friendly_message.
    On API / key error  : {"error": "<message>", "raw": ""}
    On JSON parse fail  : {"error": "JSON parse failed", "raw": "<raw text>"}
    """
    try:
        model = _get_model()
    except KeyError as exc:
        logger.error(str(exc))
        return {"error": str(exc), "raw": ""}

    # ── Build the prompt ───────────────────────────────────────────
    prompt = _build_classifier_prompt(
        system_prompt=system_prompt,
        registered_name=registered_name,
        previous_context=previous_context,
    )

    # ── Assemble content parts ─────────────────────────────────────
    parts: list = [prompt]

    if image_path:
        try:
            img = Image.open(image_path)
            parts.append(img)
        except (OSError, FileNotFoundError) as exc:
            logger.warning("Could not open image at %s: %s — proceeding text-only.", image_path, exc)

    # Append any extra user text if provided
    if user_input and user_input.strip():
        parts.append(user_input)

    # ── Call Gemini ────────────────────────────────────────────────
    try:
        response = model.generate_content(parts)
        raw_text: str = response.text or ""
        logger.info("Gemini responded (%d chars).", len(raw_text))
        return _parse_response(raw_text)

    except Exception as exc:  # noqa: BLE001 — safety net; Gemini SDK raises various types
        msg = f"Gemini API error: {exc}"
        logger.exception(msg)
        return {"error": msg, "raw": ""}


# ─────────────────────────────────────────────────────────────────
# Conversational API — text intent & native audio handling
# ─────────────────────────────────────────────────────────────────

def _build_conversational_prompt(
    user_text: str,
    previous_context: Optional[dict] = None,
    is_audio: bool = False,
) -> str:
    """
    Build a conversational intent-handling prompt for text or audio inputs.

    Unlike _build_classifier_prompt (document OCR), this prompt guides the user
    through the scheme application journey, checking session context to avoid
    asking for documents they have already provided.
    """
    session_block = ""
    if previous_context:
        session_block = (
            f"\n## DOCUMENTS ALREADY COLLECTED IN THIS SESSION\n"
            f"```json\n{json.dumps(previous_context, ensure_ascii=False, indent=2)}\n```\n"
            f"DO NOT ask the user for any document listed above.\n"
        )

    input_mode = "voice note (audio file attached)" if is_audio else "text message"
    transcribe_instruction = "Transcribe the audio accurately, then understand" if is_audio else "Understand"

    user_text_block = f"## USER TEXT\n{user_text}\n" if user_text else ""

    return (
        f"You are GramSetu, a friendly WhatsApp assistant helping rural Indian citizens "
        f"apply for government welfare schemes: PM-KISAN, PMAY, MGNREGA, PM Jan Dhan, and Ayushman Bharat.\n\n"
        f"## YOUR TASK\n"
        f"The user has sent a {input_mode}. {transcribe_instruction} their intent and guide them "
        f"to the next step in their application.\n\n"
        f"## BEHAVIOUR RULES\n"
        f"1. If the user states intent to apply for a scheme (e.g. 'I want to apply for PM-Kisan', "
        f"'Ayushman Bharat ke liye apply karna hai'), acknowledge it warmly.\n"
        f"2. Check DOCUMENTS ALREADY COLLECTED. Ask ONLY for the next missing document in this order:\n"
        f"   Aadhaar Card → Income Certificate → Land Record.\n"
        f"3. If asked a general question about a scheme, answer briefly then offer to start the application.\n"
        f"4. NEVER ask for a document that already appears in the session data.\n"
        f"5. All replies MUST be bilingual (English + Hindi) and concise for WhatsApp.\n"
        f"6. If intent is unclear, ask one simple clarifying question.\n"
        f"7. SUBMISSION TRIGGER: If the user explicitly says they want to proceed or submit "
        f"(e.g. 'let\'s apply', 'proceed', 'apply now', 'submit', 'yes', 'aage badho', 'apply karo') AND the session "
        f"already contains an Aadhaar name (field 'name' is present), set "
        f"submission_intent.status to 'READY_FOR_SUBMISSION' and populate scheme_name with the "
        f"scheme they are applying for. Otherwise leave status as null.\n"
        f"{session_block}\n"
        f"{user_text_block}\n"
        f"## OUTPUT FORMAT\n"
        f"Return ONLY a valid JSON object. Do NOT use markdown code fences.\n"
        f'{{\n'
        f'  "reply": "Your bilingual WhatsApp reply for the user",\n'
        f'  "transcription": "Verbatim transcription if audio, otherwise null",\n'
        f'  "detected_intent": "apply_scheme | question | greeting | proceed | other",\n'
        f'  "session_update": {{\n'
        f'    "stated_scheme": "pm_kisan | ayushman_bharat | pmay | mgnrega | jan_dhan | null"\n'
        f'  }},\n'
        f'  "submission_intent": {{\n'
        f'    "status": "READY_FOR_SUBMISSION | null",\n'
        f'    "scheme_name": "Human-readable scheme name, e.g. Ayushman Bharat, or null"\n'
        f'  }}\n'
        f'}}\n'
    )


def invoke_conversational(
    user_text: str,
    previous_context: Optional[dict] = None,
) -> Dict[str, Any]:
    """
    Call Gemini for a text-based conversational interaction.

    Designed for messages where the user states an intent, asks a question,
    or continues a scheme application. Uses session context to avoid re-asking
    for documents already provided.

    Returns
    ───────
    dict: reply, transcription (null), detected_intent, session_update.
    On error: {"error": "<message>", "raw": ""}
    """
    try:
        model = _get_model()
    except KeyError as exc:
        logger.error(str(exc))
        return {"error": str(exc), "raw": ""}

    prompt = _build_conversational_prompt(
        user_text=user_text,
        previous_context=previous_context,
        is_audio=False,
    )
    try:
        response = model.generate_content([prompt])
        raw_text: str = response.text or ""
        logger.info("Gemini conversational responded (%d chars).", len(raw_text))
        return _parse_response(raw_text)
    except Exception as exc:  # noqa: BLE001
        msg = f"Gemini conversational API error: {exc}"
        logger.exception(msg)
        return {"error": msg, "raw": ""}


def invoke_audio_gemini(
    audio_path: str,
    previous_context: Optional[dict] = None,
) -> Dict[str, Any]:
    """
    Pass an audio file directly to Gemini for transcription + intent extraction.

    Uses the Gemini File API (genai.upload_file) so audio is processed natively —
    no separate transcription service needed. The uploaded file is deleted
    immediately after generation; it auto-expires after 48 h if deletion fails.

    Returns
    ───────
    dict: reply, transcription, detected_intent, session_update.
    On error: {"error": "<message>", "raw": ""}
    """
    import pathlib

    try:
        model = _get_model()
    except KeyError as exc:
        logger.error(str(exc))
        return {"error": str(exc), "raw": ""}

    _AUDIO_MIME_MAP = {
        ".ogg":  "audio/ogg",
        ".opus": "audio/ogg",
        ".mp3":  "audio/mpeg",
        ".wav":  "audio/wav",
        ".m4a":  "audio/mp4",
        ".aac":  "audio/aac",
        ".flac": "audio/flac",
    }
    ext = pathlib.Path(audio_path).suffix.lower()
    mime_type = _AUDIO_MIME_MAP.get(ext, "audio/ogg")

    prompt = _build_conversational_prompt(
        user_text="",
        previous_context=previous_context,
        is_audio=True,
    )

    uploaded_file = None
    try:
        uploaded_file = genai.upload_file(path=audio_path, mime_type=mime_type)
        response = model.generate_content([prompt, uploaded_file])
        raw_text: str = response.text or ""
        logger.info("Gemini audio responded (%d chars).", len(raw_text))
        return _parse_response(raw_text)
    except Exception as exc:  # noqa: BLE001
        msg = f"Gemini audio API error: {exc}"
        logger.exception(msg)
        return {"error": msg, "raw": ""}
    finally:
        if uploaded_file:
            try:
                genai.delete_file(uploaded_file.name)
            except Exception:  # noqa: BLE001
                pass  # Non-critical; file auto-expires after 48 h
