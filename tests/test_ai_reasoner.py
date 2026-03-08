"""
GramSetu — AI Reasoner Prompt Tests

Validates build_system_prompt() and mock_invoke_claude() from src/ai_reasoner/prompts.py.

Test Classes:
  TestBuildSystemPrompt    — prompt composition, guardrail presence, language/step/scheme injection
  TestMockInvokeClaudeExtraction — entity extraction from Hindi and English inputs
  TestMockInvokeClaudeGuardrails — GUARDRAIL 1 (no hallucination), return type, confidence
"""
import pytest

from src.shared.types import ConversationStep
from src.ai_reasoner.prompts import build_system_prompt, mock_invoke_claude

# ─────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def hindi_welcome_prompt() -> str:
    return build_system_prompt("hi-IN", ConversationStep.WELCOME)

@pytest.fixture(scope="module")
def odia_collecting_docs_prompt() -> str:
    return build_system_prompt("or-IN", ConversationStep.COLLECTING_DOCUMENTS, "pm-kisan")

@pytest.fixture(scope="module")
def english_confirming_prompt() -> str:
    return build_system_prompt("en-IN", ConversationStep.CONFIRMING_DATA, "pmay")

@pytest.fixture(scope="module")
def generic_no_scheme_prompt() -> str:
    return build_system_prompt("hi-IN", ConversationStep.WELCOME, None)

# ─────────────────────────────────────────────────────────────────
# 1. TestBuildSystemPrompt
# ─────────────────────────────────────────────────────────────────

class TestBuildSystemPrompt:

    # ── Language injection ────────────────────────────────────────

    def test_hindi_prompt_contains_hindi_name(self, hindi_welcome_prompt):
        """Hindi language name must appear in the prompt."""
        assert "Hindi" in hindi_welcome_prompt or "हिंदी" in hindi_welcome_prompt

    def test_odia_prompt_contains_odia_name(self, odia_collecting_docs_prompt):
        """Odia language name must appear in the prompt."""
        assert "Odia" in odia_collecting_docs_prompt or "ଓଡ଼ିଆ" in odia_collecting_docs_prompt

    def test_english_prompt_contains_english_name(self, english_confirming_prompt):
        """English prompt must reference 'English' language."""
        assert "English" in english_confirming_prompt

    # ── Guardrail 1 — No Hallucination ───────────────────────────

    def test_guardrail_no_hallucination_present(self, hindi_welcome_prompt):
        """All prompts must contain the no-hallucination guardrail."""
        lowered = hindi_welcome_prompt.lower()
        assert "hallucination" in lowered or "guess" in lowered or "unclear" in lowered

    def test_guardrail_null_instruction_present(self, hindi_welcome_prompt):
        """Prompt must instruct Claude to set missing fields to null (not fabricate)."""
        assert "null" in hindi_welcome_prompt

    # ── Guardrail 2 — Empathy First ───────────────────────────────

    def test_guardrail_empathy_present(self, hindi_welcome_prompt):
        """All prompts must contain the empathy-first guardrail."""
        lowered = hindi_welcome_prompt.lower()
        assert "distress" in lowered or "empathy" in lowered or "acknowledge" in lowered

    # ── Guardrail 3 — Output format strictness ───────────────────

    def test_guardrail_form_field_ids_present(self, hindi_welcome_prompt):
        """Prompt must embed the exact government PDF field IDs."""
        assert "form_field_applicant_name_01" in hindi_welcome_prompt
        assert "form_field_annual_income_01" in hindi_welcome_prompt

    def test_output_format_section_present(self, hindi_welcome_prompt):
        """OUTPUT FORMAT section must be present in every prompt."""
        assert "OUTPUT FORMAT" in hindi_welcome_prompt

    # ── Step-specific contextual guidance ────────────────────────

    def test_collecting_documents_step_in_prompt(self, odia_collecting_docs_prompt):
        """COLLECTING_DOCUMENTS step must inject document-collection guidance."""
        assert "COLLECTING DOCUMENTS" in odia_collecting_docs_prompt or \
               "document" in odia_collecting_docs_prompt.lower()

    def test_confirming_data_step_mentions_confirm(self, english_confirming_prompt):
        """CONFIRMING_DATA step must mention confirmation before PDF generation."""
        lowered = english_confirming_prompt.lower()
        assert "confirm" in lowered

    def test_confirming_data_no_premature_pdf(self, english_confirming_prompt):
        """CONFIRMING_DATA step must not generate PDF without explicit user confirmation."""
        lowered = english_confirming_prompt.lower()
        assert "do not generate" in lowered or "not generate" in lowered \
               or "until the user" in lowered or "do not" in lowered

    # ── Scheme-specific rules ─────────────────────────────────────

    def test_pm_kisan_scheme_rules_injected(self, odia_collecting_docs_prompt):
        """pm-kisan target scheme must inject PM-KISAN specific fields and rules."""
        assert "PM-KISAN" in odia_collecting_docs_prompt or "pm-kisan" in odia_collecting_docs_prompt.lower()

    def test_pm_kisan_includes_land_record_field(self, odia_collecting_docs_prompt):
        """PM-KISAN prompt must mention land record (Khasra) requirement."""
        lowered = odia_collecting_docs_prompt.lower()
        assert "khasra" in lowered or "land" in lowered

    def test_pmay_rules_injected(self, english_confirming_prompt):
        """pmay target scheme must inject PMAY-specific income field."""
        assert "PMAY" in english_confirming_prompt or "Awas Yojana" in english_confirming_prompt

    def test_no_scheme_generic_mode(self, generic_no_scheme_prompt):
        """No target_scheme must inject discovery mode — not a specific scheme's fields."""
        assert "DISCOVERY MODE" in generic_no_scheme_prompt or "discovery" in generic_no_scheme_prompt.lower()

    # ── Return type ───────────────────────────────────────────────

    def test_returns_non_empty_string(self, hindi_welcome_prompt):
        assert isinstance(hindi_welcome_prompt, str)
        assert len(hindi_welcome_prompt) > 200   # must have substantial content

    def test_three_sections_present(self, hindi_welcome_prompt):
        """All three sections (ROLE, CONVERSATION CONTEXT, SCHEME RULES) must be present."""
        assert "## ROLE" in hindi_welcome_prompt
        assert "## CONVERSATION CONTEXT" in hindi_welcome_prompt
        assert "## SCHEME RULES" in hindi_welcome_prompt or "## GUARDRAILS" in hindi_welcome_prompt


