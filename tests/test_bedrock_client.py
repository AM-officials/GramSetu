"""
GramSetu — Gemini Vision Client Unit Tests

Tests for src/ai_reasoner/client.py (google-generativeai + PIL).
All Gemini and PIL calls are mocked — no real API key needed.

Test Classes:
  TestTextOnlyCall   — text-only prompt, happy-path JSON parsing
  TestVisionCall     — PIL Image.open and multimodal parts construction
  TestErrorHandling  — missing key, Gemini API errors, non-JSON responses
"""
from __future__ import annotations

import json
import tempfile
from unittest.mock import MagicMock, patch, call

import pytest

# Import module under test at module level so patch targets resolve correctly.
from src.ai_reasoner.client import invoke_claude


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _mock_gemini_response(payload: dict | str) -> MagicMock:
    """Return a fake Gemini GenerateContentResponse."""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    resp = MagicMock()
    resp.text = text
    return resp


def _patch_model(response: MagicMock):
    """
    Patch _get_model() so that model.generate_content() returns *response*.
    Returns (patcher, mock_model).
    """
    mock_model = MagicMock()
    mock_model.generate_content.return_value = response
    patcher = patch("src.ai_reasoner.client._get_model", return_value=mock_model)
    return patcher, mock_model


# ─────────────────────────────────────────────────────────────────
# 1. TestTextOnlyCall
# ─────────────────────────────────────────────────────────────────

class TestTextOnlyCall:

    def test_returns_parsed_dict(self, monkeypatch):
        """Happy path: Gemini returns valid JSON → invoke_claude returns a dict."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        expected = {"form_field_applicant_name_01": "Ramesh", "confidence": 0.9}
        patcher, mock_model = _patch_model(_mock_gemini_response(expected))
        with patcher:
            result = invoke_claude("sys prompt", "user text")
        assert isinstance(result, dict)
        assert result["form_field_applicant_name_01"] == "Ramesh"
        assert result["confidence"] == 0.9

    def test_prompt_contains_yojnas(self, monkeypatch):
        """AVAILABLE_YOJNAS must appear in the prompt passed to generate_content."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        patcher, mock_model = _patch_model(_mock_gemini_response({}))
        with patcher:
            invoke_claude("sys", "hello")
        parts = mock_model.generate_content.call_args.args[0]
        prompt_text = parts[0]
        assert "PM-Kisan" in prompt_text or "AVAILABLE_YOJNAS" in prompt_text or "rules" in prompt_text

    def test_strips_markdown_code_fences(self, monkeypatch):
        """Gemini sometimes wraps JSON in ```json ... ``` — client must strip and parse."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        fenced = "```json\n{\"confidence\": 0.8}\n```"
        patcher, mock_model = _patch_model(_mock_gemini_response(fenced))
        with patcher:
            result = invoke_claude("sys", "text")
        assert result.get("confidence") == 0.8

    def test_no_image_part_without_path(self, monkeypatch):
        """Without image_path, generate_content must not receive a PIL Image part."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        patcher, mock_model = _patch_model(_mock_gemini_response({}))
        with patcher:
            invoke_claude("sys", "text only")
        parts = mock_model.generate_content.call_args.args[0]
        from PIL.Image import Image as PILImage
        assert not any(isinstance(p, PILImage) for p in parts)

    def test_user_input_appended_to_parts(self, monkeypatch):
        """Non-empty user_input must be included as a string part."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        patcher, mock_model = _patch_model(_mock_gemini_response({}))
        with patcher:
            invoke_claude("sys", "MY_SPECIAL_USER_INPUT")
        parts = mock_model.generate_content.call_args.args[0]
        assert any("MY_SPECIAL_USER_INPUT" in str(p) for p in parts)


# ─────────────────────────────────────────────────────────────────
# 2. TestVisionCall
# ─────────────────────────────────────────────────────────────────

class TestVisionCall:

    def test_image_part_present_when_path_given(self, monkeypatch):
        """When image_path is a valid file, a PIL Image must be in the content parts."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        patcher, mock_model = _patch_model(_mock_gemini_response({}))

        # Create a minimal valid PNG so PIL.Image.open succeeds
        from PIL import Image as PILImageModule
        import io
        img_buf = io.BytesIO()
        PILImageModule.new("RGB", (10, 10), color=(0, 0, 0)).save(img_buf, format="PNG")
        img_buf.seek(0)

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(img_buf.read())
            tmp_path = f.name

        with patcher:
            invoke_claude("sys", "describe document", image_path=tmp_path)

        parts = mock_model.generate_content.call_args.args[0]
        from PIL.Image import Image as PILImage
        pil_parts = [p for p in parts if isinstance(p, PILImage)]
        assert len(pil_parts) == 1

    def test_missing_image_path_does_not_raise(self, monkeypatch):
        """A non-existent image_path must be silently skipped — no exception."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        patcher, mock_model = _patch_model(_mock_gemini_response({}))
        with patcher:
            result = invoke_claude("sys", "text", image_path="/tmp/ghost_file.jpg")
        assert isinstance(result, dict)

    def test_missing_image_falls_back_to_text_only(self, monkeypatch):
        """When image is missing, generate_content is still called (text-only)."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        patcher, mock_model = _patch_model(_mock_gemini_response({}))
        with patcher:
            invoke_claude("sys", "text", image_path="/tmp/ghost.jpg")
        assert mock_model.generate_content.call_count == 1


# ─────────────────────────────────────────────────────────────────
# 3. TestErrorHandling
# ─────────────────────────────────────────────────────────────────

class TestErrorHandling:

    def test_missing_api_key_returns_error(self, monkeypatch):
        """Missing GEMINI_API_KEY must return an error dict, not raise KeyError."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        result = invoke_claude("sys", "user")
        assert "error" in result
        assert isinstance(result, dict)

    def test_non_json_response_returns_raw(self, monkeypatch):
        """Non-JSON Gemini output must return {'error': ..., 'raw': ...}."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        patcher, mock_model = _patch_model(_mock_gemini_response("Sorry, cannot process."))
        with patcher:
            result = invoke_claude("sys", "user")
        assert "error" in result
        assert "raw" in result

    def test_gemini_exception_returns_error_dict(self, monkeypatch):
        """An exception from generate_content must return an error dict, not raise."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = RuntimeError("quota exceeded")
        with patch("src.ai_reasoner.client._get_model", return_value=mock_model):
            result = invoke_claude("sys", "user")
        assert "error" in result
        assert isinstance(result, dict)

    def test_always_returns_dict(self, monkeypatch):
        """invoke_claude must return a dict on every code path — never None or raise."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = Exception("network timeout")
        with patch("src.ai_reasoner.client._get_model", return_value=mock_model):
            result = invoke_claude("sys", "user")
        assert isinstance(result, dict)
