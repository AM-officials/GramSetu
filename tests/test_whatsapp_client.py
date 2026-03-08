"""
Tests for src/whatsapp_client/client.py

All tests mock httpx.post to avoid real network calls.
Env vars are injected with patch.dict(os.environ, ...) so the real
WHATSAPP_API_TOKEN in .env does not interfere.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from src.whatsapp_client.client import (
    GRAPH_API_BASE,
    GRAPH_API_VERSION,
    _extract_error,
    send_whatsapp_message,
)

# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

_GOOD_ENV = {
    "WHATSAPP_API_TOKEN": "test_bearer_token_abc123",
    "WHATSAPP_PHONE_NUMBER_ID": "1234567890",
}

_SUCCESS_BODY = {
    "messaging_product": "whatsapp",
    "contacts": [{"input": "919876543210", "wa_id": "919876543210"}],
    "messages": [{"id": "wamid.abc123"}],
}


def _make_mock_response(status_code: int, json_body: dict) -> MagicMock:
    """Build a mock httpx.Response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_body
    mock_resp.text = str(json_body)
    return mock_resp


# ─────────────────────────────────────────────────────────────────
# TestSuccessfulSend
# ─────────────────────────────────────────────────────────────────


class TestSuccessfulSend:
    """send_whatsapp_message returns success=True when Meta returns 200."""

    @patch("src.whatsapp_client.client.httpx.post")
    def test_returns_success_true(self, mock_post):
        mock_post.return_value = _make_mock_response(200, _SUCCESS_BODY)
        with patch.dict(os.environ, _GOOD_ENV):
            result = send_whatsapp_message("919876543210", "Hello!")
        assert result["success"] is True

    @patch("src.whatsapp_client.client.httpx.post")
    def test_returns_message_id(self, mock_post):
        mock_post.return_value = _make_mock_response(200, _SUCCESS_BODY)
        with patch.dict(os.environ, _GOOD_ENV):
            result = send_whatsapp_message("919876543210", "Hello!")
        assert result["message_id"] == "wamid.abc123"

    @patch("src.whatsapp_client.client.httpx.post")
    def test_returns_status_code(self, mock_post):
        mock_post.return_value = _make_mock_response(200, _SUCCESS_BODY)
        with patch.dict(os.environ, _GOOD_ENV):
            result = send_whatsapp_message("919876543210", "Hello!")
        assert result["status_code"] == 200

    @patch("src.whatsapp_client.client.httpx.post")
    def test_url_contains_phone_number_id(self, mock_post):
        mock_post.return_value = _make_mock_response(200, _SUCCESS_BODY)
        with patch.dict(os.environ, _GOOD_ENV):
            send_whatsapp_message("919876543210", "Hello!")
        call_args = mock_post.call_args
        called_url = call_args[0][0] if call_args[0] else call_args.kwargs.get("url", call_args[0][0])
        expected_url = f"{GRAPH_API_BASE}/{GRAPH_API_VERSION}/1234567890/messages"
        assert called_url == expected_url

    @patch("src.whatsapp_client.client.httpx.post")
    def test_authorization_header_is_bearer(self, mock_post):
        mock_post.return_value = _make_mock_response(200, _SUCCESS_BODY)
        with patch.dict(os.environ, _GOOD_ENV):
            send_whatsapp_message("919876543210", "Hello!")
        call_kwargs = mock_post.call_args.kwargs
        headers = call_kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer test_bearer_token_abc123"

    @patch("src.whatsapp_client.client.httpx.post")
    def test_payload_contains_recipient_number(self, mock_post):
        mock_post.return_value = _make_mock_response(200, _SUCCESS_BODY)
        with patch.dict(os.environ, _GOOD_ENV):
            send_whatsapp_message("919876543210", "Hello!")
        call_kwargs = mock_post.call_args.kwargs
        payload = call_kwargs.get("json", {})
        assert payload.get("to") == "919876543210"

    @patch("src.whatsapp_client.client.httpx.post")
    def test_payload_contains_message_text(self, mock_post):
        mock_post.return_value = _make_mock_response(200, _SUCCESS_BODY)
        with patch.dict(os.environ, _GOOD_ENV):
            send_whatsapp_message("919876543210", "Hello GramSetu!")
        call_kwargs = mock_post.call_args.kwargs
        body_text = call_kwargs.get("json", {}).get("text", {}).get("body")
        assert body_text == "Hello GramSetu!"

    @patch("src.whatsapp_client.client.httpx.post")
    def test_payload_messaging_product_is_whatsapp(self, mock_post):
        mock_post.return_value = _make_mock_response(200, _SUCCESS_BODY)
        with patch.dict(os.environ, _GOOD_ENV):
            send_whatsapp_message("919876543210", "Hi!")
        payload = mock_post.call_args.kwargs.get("json", {})
        assert payload.get("messaging_product") == "whatsapp"

    @patch("src.whatsapp_client.client.httpx.post")
    def test_accepts_201_created(self, mock_post):
        """Meta Cloud API may return 201 on some deployments; treat as success."""
        mock_post.return_value = _make_mock_response(201, _SUCCESS_BODY)
        with patch.dict(os.environ, _GOOD_ENV):
            result = send_whatsapp_message("919876543210", "Hi!")
        assert result["success"] is True


# ─────────────────────────────────────────────────────────────────
# TestMissingCredentials
# ─────────────────────────────────────────────────────────────────