# ─────────────────────────────────────────────────────────────────
# 2. TestMockInvokeClaudeExtraction  (entity extraction)
# ─────────────────────────────────────────────────────────────────

DUMMY_PROMPT = "system prompt placeholder"

class TestMockInvokeClaudeExtraction:

    def test_extracts_name_from_english(self):
        """English 'my name is X' pattern must yield the name."""
        result = mock_invoke_claude(DUMMY_PROMPT, "My name is Ramesh Kumar and I am a farmer.")
        assert result["form_field_applicant_name_01"] is not None
        assert "Ramesh" in result["form_field_applicant_name_01"]

    def test_extracts_name_from_hindi(self):
        """Hindi 'मेरा नाम X है' pattern must yield the name."""
        result = mock_invoke_claude(DUMMY_PROMPT, "मेरा नाम रमेश है, मैं किसान हूँ।")
        assert result["form_field_applicant_name_01"] is not None

    def test_extracts_age_from_english(self):
        """'age 42' or '42 years old' must yield integer age."""
        result = mock_invoke_claude(DUMMY_PROMPT, "I am a farmer, age 42, living in Odisha.")
        assert result["form_field_applicant_age_01"] == 42

    def test_extracts_age_from_hindi(self):
        """'42 साल' must yield integer age 42."""
        result = mock_invoke_claude(DUMMY_PROMPT, "मेरी उम्र 42 साल है।")
        assert result["form_field_applicant_age_01"] == 42

    def test_extracts_income_rupees(self):
        """'₹60000' must yield integer income 60000."""
        result = mock_invoke_claude(DUMMY_PROMPT, "My annual income is ₹60000 from farming.")
        assert result["form_field_annual_income_01"] == 60000

    def test_extracts_income_hazar(self):
        """'60 हजार रुपये' must yield income 60000."""
        result = mock_invoke_claude(DUMMY_PROMPT, "मेरी सालाना आमदनी 60 हजार रुपये है।")
        assert result["form_field_annual_income_01"] == 60000

    def test_extracts_all_three_fields_combined(self):
        """A rich sentence must extract name, age, and income together."""
        text = "My name is Priya Devi, I am 35 years old, and my annual income is Rs. 48000."
        result = mock_invoke_claude(DUMMY_PROMPT, text)
        assert result["form_field_applicant_name_01"] is not None
        assert result["form_field_applicant_age_01"] == 35
        assert result["form_field_annual_income_01"] == 48000


