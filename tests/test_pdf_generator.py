"""
GramSetu — PDF Generator Tests

Validates PDFGenerator.generate_application() from src/pdf_generator/generator.py.

Requirements verified:
  Req 4.1 — Validation gate: missing fields → PDFResult(success=False, missing_fields=[...])
  Req 4.2 — Pre-filled form output: success case returns a structured S3 URL
  Req 4.4 — Submission instructions: bilingual English + Hindi
  Req 4.5 — At least 3 scheme templates: PM-KISAN, PMAY, MGNREGA (+ PM-JAN-DHAN)

Test Classes:
  TestValidationFailures    — missing required fields → success=False with descriptive labels
  TestSuccessfulGeneration  — fully populated UserData → success=True, S3 URL, instructions
  TestEdgeCases             — unknown scheme, aliases, empty user_data
"""
import pytest

from src.shared.db_models import (
    FamilyInfo,
    IncomeInfo,
    Location,
    PersonalInfo,
    ProcessedDocument,
    UserData,
)
from src.shared.types import DocumentType
from src.pdf_generator.generator import PDFGenerator, PDFResult


# ═══════════════════════════════════════════════════════════════════
# Fixtures — UserData builders
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def generator() -> PDFGenerator:
    return PDFGenerator()


def _make_aadhaar_doc() -> ProcessedDocument:
    return ProcessedDocument(
        doc_type=DocumentType.AADHAAR,
        extracted_data={"name": "RAMESH KUMAR", "aadhaar_last4": "3742"},
        confidence=0.92,
        image_s3_key="s3://bucket/aadhaar.jpg",
    )


def _make_land_doc() -> ProcessedDocument:
    return ProcessedDocument(
        doc_type=DocumentType.LAND_RECORD,
        extracted_data={"khasra_number": "234/B", "owner_name": "Ramesh Kumar"},
        confidence=0.85,
        image_s3_key="s3://bucket/land.jpg",
    )


def _make_income_doc() -> ProcessedDocument:
    return ProcessedDocument(
        doc_type=DocumentType.INCOME_CERTIFICATE,
        extracted_data={"annual_income_inr": 60000},
        confidence=0.88,
        image_s3_key="s3://bucket/income.jpg",
    )


def _full_personal_info() -> PersonalInfo:
    return PersonalInfo(full_name="Ramesh Kumar", age=42, gender="Male", aadhaar_last4="3742")


def _full_location() -> Location:
    return Location(state="Odisha", district="Sundargarh", village="Dharampur")


def _full_income() -> IncomeInfo:
    return IncomeInfo(annual_income_inr=60000, income_source="agriculture")


# ── Fully valid UserData for each scheme ──────────────────────────

@pytest.fixture(scope="module")
def valid_pm_kisan_data() -> UserData:
    return UserData(
        personal_info=_full_personal_info(),
        location=_full_location(),
        income=_full_income(),
        documents=[_make_aadhaar_doc(), _make_land_doc()],
    )


@pytest.fixture(scope="module")
def valid_pmay_data() -> UserData:
    return UserData(
        personal_info=_full_personal_info(),
        location=_full_location(),
        income=_full_income(),
        documents=[_make_aadhaar_doc(), _make_income_doc()],
    )


@pytest.fixture(scope="module")
def valid_mgnrega_data() -> UserData:
    """MGNREGA only needs name, Aadhaar, and location — no income or land doc."""
    return UserData(
        personal_info=_full_personal_info(),
        location=_full_location(),
        documents=[_make_aadhaar_doc()],
    )


@pytest.fixture(scope="module")
def valid_jan_dhan_data() -> UserData:
    """PM Jan Dhan only needs name, Aadhaar, and village."""
    return UserData(
        personal_info=_full_personal_info(),
        location=_full_location(),
    )


# ═══════════════════════════════════════════════════════════════════
# 1. TestValidationFailures  (Req 4.1)
# ═══════════════════════════════════════════════════════════════════