class TestMissingCredentials:
    """send_whatsapp_message returns success=False without raising when env vars are absent."""

    def test_missing_token_returns_failure(self):
        env = {"WHATSAPP_PHONE_NUMBER_ID": "1234567890"}
        with patch.dict(os.environ, env, clear=True):
            result = send_whatsapp_message("919876543210", "Hi!")
        assert result["success"] is False

    def test_missing_token_no_exception(self):
        with patch.dict(os.environ, {"WHATSAPP_PHONE_NUMBER_ID": "1234567890"}, clear=True):
            # Must not raise
            result = send_whatsapp_message("919876543210", "Hi!")
        assert "error" in result

    def test_missing_token_status_code_is_none(self):
        with patch.dict(os.environ, {"WHATSAPP_PHONE_NUMBER_ID": "1234567890"}, clear=True):
            result = send_whatsapp_message("919876543210", "Hi!")
        assert result["status_code"] is None

    def test_missing_phone_id_returns_failure(self):
        env = {"WHATSAPP_API_TOKEN": "test_token"}
        with patch.dict(os.environ, env, clear=True):
            result = send_whatsapp_message("919876543210", "Hi!")
        assert result["success"] is False

    def test_missing_phone_id_status_code_is_none(self):
        env = {"WHATSAPP_API_TOKEN": "test_token"}
        with patch.dict(os.environ, env, clear=True):
            result = send_whatsapp_message("919876543210", "Hi!")
        assert result["status_code"] is None


# ─────────────────────────────────────────────────────────────────
# TestHTTPErrors
# ─────────────────────────────────────────────────────────────────


class TestHTTPErrors:
    """send_whatsapp_message handles non-200 responses without raising."""

    @patch("src.whatsapp_client.client.httpx.post")
    def test_4xx_returns_failure(self, mock_post):
        error_body = {"error": {"message": "Invalid OAuth access token", "code": 190}}
        mock_post.return_value = _make_mock_response(400, error_body)
        with patch.dict(os.environ, _GOOD_ENV):
            result = send_whatsapp_message("919876543210", "Hi!")
        assert result["success"] is False

    @patch("src.whatsapp_client.client.httpx.post")
    def test_4xx_preserves_status_code(self, mock_post):
        error_body = {"error": {"message": "Invalid OAuth access token", "code": 190}}
        mock_post.return_value = _make_mock_response(401, error_body)
        with patch.dict(os.environ, _GOOD_ENV):
            result = send_whatsapp_message("919876543210", "Hi!")
        assert result["status_code"] == 401

    @patch("src.whatsapp_client.client.httpx.post")
    def test_5xx_returns_failure(self, mock_post):
        mock_post.return_value = _make_mock_response(500, {"error": {"message": "Internal error"}})
        with patch.dict(os.environ, _GOOD_ENV):
            result = send_whatsapp_message("919876543210", "Hi!")
        assert result["success"] is False

    @patch("src.whatsapp_client.client.httpx.post")
    def test_error_message_included_in_result(self, mock_post):
        error_body = {"error": {"message": "Token expired", "code": 190}}
        mock_post.return_value = _make_mock_response(401, error_body)
        with patch.dict(os.environ, _GOOD_ENV):
            result = send_whatsapp_message("919876543210", "Hi!")
        assert "error" in result
        assert result["error"]  # non-empty


# ─────────────────────────────────────────────────────────────────
# TestNetworkExceptions
# ─────────────────────────────────────────────────────────────────


class TestNetworkExceptions:
    """send_whatsapp_message handles network-level failures gracefully."""

    @patch("src.whatsapp_client.client.httpx.post")
    def test_connect_error_returns_failure(self, mock_post):
        import httpx as _httpx
        mock_post.side_effect = _httpx.ConnectError("Connection refused")
        with patch.dict(os.environ, _GOOD_ENV):
            result = send_whatsapp_message("919876543210", "Hi!")
        assert result["success"] is False

    @patch("src.whatsapp_client.client.httpx.post")
    def test_connect_error_no_exception_raised(self, mock_post):
        import httpx as _httpx
        mock_post.side_effect = _httpx.ConnectError("Connection refused")
        with patch.dict(os.environ, _GOOD_ENV):
            result = send_whatsapp_message("919876543210", "Hi!")
        # Must not raise — this is the critical webhook safety requirement
        assert result is not None

    @patch("src.whatsapp_client.client.httpx.post")
    def test_timeout_returns_failure(self, mock_post):
        import httpx as _httpx
        mock_post.side_effect = _httpx.TimeoutException("Request timed out")
        with patch.dict(os.environ, _GOOD_ENV):
            result = send_whatsapp_message("919876543210", "Hi!")
        assert result["success"] is False

    @patch("src.whatsapp_client.client.httpx.post")
    def test_timeout_status_code_is_none(self, mock_post):
        import httpx as _httpx
        mock_post.side_effect = _httpx.TimeoutException("Request timed out")
        with patch.dict(os.environ, _GOOD_ENV):
            result = send_whatsapp_message("919876543210", "Hi!")
        assert result["status_code"] is None


# ─────────────────────────────────────────────────────────────────
# TestExtractError (internal helper)
# ─────────────────────────────────────────────────────────────────


class TestExtractError:
    """_extract_error correctly parses Meta's error response shape."""

    def test_extracts_message_and_code(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "error": {"message": "Invalid token", "code": 190}
        }
        result = _extract_error(mock_resp)
        assert "190" in result
        assert "Invalid token" in result

    def test_falls_back_to_text_on_json_error(self):
        mock_resp = MagicMock()
        mock_resp.json.side_effect = ValueError("Not JSON")
        mock_resp.text = "Bad gateway"
        result = _extract_error(mock_resp)
        assert "Bad gateway" in result