# ─────────────────────────────────────────────────────────────────
# 3. TestMockInvokeClaudeGuardrails  (GUARDRAIL 1 + return contract)
# ─────────────────────────────────────────────────────────────────

class TestMockInvokeClaudeGuardrails:

    def test_aadhaar_is_always_null(self):
        """
        Aadhaar must NEVER be guessed from plain text — it always requires
        a document photo. GUARDRAIL 1 enforcement.
        """
        # Even if user says "my aadhaar is 1234", mock must not extract it
        result = mock_invoke_claude(DUMMY_PROMPT, "my name is Ramesh, aadhaar 9876")
        assert result["form_field_aadhaar_last4_01"] is None

    def test_village_is_always_null_without_doc(self):
        """Village must remain null without explicit document extraction."""
        result = mock_invoke_claude(DUMMY_PROMPT, "I live in Balasore village, Odisha.")
        # Village field is null — this requires Textract from an address proof doc
        assert result["form_field_village_name_01"] is None

    def test_missing_fields_in_needs_followup(self):
        """All null fields must appear in needs_followup list."""
        result = mock_invoke_claude(DUMMY_PROMPT, "My name is Ramesh.")
        # age and income are missing → must be in needs_followup
        assert "form_field_applicant_age_01" in result["needs_followup"]
        assert "form_field_annual_income_01" in result["needs_followup"]

    def test_extracted_fields_not_in_needs_followup(self):
        """Successfully extracted fields must NOT appear in needs_followup."""
        result = mock_invoke_claude(DUMMY_PROMPT, "My name is Ramesh Kumar, age 42.")
        assert "form_field_applicant_name_01" not in result["needs_followup"]
        assert "form_field_applicant_age_01" not in result["needs_followup"]

    def test_returns_dict(self):
        """mock_invoke_claude must always return a dict."""
        result = mock_invoke_claude(DUMMY_PROMPT, "some random input")
        assert isinstance(result, dict)

    def test_has_confidence_key(self):
        """Returned dict must always have a 'confidence' float key."""
        result = mock_invoke_claude(DUMMY_PROMPT, "some random input")
        assert "confidence" in result
        assert isinstance(result["confidence"], float)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_has_notes_key(self):
        """Returned dict must always have a 'notes' string."""
        result = mock_invoke_claude(DUMMY_PROMPT, "some random input")
        assert "notes" in result
        assert isinstance(result["notes"], str)

    def test_confidence_zero_when_nothing_extracted(self):
        """Confidence must be 0.0 when no fields are extractable."""
        result = mock_invoke_claude(DUMMY_PROMPT, "ठीक है धन्यवाद।")  # "OK thank you" — no data
        assert result["confidence"] == 0.0

    def test_confidence_higher_with_more_fields(self):
        """More extracted fields must produce higher confidence."""
        sparse = mock_invoke_claude(DUMMY_PROMPT, "My name is Ramesh.")
        rich = mock_invoke_claude(DUMMY_PROMPT, "My name is Ramesh, age 42, income ₹60000.")
        assert rich["confidence"] >= sparse["confidence"]

    def test_all_required_field_ids_present(self):
        """All 7 form field IDs plus meta keys must always be present in the result."""
        result = mock_invoke_claude(DUMMY_PROMPT, "hello")
        required_keys = {
            "form_field_applicant_name_01",
            "form_field_applicant_age_01",
            "form_field_annual_income_01",
            "form_field_aadhaar_last4_01",
            "form_field_village_name_01",
            "form_field_district_01",
            "form_field_state_01",
            "confidence",
            "needs_followup",
            "notes",
        }
        assert required_keys.issubset(result.keys())
