"""
GramSetu — Voice Processor Tests

Validates all edge cases mandated by requirements.md §Req-1:
  Req 1.1 — Successful transcription returned for clean audio
  Req 1.3 — poor_quality URL → retry requested with guidance
  Req 1.4 — Unsupported language URL → retry with supported-language list
  Req 1.5 — All 5+ regional languages handled (Hindi, Odia, Bengali, Gujarati, Marathi)
"""
import pytest

from src.shared.types import SupportedLanguage
from src.voice_processor.processor import TranscriptionResult, VoiceProcessor

SUPPORTED_LANGUAGE_CODES = {lang.value for lang in SupportedLanguage}

@pytest.fixture(scope="module")
def processor() -> VoiceProcessor:
    return VoiceProcessor()


# ─────────────────────────────────────────────────────────────────
# 1. TestQualityErrors  (Req 1.3)
# ─────────────────────────────────────────────────────────────────

class TestQualityErrors:
    def test_poor_quality_url_triggers_retry(self, processor):
        """'poor_quality' in URL must force needs_retry=True. (Req 1.3)"""
        result = processor.process_audio("s3://bucket/audio/poor_quality_sample.ogg")
        assert result.needs_retry is True

    def test_poor_quality_text_is_empty(self, processor):
        """No text should be returned when audio is unusable."""
        result = processor.process_audio("https://cdn.example.com/poor_quality.ogg")
        assert result.text == ""

    def test_poor_quality_has_retry_guidance(self, processor):
        """retry_guidance must be a non-empty string. (Req 1.3)"""
        result = processor.process_audio("s3://bucket/poor_quality.ogg")
        assert result.retry_guidance is not None
        assert len(result.retry_guidance) > 0

    def test_poor_quality_guidance_mentions_quiet(self, processor):
        """Guidance must tell user to find a quieter location (design.md empathy rule)."""
        result = processor.process_audio("uploads/poor_quality_voice.ogg")
        guidance = result.retry_guidance.lower()
        assert "quiet" in guidance

    def test_poor_quality_confidence_is_zero(self, processor):
        """Confidence must be 0.0 when transcription is rejected."""
        result = processor.process_audio("test/poor_quality.ogg")
        assert result.confidence == 0.0

    def test_poor_quality_quality_assessment_attached(self, processor):
        """QualityAssessment must be populated so callers can inspect the reason."""
        result = processor.process_audio("test/poor_quality.ogg")
        assert result.quality_assessment is not None
        assert result.quality_assessment.is_poor_quality is True


# ─────────────────────────────────────────────────────────────────
# 2. TestUnsupportedLanguage  (Req 1.4)
# ─────────────────────────────────────────────────────────────────

class TestUnsupportedLanguage:
    def test_tamil_is_unsupported(self, processor):
        """Tamil is not in the supported set — needs_retry must be True. (Req 1.4)"""
        result = processor.process_audio("s3://bucket/audio/tamil_voice.ogg")
        assert result.needs_retry is True

    def test_telugu_is_unsupported(self, processor):
        """Telugu is not in the supported set — needs_retry must be True. (Req 1.4)"""
        result = processor.process_audio("uploads/telugu_user_audio.ogg")
        assert result.needs_retry is True

    def test_kannada_is_unsupported(self, processor):
        """Kannada is not in the supported set — needs_retry must be True."""
        result = processor.process_audio("uploads/kannada_audio.ogg")
        assert result.needs_retry is True

    def test_unsupported_guidance_mentions_hindi(self, processor):
        """Guidance must include Hindi in the list of supported languages. (Req 1.4)"""
        result = processor.process_audio("uploads/tamil_audio.ogg")
        assert "Hindi" in result.retry_guidance or "हिंदी" in result.retry_guidance

    def test_unsupported_guidance_mentions_odia(self, processor):
        """Guidance must include Odia in the list of supported languages."""
        result = processor.process_audio("uploads/tamil_audio.ogg")
        assert "Odia" in result.retry_guidance or "ଓଡ଼ିଆ" in result.retry_guidance

    def test_unsupported_language_text_is_empty(self, processor):
        """No transcript is returned when language is unsupported."""
        result = processor.process_audio("uploads/tamil_audio.ogg")
        assert result.text == ""