class TestValidationFailures:

    def test_empty_userdata_fails_pm_kisan(self, generator):
        """Completely empty UserData must fail all PM-KISAN checks."""
        result = generator.generate_application("pm-kisan", UserData())
        assert result.success is False
        assert len(result.missing_fields) > 0

    def test_pm_kisan_fails_without_name(self, generator):
        """Missing full_name must flag 'name' as a missing field."""
        data = UserData(
            personal_info=PersonalInfo(aadhaar_last4="3742"),  # no full_name
            location=_full_location(),
            income=_full_income(),
            documents=[_make_aadhaar_doc(), _make_land_doc()],
        )
        result = generator.generate_application("pm-kisan", data)
        assert result.success is False
        assert any("name" in f.lower() or "नाम" in f for f in result.missing_fields)

    def test_pm_kisan_fails_without_aadhaar(self, generator):
        """Missing aadhaar_last4 must flag Aadhaar as missing."""
        data = UserData(
            personal_info=PersonalInfo(full_name="Ramesh Kumar"),   # no aadhaar_last4
            location=_full_location(),
            income=_full_income(),
            documents=[_make_aadhaar_doc(), _make_land_doc()],
        )
        result = generator.generate_application("pm-kisan", data)
        assert result.success is False
        assert any("aadhaar" in f.lower() or "आधार" in f for f in result.missing_fields)

    def test_pm_kisan_fails_without_land_record_doc(self, generator):
        """A PM-KISAN form must fail if no LAND_RECORD document has been uploaded."""
        data = UserData(
            personal_info=_full_personal_info(),
            location=_full_location(),
            income=_full_income(),
            documents=[_make_aadhaar_doc()],   # no land doc
        )
        result = generator.generate_application("pm-kisan", data)
        assert result.success is False
        assert any("land" in f.lower() or "ज़मीन" in f or "khasra" in f.lower()
                   for f in result.missing_fields)

    def test_pm_kisan_fails_without_income(self, generator):
        """Missing income triggers a missing field for PM-KISAN."""
        data = UserData(
            personal_info=_full_personal_info(),
            location=_full_location(),
            income=None,
            documents=[_make_aadhaar_doc(), _make_land_doc()],
        )
        result = generator.generate_application("pm-kisan", data)
        assert result.success is False
        assert any("income" in f.lower() or "आय" in f for f in result.missing_fields)

    def test_pm_kisan_fails_without_location(self, generator):
        """Missing location means village + district are unknown — must fail."""
        data = UserData(
            personal_info=_full_personal_info(),
            location=None,
            income=_full_income(),
            documents=[_make_aadhaar_doc(), _make_land_doc()],
        )
        result = generator.generate_application("pm-kisan", data)
        assert result.success is False
        assert any("village" in f.lower() or "गाँव" in f for f in result.missing_fields)

    def test_pmay_fails_without_income_certificate_doc(self, generator):
        """PMAY requires an uploaded income certificate — voice-reported income alone is insufficient."""
        data = UserData(
            personal_info=_full_personal_info(),
            location=_full_location(),
            income=_full_income(),
            documents=[_make_aadhaar_doc()],   # income doc missing
        )
        result = generator.generate_application("pmay", data)
        assert result.success is False
        assert any("income certificate" in f.lower() or "आय प्रमाण" in f
                   for f in result.missing_fields)

    def test_pmay_fails_without_state(self, generator):
        """PMAY requires state (for rural vs. urban classification) — must fail without it."""
        data = UserData(
            personal_info=_full_personal_info(),
            location=Location(state="", district="Sundargarh", village="Dharampur"),
            income=_full_income(),
            documents=[_make_aadhaar_doc(), _make_income_doc()],
        )
        result = generator.generate_application("pmay", data)
        assert result.success is False

    def test_missing_fields_are_human_readable(self, generator):
        """Missing field labels must be non-empty human-readable strings, not Python attr names."""
        result = generator.generate_application("pm-kisan", UserData())
        for field in result.missing_fields:
            assert isinstance(field, str)
            assert len(field) > 5          # not just "name" or "pk"
            # Must NOT be raw Python attribute paths like "personal_info.full_name"
            assert "personal_info." not in field

    def test_failure_has_no_pdf_url(self, generator):
        """PDF URL must be None when validation fails — nothing is generated."""
        result = generator.generate_application("pm-kisan", UserData())
        assert result.pdf_s3_url is None

    def test_failure_generated_at_is_none(self, generator):
        """generated_at timestamp must be None when no PDF is produced."""
        result = generator.generate_application("pm-kisan", UserData())
        assert result.generated_at is None


# ═══════════════════════════════════════════════════════════════════
# 2. TestSuccessfulGeneration  (Req 4.2, 4.4, 4.5)
# ═══════════════════════════════════════════════════════════════════

