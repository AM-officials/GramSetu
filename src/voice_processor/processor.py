"""
GramSetu — Voice Message Processor

This module implements the Voice_Processor component from requirements.md §Req-1.
It is a *mock* implementation that simulates AWS Transcribe behaviour via
URL-pattern inspection — no real AWS credentials or network calls are made.

When AWS keys are active, replace `_call_transcribe()` with a real boto3
`TranscribeService.start_transcription_job()` call; the public interface
(`process_audio`) and all Pydantic result types remain unchanged.

Supported languages (AWS Transcribe BCP-47 codes):
  hi-IN  Hindi         (batch + streaming)
  bn-IN  Bengali       (batch)
  or-IN  Odia / Oriya  (batch)
  gu-IN  Gujarati      (batch)
  mr-IN  Marathi       (batch)
  en-IN  English India (batch + streaming)

Refs: design.md §"Voice Message Processor Lambda", requirements.md §Req-1
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from src.shared.types import SupportedLanguage


# ═══════════════════════════════════════════════════════════════════
# Result models — Python equivalents of the TypeScript interfaces
# in design.md §"Voice Message Processor Lambda"
# ═══════════════════════════════════════════════════════════════════


class QualityAssessment(BaseModel):
    """Audio quality evaluation returned by the pre-flight check."""
    is_poor_quality: bool = False
    has_background_noise: bool = False
    is_too_short: bool = False
    recommended_actions: List[str] = Field(default_factory=list)


class LanguageDetection(BaseModel):
    """Language identification result for the audio clip."""
    detected_language: Optional[SupportedLanguage] = None
    raw_detected_code: str = ""   # BCP-47 code even when unsupported (e.g. "ta-IN")
    confidence: float = 0.0
    is_supported: bool = True


class TranscriptionResult(BaseModel):
    """
    Full output of VoiceProcessor.process_audio().

    On success  : needs_retry=False, text is populated, confidence >= 0.85
    On failure  : needs_retry=True,  retry_guidance explains what to do next
    """
    text: str
    language: str           # BCP-47 code, e.g. "hi-IN"
    confidence: float       # 0.0 – 1.0
    needs_retry: bool
    retry_guidance: Optional[str] = None
    quality_assessment: Optional[QualityAssessment] = None
    language_detection: Optional[LanguageDetection] = None


# ═══════════════════════════════════════════════════════════════════
# Mock data tables
# ═══════════════════════════════════════════════════════════════════

# Substrings in the audio URL that indicate language (case-insensitive)
_LANGUAGE_URL_HINTS: Dict[str, SupportedLanguage] = {
    "hindi":   SupportedLanguage.HINDI,
    "hi-in":   SupportedLanguage.HINDI,
    "odia":    SupportedLanguage.ODIA,
    "oriya":   SupportedLanguage.ODIA,
    "or-in":   SupportedLanguage.ODIA,
    "bengali": SupportedLanguage.BENGALI,
    "bn-in":   SupportedLanguage.BENGALI,
    "gujarati":SupportedLanguage.GUJARATI,
    "gu-in":   SupportedLanguage.GUJARATI,
    "marathi": SupportedLanguage.MARATHI,
    "mr-in":   SupportedLanguage.MARATHI,
    "english": SupportedLanguage.ENGLISH_INDIAN,
    "en-in":   SupportedLanguage.ENGLISH_INDIAN,
}

# Substrings that indicate an *unsupported* language
_UNSUPPORTED_LANGUAGE_HINTS = frozenset({
    "tamil", "ta-in",
    "telugu", "te-in",
    "kannada", "kn-in",
    "punjabi", "pa-in",
    "malayalam", "ml-in",
    "urdu", "ur-in",
})

# Guidance messages (bilingual English + Hindi for accessibility)
_POOR_QUALITY_GUIDANCE = (
    "Your voice note was unclear. Please try again:\n"
    "  • Find a quieter place away from background noise.\n"
    "  • Hold your phone closer to your mouth.\n"
    "  • Speak slowly and clearly.\n\n"
    "आपकी आवाज़ स्पष्ट नहीं थी। कृपया दोबारा भेजें:\n"
    "  • शोर से दूर, शांत जगह पर जाएँ।\n"
    "  • फ़ोन को मुँह के पास रखें।\n"
    "  • धीरे और स्पष्ट रूप से बोलें।"
)

_UNSUPPORTED_LANGUAGE_GUIDANCE = (
    "Sorry, GramSetu currently supports these languages:\n"
    "  • Hindi (हिंदी)\n"
    "  • Odia (ଓଡ଼ିଆ)\n"
    "  • Bengali (বাংলা)\n"
    "  • Gujarati (ગુજરાતી)\n"
    "  • Marathi (मराठी)\n"
    "  • English\n\n"
    "Please send your voice note in one of these languages, or type your message.\n\n"
    "माफ़ करें, GramSetu अभी इन भाषाओं में काम करता है: "
    "हिंदी, ओड़िया, बंगाली, गुजराती, मराठी, अंग्रेज़ी।"
)


# ═══════════════════════════════════════════════════════════════════
# VoiceProcessor
# ═══════════════════════════════════════════════════════════════════


class VoiceProcessor:
    """
    Mock implementation of the Voice Message Processor Lambda.

    Public API
    ──────────
    process_audio(audio_url, user_id="") → TranscriptionResult

    Internal pipeline (all private, replaces real AWS calls):
    1. _validate_audio_quality  — detects poor-quality signal
    2. _detect_language         — identifies language from URL hints
    3. _call_transcribe         — returns a mocked transcription string

    Swap-in path for production
    ───────────────────────────
    When AWS Transcribe is available, replace `_call_transcribe()` body with:
      client = boto3.client("transcribe", region_name=os.getenv("AWS_REGION"))
      # ... start_transcription_job(), poll for completion, parse result
    Everything else (quality check, language detect, result shaping) stays the same.
    """

    # ── Internal helpers ──────────────────────────────────────────

    def _validate_audio_quality(self, audio_url: str) -> QualityAssessment:
        """
        Inspect the audio URL for quality signal keywords.

        Real implementation: call AWS Transcribe's confidence score on a
        short pre-flight segment, or use a custom noise-detection Lambda.
        """
        url_lower = audio_url.lower()

        if "poor_quality" in url_lower or "noisy" in url_lower:
            return QualityAssessment(
                is_poor_quality=True,
                has_background_noise="noisy" in url_lower,
                recommended_actions=[
                    "Find a quieter location",
                    "Hold phone closer to mouth",
                    "Speak slowly and clearly",
                ],
            )

        if "short" in url_lower:
            return QualityAssessment(
                is_too_short=True,
                recommended_actions=["Send a longer voice note with more details"],
            )

        return QualityAssessment()

    def _detect_language(self, audio_url: str) -> LanguageDetection:
        """
        Identify the spoken language from URL hints.

        Real implementation: use AWS Transcribe's automatic language
        identification (IdentifyLanguage=True) on the audio file in S3.
        """
        url_lower = audio_url.lower()

        # Check for explicitly unsupported language markers first
        for hint in _UNSUPPORTED_LANGUAGE_HINTS:
            if hint in url_lower:
                raw_code = hint if "-in" in hint else f"{hint[:2]}-IN"
                return LanguageDetection(
                    detected_language=None,
                    raw_detected_code=raw_code,
                    confidence=0.92,
                    is_supported=False,
                )

        # Check for supported language markers
        for hint, language in _LANGUAGE_URL_HINTS.items():
            if hint in url_lower:
                return LanguageDetection(
                    detected_language=language,
                    raw_detected_code=language.value,
                    confidence=0.95,
                    is_supported=True,
                )

        # Default: Hindi (most common for rural India)
        return LanguageDetection(
            detected_language=SupportedLanguage.HINDI,
            raw_detected_code=SupportedLanguage.HINDI.value,
            confidence=0.80,
            is_supported=True,
        )

    # ── Public API ────────────────────────────────────────────────

    def process_audio(self, audio_url: str, user_id: str = "") -> TranscriptionResult:
        """
        Full voice processing pipeline: quality check → language detect → transcribe.

        Parameters
        ──────────
        audio_url : URL (S3 or local) pointing to the audio file.
                    In this mock, URL substrings drive the response:
                      'poor_quality' → quality error (Req 1.3)
                      'tamil' / 'telugu' / 'kannada' etc. → unsupported lang (Req 1.4)
                      'odia' / 'hindi' / 'bengali' etc. → matching language transcript
                      anything else → Hindi transcript by default
        user_id   : Phone number of the requesting user (for logging / audit).
                    Reserved for the real AWS integration path.

        Returns
        ───────
        TranscriptionResult — always returned; inspect `needs_retry` first.
        """

        # Step 1 — Audio quality gate
        quality = self._validate_audio_quality(audio_url)
        if quality.is_poor_quality or quality.is_too_short:
            return TranscriptionResult(
                text="",
                language="",
                confidence=0.0,
                needs_retry=True,
                retry_guidance=_POOR_QUALITY_GUIDANCE,
                quality_assessment=quality,
            )

        # Step 2 — Language identification
        lang_detection = self._detect_language(audio_url)
        if not lang_detection.is_supported:
            return TranscriptionResult(
                text="",
                language=lang_detection.raw_detected_code,
                confidence=0.0,
                needs_retry=True,
                retry_guidance=_UNSUPPORTED_LANGUAGE_GUIDANCE,
                language_detection=lang_detection,
            )

        # Step 3 — Transcription is handled natively by Gemini via invoke_audio_gemini.
        # This method now serves as a quality/language pre-flight check only.
        return TranscriptionResult(
            text="",
            language=lang_detection.detected_language.value if lang_detection.detected_language else "",
            confidence=1.0,
            needs_retry=False,
            quality_assessment=quality,
            language_detection=lang_detection,
        )


# ─────────────────────────────────────────────────────────────────
# AWS Lambda entry point
# ─────────────────────────────────────────────────────────────────

_processor = VoiceProcessor()


def handler(event: dict, context: object) -> dict:
    """
    Lambda handler invoked asynchronously by WebhookHandler.

    Expected event shape:
      {
        "audio_url": "s3://gramsetu-media-<account>-<env>/incoming/<phone>/<id>.ogg",
        "user_id":   "+919876543210"
      }

    Returns a JSON-serialisable dict of TranscriptionResult fields.
    The AI Reasoner Lambda is invoked next with this result by the
    WebhookHandler orchestrator.
    """
    audio_url = event.get("audio_url", "")
    user_id = event.get("user_id", "")
    result = _processor.process_audio(audio_url=audio_url, user_id=user_id)
    return result.model_dump()