# ─────────────────────────────────────────────────────────────────
# 3. TestSuccessfulTranscription  (Req 1.1, 1.5)
# ─────────────────────────────────────────────────────────────────

class TestSuccessfulTranscription:
    def test_default_returns_hindi(self, processor):
        """With no language hint, Hindi is the default. (Req 1.5 — Hindi required)"""
        result = processor.process_audio("s3://bucket/audio/voice_001.ogg")
        assert result.language == SupportedLanguage.HINDI.value
        assert result.needs_retry is False

    def test_hindi_url_hint(self, processor):
        """'hindi' in URL → language=hi-IN. (Req 1.5)"""
        result = processor.process_audio("uploads/hindi_voice_message.ogg")
        assert result.language == SupportedLanguage.HINDI.value

    def test_odia_url_hint(self, processor):
        """'odia' in URL → language=or-IN. (Req 1.5 — Odia required)"""
        result = processor.process_audio("uploads/odia_voice_message.ogg")
        assert result.language == SupportedLanguage.ODIA.value

    def test_bengali_url_hint(self, processor):
        """'bengali' in URL → language=bn-IN. (Req 1.5)"""
        result = processor.process_audio("uploads/bengali_voice.ogg")
        assert result.language == SupportedLanguage.BENGALI.value

    def test_gujarati_url_hint(self, processor):
        """'gujarati' in URL → language=gu-IN. (Req 1.5)"""
        result = processor.process_audio("uploads/gujarati_voice.ogg")
        assert result.language == SupportedLanguage.GUJARATI.value

    def test_marathi_url_hint(self, processor):
        """'marathi' in URL → language=mr-IN. (Req 1.5)"""
        result = processor.process_audio("uploads/marathi_voice.ogg")
        assert result.language == SupportedLanguage.MARATHI.value

    def test_success_needs_retry_false(self, processor):
        """Successful result must have needs_retry=False. (Req 1.1)"""
        result = processor.process_audio("s3://bucket/audio/clean_hindi.ogg")
        assert result.needs_retry is False

    def test_confidence_above_threshold(self, processor):
        """Mocked confidence must be >= 0.85 to represent a high-quality result."""
        result = processor.process_audio("s3://bucket/audio/voice.ogg")
        assert result.confidence >= 0.85

    def test_confidence_in_valid_range(self, processor):
        """Confidence must always be within [0.0, 1.0]."""
        result = processor.process_audio("s3://bucket/audio/voice.ogg")
        assert 0.0 <= result.confidence <= 1.0

    def test_language_is_in_supported_set(self, processor):
        """Returned language code must be one of the 6 supported BCP-47 codes."""
        result = processor.process_audio("s3://bucket/audio/voice.ogg")
        assert result.language in SUPPORTED_LANGUAGE_CODES

    def test_transcribed_text_is_nonempty(self, processor):
        """Successful transcription must return non-empty text. (Req 1.1)"""
        result = processor.process_audio("s3://bucket/audio/voice.ogg")
        assert len(result.text.strip()) > 0

    def test_retry_guidance_is_none_on_success(self, processor):
        """retry_guidance must be None when transcription succeeds."""
        result = processor.process_audio("s3://bucket/audio/voice.ogg")
        assert result.retry_guidance is None


# ─────────────────────────────────────────────────────────────────
# 4. TestEdgeCases
# ─────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_poor_quality_overrides_language_hint(self, processor):
        """
        Quality errors must be caught before language detection.
        A URL with both 'poor_quality' and 'odia' must return a quality error,
        not an Odia transcript.
        """
        result = processor.process_audio("uploads/odia_poor_quality_voice.ogg")
        assert result.needs_retry is True
        assert result.quality_assessment is not None
        assert result.quality_assessment.is_poor_quality is True

    def test_user_id_parameter_accepted(self, processor):
        """process_audio must accept an optional user_id without error."""
        result = processor.process_audio(
            audio_url="s3://bucket/audio/voice.ogg",
            user_id="919876543210",
        )
        assert isinstance(result, TranscriptionResult)

    def test_oriya_alias_maps_to_odia(self, processor):
        """'oriya' (older spelling) must map to the same or-IN language code."""
        result = processor.process_audio("uploads/oriya_voice.ogg")
        assert result.language == SupportedLanguage.ODIA.value
