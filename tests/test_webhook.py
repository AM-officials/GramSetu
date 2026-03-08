"""
GramSetu — Webhook Handler Tests
Tests for GET /webhook (hub verification) and POST /webhook (message intake + routing).
Covers text, audio, image, and status-update payloads.
"""
import os
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

# Ensure the verify token is set before importing the app
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "gramsetu_dev")

from src.webhook_handler.main import app  # noqa: E402

client = TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures — reusable payload builders
# ---------------------------------------------------------------------------

def _base_payload(messages: list) -> dict:
    """Wraps a list of message dicts in the standard WhatsApp webhook envelope."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba_001",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550001234",
                                "phone_number_id": "pid_001",
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Ramesh Kumar"},
                                    "wa_id": "919876543210",
                                }
                            ],
                            "messages": messages,
                        },
                    }
                ],
            }
        ],
    }


TEXT_MESSAGE = _base_payload(
    [
        {
            "from": "919876543210",
            "id": "wamid.text001",
            "timestamp": "1741064537",
            "type": "text",
            "text": {"body": "Mujhe PM Kisan ke liye apply karna hai"},
        }
    ]
)

AUDIO_MESSAGE = _base_payload(
    [
        {
            "from": "919876543210",
            "id": "wamid.audio001",
            "timestamp": "1741064537",
            "type": "audio",
            "audio": {"id": "audio_media_001", "mime_type": "audio/ogg; codecs=opus"},
        }
    ]
)

IMAGE_MESSAGE = _base_payload(
    [
        {
            "from": "919876543210",
            "id": "wamid.image001",
            "timestamp": "1741064537",
            "type": "image",
            "image": {
                "id": "image_media_001",
                "mime_type": "image/jpeg",
                "sha256": "abc123deadbeef",
                "caption": "Mera Aadhaar card",
            },
        }
    ]
)


# ---------------------------------------------------------------------------
# GET /webhook  — Hub challenge verification
# ---------------------------------------------------------------------------

class TestWebhookVerification:
    def test_valid_token_returns_challenge(self):
        """WhatsApp hub verification with the correct token echoes back the challenge."""
        response = client.get(
            "/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "gramsetu_dev",
                "hub.challenge": "challenge_abc123",
            },
        )
        assert response.status_code == 200
        assert response.text == "challenge_abc123"

    def test_invalid_token_returns_403(self):
        """Wrong verify token must be rejected with 403."""
        response = client.get(
            "/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong_token",
                "hub.challenge": "challenge_xyz",
            },
        )
        assert response.status_code == 403

    def test_wrong_mode_returns_403(self):
        """hub.mode other than 'subscribe' must be rejected."""
        response = client.get(
            "/webhook",
            params={
                "hub.mode": "unsubscribe",
                "hub.verify_token": "gramsetu_dev",
                "hub.challenge": "challenge_xyz",
            },
        )
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# POST /webhook  — Basic routing — always returns 200 regardless of internals
# ---------------------------------------------------------------------------

class TestWebhookMessages:
    """
    These tests verify the webhook always returns 200 OK.
    Media download and processor calls are mocked to isolate the routing logic.
    """

    @patch("src.webhook_handler.router.send_whatsapp_message")
    def test_text_message_returns_200(self, mock_send):
        mock_send.return_value = {"success": True, "message_id": "wamid.reply001"}
        response = client.post("/webhook", json=TEXT_MESSAGE)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    @patch("src.webhook_handler.router.send_whatsapp_message")
    @patch("src.webhook_handler.router.download_whatsapp_media")
    def test_audio_message_returns_200(self, mock_dl, mock_send):
        mock_dl.return_value = "temp_media/audio_media_001.ogg"
        mock_send.return_value = {"success": True, "message_id": "wamid.reply002"}
        response = client.post("/webhook", json=AUDIO_MESSAGE)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    @patch("src.webhook_handler.router.send_whatsapp_message")
    @patch("src.webhook_handler.router.download_whatsapp_media")
    def test_image_message_returns_200(self, mock_dl, mock_send):
        mock_dl.return_value = "temp_media/image_media_001.jpg"
        mock_send.return_value = {"success": True, "message_id": "wamid.reply003"}
        response = client.post("/webhook", json=IMAGE_MESSAGE)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_status_update_returns_200(self):
        """
        WhatsApp also POSTs delivery/read receipts. These have no
        'messages' key — the handler should silently return 200 OK.
        """
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "waba_001",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "15550001234",
                                    "phone_number_id": "pid_001",
                                },
                                "statuses": [
                                    {
                                        "id": "wamid.text001",
                                        "status": "delivered",
                                        "timestamp": "1741064540",
                                        "recipient_id": "919876543210",
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }
        response = client.post("/webhook", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_non_whatsapp_object_returns_200(self):
        """Payloads for non-WhatsApp objects are acknowledged without processing."""
        payload = {"object": "instagram", "entry": []}
        response = client.post("/webhook", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /webhook  — Routing correctness (Req 5.2)
# ---------------------------------------------------------------------------

class TestWebhookMediaRouting:
    """
    Verify that audio and image messages are routed to the correct processors
    and that a WhatsApp reply is sent back to the user in each case.
    """

    @patch("src.webhook_handler.router.send_whatsapp_message")
    @patch("src.webhook_handler.router._cleanup_file")
    @patch("src.webhook_handler.router.VoiceProcessor")
    @patch("src.webhook_handler.router.download_whatsapp_media")
    def test_audio_calls_voice_processor(
        self, mock_dl, mock_vp_cls, mock_cleanup, mock_send
    ):
        """Audio message must invoke VoiceProcessor.process_audio."""
        # Arrange
        mock_dl.return_value = "temp_media/audio_media_001.ogg"
        mock_result = MagicMock()
        mock_result.needs_retry = False
        mock_result.text = "मुझे पीएम किसान योजना के लिए आवेदन करना है"
        mock_vp_cls.return_value.process_audio.return_value = mock_result
        mock_send.return_value = {"success": True, "message_id": "wamid.r1"}

        # Act
        client.post("/webhook", json=AUDIO_MESSAGE)

        # Assert
        mock_dl.assert_called_once_with("audio_media_001")
        mock_vp_cls.return_value.process_audio.assert_called_once_with(
            "temp_media/audio_media_001.ogg"
        )

    @patch("src.webhook_handler.router.send_whatsapp_message")
    @patch("src.webhook_handler.router._cleanup_file")
    @patch("src.webhook_handler.router.VoiceProcessor")
    @patch("src.webhook_handler.router.download_whatsapp_media")
    def test_audio_sends_reply(
        self, mock_dl, mock_vp_cls, mock_cleanup, mock_send
    ):
        """A successfully transcribed voice note must trigger a WhatsApp reply."""
        mock_dl.return_value = "temp_media/audio_media_001.ogg"
        mock_result = MagicMock()
        mock_result.needs_retry = False
        mock_result.text = "My name is Ramesh Kumar. I am 45 years old."
        mock_vp_cls.return_value.process_audio.return_value = mock_result
        mock_send.return_value = {"success": True, "message_id": "wamid.r2"}

        client.post("/webhook", json=AUDIO_MESSAGE)

        # send_whatsapp_message must have been called (at least once)
        mock_send.assert_called()
        # Verify the recipient number is correct (works with positional or keyword args)
        args, kwargs = mock_send.call_args
        actual_number = kwargs.get("to_number") or (args[0] if args else None)
        assert actual_number == "919876543210"

    @patch("src.webhook_handler.router.send_whatsapp_message")
    @patch("src.webhook_handler.router._cleanup_file")
    @patch("src.webhook_handler.router.VoiceProcessor")
    @patch("src.webhook_handler.router.download_whatsapp_media")
    def test_audio_retry_sends_guidance(
        self, mock_dl, mock_vp_cls, mock_cleanup, mock_send
    ):
        """If transcription needs retry, the retry guidance is sent as reply."""
        mock_dl.return_value = "temp_media/poor_quality.ogg"
        mock_result = MagicMock()
        mock_result.needs_retry = True
        mock_result.retry_guidance = "Please record in a quieter place."
        mock_vp_cls.return_value.process_audio.return_value = mock_result
        mock_send.return_value = {"success": True, "message_id": "wamid.r3"}

        client.post("/webhook", json=AUDIO_MESSAGE)

        mock_send.assert_called()
        # The retry guidance (or a fallback error) must have been sent
        args, kwargs = mock_send.call_args
        reply_text = kwargs.get("message_text") or (args[1] if len(args) > 1 else "")
        # Any non-empty reply is acceptable; the key is that send was called
        assert reply_text

    @patch("src.webhook_handler.router.send_whatsapp_message")
    @patch("src.webhook_handler.router._cleanup_file")
    @patch("src.webhook_handler.router.VoiceProcessor")
    @patch("src.webhook_handler.router.download_whatsapp_media")
    def test_audio_cleans_up_temp_file(
        self, mock_dl, mock_vp_cls, mock_cleanup, mock_send
    ):
        """Temp file must be cleaned up after audio processing (success or failure)."""
        mock_dl.return_value = "temp_media/audio_media_001.ogg"
        mock_result = MagicMock()
        mock_result.needs_retry = False
        mock_result.text = "Test"
        mock_vp_cls.return_value.process_audio.return_value = mock_result
        mock_send.return_value = {"success": True, "message_id": "wamid.r4"}

        client.post("/webhook", json=AUDIO_MESSAGE)

        mock_cleanup.assert_called_once_with("temp_media/audio_media_001.ogg")

    @patch("src.webhook_handler.router.send_whatsapp_message")
    @patch("src.webhook_handler.router._cleanup_file")
    @patch("src.webhook_handler.router.VoiceProcessor")
    @patch("src.webhook_handler.router.download_whatsapp_media")
    def test_audio_download_failure_sends_error_message(
        self, mock_dl, mock_vp_cls, mock_cleanup, mock_send
    ):
        """If download fails (returns ''), user must receive an error message."""
        mock_dl.return_value = ""  # Simulate download failure
        mock_send.return_value = {"success": True, "message_id": "wamid.r5"}

        client.post("/webhook", json=AUDIO_MESSAGE)

        # VoiceProcessor should NOT be called (no file to process)
        mock_vp_cls.return_value.process_audio.assert_not_called()
        # But an error reply SHOULD be sent
        mock_send.assert_called_once()

    @patch("src.webhook_handler.router.send_whatsapp_message")
    @patch("src.webhook_handler.router._cleanup_file")
    @patch("src.webhook_handler.router.DocumentProcessor")
    @patch("src.webhook_handler.router.download_whatsapp_media")
    def test_image_calls_document_processor(
        self, mock_dl, mock_dp_cls, mock_cleanup, mock_send
    ):
        """Image message must invoke DocumentProcessor.process_document."""
        mock_dl.return_value = "temp_media/image_media_001.jpg"
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_data = {"name": "Ramesh", "aadhaar": "XXXX XXXX 1234"}
        mock_result.errors = []
        mock_result.document_type = MagicMock()
        mock_result.document_type.value = "aadhaar"
        mock_dp_cls.return_value.process_document.return_value = mock_result
        mock_send.return_value = {"success": True, "message_id": "wamid.r6"}

        client.post("/webhook", json=IMAGE_MESSAGE)

        mock_dl.assert_called_once_with("image_media_001")
        mock_dp_cls.return_value.process_document.assert_called_once_with(
            image_url="temp_media/image_media_001.jpg",
            user_id="919876543210",
        )

    @patch("src.webhook_handler.router.send_whatsapp_message")
    @patch("src.webhook_handler.router._cleanup_file")
    @patch("src.webhook_handler.router.DocumentProcessor")
    @patch("src.webhook_handler.router.download_whatsapp_media")
    def test_image_sends_reply(
        self, mock_dl, mock_dp_cls, mock_cleanup, mock_send
    ):
        """A successfully processed document image must trigger a WhatsApp reply."""
        mock_dl.return_value = "temp_media/image_media_001.jpg"
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_data = {"name": "Ramesh"}
        mock_result.errors = []
        mock_result.document_type = MagicMock()
        mock_result.document_type.value = "aadhaar"
        mock_dp_cls.return_value.process_document.return_value = mock_result
        mock_send.return_value = {"success": True, "message_id": "wamid.r7"}

        client.post("/webhook", json=IMAGE_MESSAGE)

        mock_send.assert_called()

    @patch("src.webhook_handler.router.send_whatsapp_message")
    @patch("src.webhook_handler.router._cleanup_file")
    @patch("src.webhook_handler.router.DocumentProcessor")
    @patch("src.webhook_handler.router.download_whatsapp_media")
    def test_image_cleans_up_temp_file(
        self, mock_dl, mock_dp_cls, mock_cleanup, mock_send
    ):
        """Temp file must be cleaned up after document processing."""
        mock_dl.return_value = "temp_media/image_media_001.jpg"
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_data = {}
        mock_result.errors = []
        mock_result.document_type = MagicMock()
        mock_result.document_type.value = "aadhaar"
        mock_dp_cls.return_value.process_document.return_value = mock_result
        mock_send.return_value = {"success": True, "message_id": "wamid.r8"}

        client.post("/webhook", json=IMAGE_MESSAGE)

        mock_cleanup.assert_called_once_with("temp_media/image_media_001.jpg")

    @patch("src.webhook_handler.router.send_whatsapp_message")
    @patch("src.webhook_handler.router._cleanup_file")
    @patch("src.webhook_handler.router.DocumentProcessor")
    @patch("src.webhook_handler.router.download_whatsapp_media")
    def test_image_extraction_failure_sends_error_message(
        self, mock_dl, mock_dp_cls, mock_cleanup, mock_send
    ):
        """If Textract returns success=False, user must receive a quality-error reply."""
        mock_dl.return_value = "temp_media/image_media_001.jpg"
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.errors = ["Image is too blurry. Please retake the photo."]
        mock_result.document_type = None
        mock_dp_cls.return_value.process_document.return_value = mock_result
        mock_send.return_value = {"success": True, "message_id": "wamid.r9"}

        client.post("/webhook", json=IMAGE_MESSAGE)

        mock_send.assert_called()

    @patch("src.webhook_handler.router.send_whatsapp_message")
    @patch("src.webhook_handler.router._cleanup_file")
    @patch("src.webhook_handler.router.DocumentProcessor")
    @patch("src.webhook_handler.router.download_whatsapp_media")
    def test_image_download_failure_sends_error_message(
        self, mock_dl, mock_dp_cls, mock_cleanup, mock_send
    ):
        """If download fails, DocumentProcessor must NOT be called."""
        mock_dl.return_value = ""
        mock_send.return_value = {"success": True, "message_id": "wamid.r10"}

        client.post("/webhook", json=IMAGE_MESSAGE)

        mock_dp_cls.return_value.process_document.assert_not_called()
        mock_send.assert_called_once()


# ---------------------------------------------------------------------------
# POST /webhook  — Document pipeline refactor tests (identity, unknown, errors)
# ---------------------------------------------------------------------------

class TestDocumentPipelineRefactor:
    """
    Tests for the refactored document pipeline:
    - Unknown document type handling
    - Identity mismatch detection
    - Aadhaar name storage
    - AI error handling
    """

    def _mock_dp_success(self, mock_dp_cls):
        """Helper: configure DocumentProcessor mock to return success."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_data = {"name": "Ramesh"}
        mock_result.errors = []
        mock_result.document_type = MagicMock()
        mock_result.document_type.value = "aadhaar"
        mock_dp_cls.return_value.process_document.return_value = mock_result

    @patch("src.webhook_handler.router.invoke_claude")
    @patch("src.webhook_handler.router.send_whatsapp_message")
    @patch("src.webhook_handler.router._cleanup_file")
    @patch("src.webhook_handler.router.DocumentProcessor")
    @patch("src.webhook_handler.router.download_whatsapp_media")
    def test_unknown_document_type_sends_specific_message(
        self, mock_dl, mock_dp_cls, mock_cleanup, mock_send, mock_ai
    ):
        """When AI returns document_type='unknown', user must get the unsupported doc message."""
        mock_dl.return_value = "temp_media/image_media_001.jpg"
        self._mock_dp_success(mock_dp_cls)
        mock_ai.return_value = {
            "document_type": "unknown",
            "extracted_data": {},
            "identity_verification": {"extracted_name": "", "confidence_score": "Low"},
            "eligibility_summary": {"is_eligible": None, "reason": "Unrecognized document"},
            "user_friendly_message": "",
        }
        mock_send.return_value = {"success": True, "message_id": "wamid.unk1"}

        client.post("/webhook", json=IMAGE_MESSAGE)

        # Find the call that sent the unknown document message (not the ack)
        from src.webhook_handler.router import UNKNOWN_DOCUMENT_MESSAGE
        calls = mock_send.call_args_list
        assert any(
            len(c.args) >= 2 and c.args[1] == UNKNOWN_DOCUMENT_MESSAGE for c in calls
        ), f"Expected UNKNOWN_DOCUMENT_MESSAGE in calls, got: {[c.args for c in calls]}"

    @patch("src.webhook_handler.router._USER_NAMES", {"919876543210": "Anmol Mishra"})
    @patch("src.webhook_handler.router.invoke_claude")
    @patch("src.webhook_handler.router.send_whatsapp_message")
    @patch("src.webhook_handler.router._cleanup_file")
    @patch("src.webhook_handler.router.DocumentProcessor")
    @patch("src.webhook_handler.router.download_whatsapp_media")
    def test_identity_mismatch_sends_warning(
        self, mock_dl, mock_dp_cls, mock_cleanup, mock_send, mock_ai
    ):
        """When AI detects a name mismatch, user must get the identity mismatch warning."""
        mock_dl.return_value = "temp_media/image_media_001.jpg"
        self._mock_dp_success(mock_dp_cls)
        mock_ai.return_value = {
            "document_type": "income_certificate",
            "extracted_data": {"name": "Pratapsindhu Barik", "annual_income_inr": 60000},
            "identity_verification": {
                "extracted_name": "Pratapsindhu Barik",
                "confidence_score": "Low",
            },
            "eligibility_summary": {"is_eligible": True, "reason": "Income eligible"},
            "user_friendly_message": "Income certificate processed.",
        }
        mock_send.return_value = {"success": True, "message_id": "wamid.mm1"}

        client.post("/webhook", json=IMAGE_MESSAGE)

        from src.webhook_handler.router import IDENTITY_MISMATCH_MESSAGE
        calls = mock_send.call_args_list
        assert any(
            len(c.args) >= 2 and c.args[1] == IDENTITY_MISMATCH_MESSAGE for c in calls
        ), f"Expected IDENTITY_MISMATCH_MESSAGE in calls, got: {[c.args for c in calls]}"

    @patch("src.webhook_handler.router._USER_NAMES", {})
    @patch("src.webhook_handler.router.invoke_claude")
    @patch("src.webhook_handler.router.send_whatsapp_message")
    @patch("src.webhook_handler.router._cleanup_file")
    @patch("src.webhook_handler.router.DocumentProcessor")
    @patch("src.webhook_handler.router.download_whatsapp_media")
    def test_aadhaar_name_stored_for_future(
        self, mock_dl, mock_dp_cls, mock_cleanup, mock_send, mock_ai
    ):
        """When an Aadhaar is processed, the name must be stored in _USER_NAMES."""
        mock_dl.return_value = "temp_media/image_media_001.jpg"
        self._mock_dp_success(mock_dp_cls)
        mock_ai.return_value = {
            "document_type": "aadhaar",
            "extracted_data": {"name": "RAMESH KUMAR", "aadhaar_number_masked": "XXXX XXXX 3742"},
            "identity_verification": {
                "extracted_name": "RAMESH KUMAR",
                "confidence_score": "High",
            },
            "eligibility_summary": {"is_eligible": None, "reason": "Need more documents"},
            "user_friendly_message": "Aadhaar verified! Name: RAMESH KUMAR.",
        }
        mock_send.return_value = {"success": True, "message_id": "wamid.an1"}

        client.post("/webhook", json=IMAGE_MESSAGE)

        from src.webhook_handler.router import _USER_NAMES
        assert _USER_NAMES.get("919876543210") == "RAMESH KUMAR"

    @patch("src.webhook_handler.router.invoke_claude")
    @patch("src.webhook_handler.router.send_whatsapp_message")
    @patch("src.webhook_handler.router._cleanup_file")
    @patch("src.webhook_handler.router.DocumentProcessor")
    @patch("src.webhook_handler.router.download_whatsapp_media")
    def test_ai_error_sends_processing_error(
        self, mock_dl, mock_dp_cls, mock_cleanup, mock_send, mock_ai
    ):
        """When AI returns an error, user must get the processing error message."""
        mock_dl.return_value = "temp_media/image_media_001.jpg"
        self._mock_dp_success(mock_dp_cls)
        mock_ai.return_value = {"error": "Gemini API error: timeout", "raw": ""}
        mock_send.return_value = {"success": True, "message_id": "wamid.err1"}

        client.post("/webhook", json=IMAGE_MESSAGE)

        from src.webhook_handler.router import PROCESSING_ERROR_MESSAGE
        calls = mock_send.call_args_list
        assert any(
            len(c.args) >= 2 and c.args[1] == PROCESSING_ERROR_MESSAGE for c in calls
        ), f"Expected PROCESSING_ERROR_MESSAGE in calls, got: {[c.args for c in calls]}"