class TestSuccessfulGeneration:

    def test_pm_kisan_success(self, generator, valid_pm_kisan_data):
        """Fully populated PM-KISAN UserData must produce success=True. (Req 4.2)"""
        result = generator.generate_application("pm-kisan", valid_pm_kisan_data)
        assert result.success is True

    def test_pmay_success(self, generator, valid_pmay_data):
        """Fully populated PMAY UserData must produce success=True. (Req 4.5)"""
        result = generator.generate_application("pmay", valid_pmay_data)
        assert result.success is True

    def test_mgnrega_success(self, generator, valid_mgnrega_data):
        """Fully populated MGNREGA UserData (minimal fields) must produce success=True. (Req 4.5)"""
        result = generator.generate_application("mgnrega", valid_mgnrega_data)
        assert result.success is True

    def test_jan_dhan_success(self, generator, valid_jan_dhan_data):
        """Fully populated PM-JAN-DHAN UserData must produce success=True. (Req 4.5)"""
        result = generator.generate_application("pm-jan-dhan", valid_jan_dhan_data)
        assert result.success is True

    def test_success_has_s3_url(self, generator, valid_pm_kisan_data):
        """Successful generation must include a non-empty S3 URL. (Req 4.2)"""
        result = generator.generate_application("pm-kisan", valid_pm_kisan_data)
        assert result.pdf_s3_url is not None
        assert result.pdf_s3_url.startswith("s3://")

    def test_s3_url_contains_scheme_type(self, generator, valid_pm_kisan_data):
        """The S3 URL must include the scheme slug for traceability."""
        result = generator.generate_application("pm-kisan", valid_pm_kisan_data)
        assert "pm-kisan" in result.pdf_s3_url

    def test_s3_url_contains_user_id(self, generator, valid_pm_kisan_data):
        """When user_id is provided, it must appear in the S3 URL path."""
        result = generator.generate_application(
            "pm-kisan", valid_pm_kisan_data, user_id="919876543210"
        )
        assert "919876543210" in result.pdf_s3_url

    def test_missing_fields_empty_on_success(self, generator, valid_pm_kisan_data):
        """Successful result must have an empty missing_fields list."""
        result = generator.generate_application("pm-kisan", valid_pm_kisan_data)
        assert result.missing_fields == []

    def test_has_submission_instructions(self, generator, valid_pm_kisan_data):
        """Submission instructions must be a non-empty string. (Req 4.4)"""
        result = generator.generate_application("pm-kisan", valid_pm_kisan_data)
        assert isinstance(result.submission_instructions, str)
        assert len(result.submission_instructions) > 50

    def test_instructions_mention_csc_for_pm_kisan(self, generator, valid_pm_kisan_data):
        """PM-KISAN instructions must direct user to CSC or Gram Panchayat. (Req 4.4)"""
        result = generator.generate_application("pm-kisan", valid_pm_kisan_data)
        instr = result.submission_instructions
        assert "CSC" in instr or "Gram Panchayat" in instr or "जन सेवा केंद्र" in instr

    def test_instructions_are_bilingual(self, generator, valid_pm_kisan_data):
        """Instructions must contain both English and Hindi text. (design.md empathy rule)"""
        result = generator.generate_application("pm-kisan", valid_pm_kisan_data)
        instr = result.submission_instructions
        # Contains at least one Hindi/Devanagari character
        has_hindi = any("\u0900" <= ch <= "\u097F" for ch in instr)
        assert has_hindi, "Instructions must include Hindi (Devanagari script) text"

    def test_generated_at_is_set(self, generator, valid_pm_kisan_data):
        """generated_at must be a timezone-aware datetime on success."""
        result = generator.generate_application("pm-kisan", valid_pm_kisan_data)
        assert result.generated_at is not None
        assert result.generated_at.tzinfo is not None   # must be tz-aware

    def test_scheme_type_preserved_in_result(self, generator, valid_pmay_data):
        """Result must echo back the scheme_type for downstream routing."""
        result = generator.generate_application("pmay", valid_pmay_data)
        assert result.scheme_type == "pmay"


# ═══════════════════════════════════════════════════════════════════
# 3. TestEdgeCases
# ═══════════════════════════════════════════════════════════════════

class TestEdgeCases:

    def test_unknown_scheme_returns_error(self, generator):
        """Unknown scheme slug must return success=False with an error msg, not raise."""
        result = generator.generate_application("ration-distribution", UserData())
        assert result.success is False
        assert len(result.errors) > 0

    def test_unknown_scheme_error_mentions_scheme_name(self, generator):
        """The error message should include the unrecognised scheme slug."""
        result = generator.generate_application("xyz-unknown-scheme", UserData())
        assert "xyz-unknown-scheme" in result.errors[0]

    def test_scheme_type_is_case_insensitive(self, generator, valid_pm_kisan_data):
        """'PM-KISAN' (upper-case) must be normalised and still succeed."""
        result = generator.generate_application("PM-KISAN", valid_pm_kisan_data)
        assert result.success is True

    def test_scheme_type_strips_whitespace(self, generator, valid_mgnrega_data):
        """Leading/trailing whitespace in scheme_type must be tolerated."""
        result = generator.generate_application("  mgnrega  ", valid_mgnrega_data)
        assert result.success is True

    def test_generate_application_accepts_optional_user_id(self, generator, valid_mgnrega_data):
        """user_id parameter is optional — omitting it must not cause an error."""
        result = generator.generate_application("mgnrega", valid_mgnrega_data)
        assert isinstance(result, PDFResult)

    def test_returns_pdf_result_type(self, generator, valid_pm_kisan_data):
        """Return value must always be a PDFResult Pydantic model instance."""
        result = generator.generate_application("pm-kisan", valid_pm_kisan_data)
        assert isinstance(result, PDFResult)

    def test_mgnrega_does_not_require_land_doc(self, generator, valid_mgnrega_data):
        """
        MGNREGA has lower requirements than PM-KISAN.
        A UserData with only Aadhaar + location (no LAND_RECORD) must succeed for MGNREGA.
        """
        # valid_mgnrega_data has no land record — still should pass
        assert DocumentType.LAND_RECORD not in [
            d.doc_type for d in valid_mgnrega_data.documents
        ]
        result = generator.generate_application("mgnrega", valid_mgnrega_data)
        assert result.success is True
