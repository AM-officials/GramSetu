"""
GramSetu — Document Processor Tests

Validates DocumentProcessor.process_document() from src/document_processor/processor.py.

Requirements verified:
  Req 2.1 — Textract processing path returns structured ExtractionResult
  Req 2.2 — 'blurry' / 'dark' URLs trigger image quality error with retry guidance
  Req 2.4 — All supported doc types: Aadhaar, Income Cert, Land Record, Ration Card, Bank Passbook
  Req 2.5 — Confidence >= 0.85 for all critical document types

Test Classes:
  TestImageQualityErrors           — blurry / dark URL edge cases (Req 2.2)
  TestAadhaarExtraction            — Aadhaar-specific data fields and types (Req 2.4)
  TestIncomeCertificateExtraction  — income certificate fields (Req 2.4)
  TestLandRecordExtraction         — land record fields including Khasra (Req 2.4)
  TestOtherDocumentTypes           — ration card, bank passbook, caste certificate
  TestExtractionResultContract     — return type shape, ProcessedDocument usage
"""
import pytest

from src.shared.db_models import ProcessedDocument
from src.shared.types import DocumentType
from src.document_processor.processor import (
    DocumentProcessor,
    ExtractionResult,
    ImageQualityIssue,
)


@pytest.fixture(scope="module")
def processor() -> DocumentProcessor:
    return DocumentProcessor()


# ─────────────────────────────────────────────────────────────────
# 1. TestImageQualityErrors  (Req 2.2)
# ─────────────────────────────────────────────────────────────────

class TestImageQualityErrors:

    def test_blurry_url_returns_failure(self, processor):
        """'blurry' in URL must produce success=False. (Req 2.2)"""
        result = processor.process_document("s3://bucket/uploads/blurry_aadhaar.jpg")
        assert result.success is False

    def test_dark_url_returns_failure(self, processor):
        """'dark' in URL must produce success=False. (Req 2.2)"""
        result = processor.process_document("s3://bucket/uploads/dark_income_cert.jpg")
        assert result.success is False

    def test_blurry_has_retry_guidance(self, processor):
        """Image quality failure must include non-empty retry guidance. (Req 2.2)"""
        result = processor.process_document("uploads/blurry_doc.jpg")
        assert result.quality_assessment is not None
        assert result.quality_assessment.retry_guidance is not None
        assert len(result.quality_assessment.retry_guidance) > 0

    def test_dark_has_retry_guidance(self, processor):
        """Dark image failure must include non-empty retry guidance."""
        result = processor.process_document("uploads/dark_photo.jpg")
        assert result.quality_assessment is not None
        assert result.quality_assessment.retry_guidance is not None

    def test_blurry_guidance_mentions_steady(self, processor):
        """Guidance for blurry photos must advise steadying the phone."""
        result = processor.process_document("test/blurry_scan.jpg")
        guidance = result.quality_assessment.retry_guidance.lower()
        assert "still" in guidance or "steady" in guidance or "हिलाएँ" in guidance

    def test_dark_guidance_mentions_light(self, processor):
        """Guidance for dark photos must advise better lighting."""
        result = processor.process_document("test/dark_scan.jpg")
        guidance = result.quality_assessment.retry_guidance.lower()
        assert "light" in guidance or "रोशनी" in guidance or "lit" in guidance

    def test_quality_error_has_no_processed_document(self, processor):
        """No ProcessedDocument should be created for a quality-failed image."""
        result = processor.process_document("uploads/blurry_aadhaar.jpg")
        assert result.processed_document is None

    def test_quality_error_confidence_is_zero(self, processor):
        """Confidence must be 0.0 when image is rejected. (Req 2.5 inverse)"""
        result = processor.process_document("uploads/blurry.jpg")
        assert result.confidence == 0.0

    def test_quality_errors_list_populated(self, processor):
        """quality_assessment.issues must contain at least one ImageQualityIssue."""
        result = processor.process_document("uploads/blurry.jpg")
        assert len(result.quality_assessment.issues) > 0
        assert ImageQualityIssue.BLURRY in result.quality_assessment.issues

    def test_blurry_overrides_document_type(self, processor):
        """
        Quality check runs before type detection.
        'blurry_aadhaar' URL should return quality error, not Aadhaar data.
        """
        result = processor.process_document("uploads/blurry_aadhaar_front.jpg")
        assert result.success is False
        assert result.processed_document is None


# ─────────────────────────────────────────────────────────────────
# 2. TestAadhaarExtraction  (Req 2.4 — Aadhaar)
# ─────────────────────────────────────────────────────────────────

class TestAadhaarExtraction:

    @pytest.fixture(scope="class")
    def aadhaar_result(self, processor) -> ExtractionResult:
        return processor.process_document("s3://bucket/uploads/aadhaar_front.jpg")

    def test_aadhaar_success(self, aadhaar_result):
        """Aadhaar URL must produce success=True. (Req 2.4)"""
        assert aadhaar_result.success is True

    def test_aadhaar_doc_type(self, aadhaar_result):
        """document_type must be AADHAAR."""
        assert aadhaar_result.document_type == DocumentType.AADHAAR

    def test_aadhaar_has_name(self, aadhaar_result):
        """Extracted data must include 'name' field."""
        assert "name" in aadhaar_result.extracted_data
        assert len(aadhaar_result.extracted_data["name"]) > 0

    def test_aadhaar_has_last4(self, aadhaar_result):
        """Extracted data must include 'aadhaar_last4' (only last 4 digits stored)."""
        assert "aadhaar_last4" in aadhaar_result.extracted_data
        assert len(aadhaar_result.extracted_data["aadhaar_last4"]) == 4

    def test_aadhaar_has_dob(self, aadhaar_result):
        """Extracted data must include 'dob' field."""
        assert "dob" in aadhaar_result.extracted_data

    def test_aadhaar_has_gender(self, aadhaar_result):
        """Extracted data must include 'gender' field."""
        assert "gender" in aadhaar_result.extracted_data

    def test_aadhaar_confidence_above_threshold(self, aadhaar_result):
        """Confidence must be >= 0.85 (Req 2.5 critical field threshold)."""
        assert aadhaar_result.confidence >= 0.85

    def test_aadhaar_has_processed_document(self, aadhaar_result):
        """ExtractionResult must include a populated ProcessedDocument."""
        assert aadhaar_result.processed_document is not None

    def test_aadhaar_processed_document_type_matches(self, aadhaar_result):
        """ProcessedDocument.doc_type must equal DocumentType.AADHAAR."""
        assert aadhaar_result.processed_document.doc_type == DocumentType.AADHAAR

    def test_aadhaar_no_full_number_exposed(self, aadhaar_result):
        """
        Full Aadhaar number must NOT be stored — only last 4 digits.
        Privacy requirement: UIDAI mandates partial masking.
        """
        data = aadhaar_result.extracted_data
        # The masked version is acceptable; the raw 12-digit number should not appear
        assert "aadhaar_number" not in data or "XXXX" in str(data.get("aadhaar_number_masked", ""))


# ─────────────────────────────────────────────────────────────────
# 3. TestIncomeCertificateExtraction  (Req 2.4 — Income Certificate)
# ─────────────────────────────────────────────────────────────────

class TestIncomeCertificateExtraction:

    @pytest.fixture(scope="class")
    def income_result(self, processor) -> ExtractionResult:
        return processor.process_document("s3://bucket/uploads/income_certificate_2024.jpg")

    def test_income_success(self, income_result):
        """Income certificate URL must produce success=True."""
        assert income_result.success is True

    def test_income_doc_type(self, income_result):
        """document_type must be INCOME_CERTIFICATE."""
        assert income_result.document_type == DocumentType.INCOME_CERTIFICATE

    def test_income_has_name(self, income_result):
        """Extracted data must include 'name' field."""
        assert "name" in income_result.extracted_data

    def test_income_has_annual_income(self, income_result):
        """Extracted data must include 'annual_income_inr' as integer."""
        assert "annual_income_inr" in income_result.extracted_data
        assert isinstance(income_result.extracted_data["annual_income_inr"], int)

    def test_income_has_issuing_authority(self, income_result):
        """Extracted data must include the off the issuing authority."""
        assert "issuing_authority" in income_result.extracted_data

    def test_income_confidence_above_threshold(self, income_result):
        """Confidence must be >= 0.85. (Req 2.5)"""
        assert income_result.confidence >= 0.85


# ─────────────────────────────────────────────────────────────────
# 4. TestLandRecordExtraction  (Req 2.4 — Land Record)
# ─────────────────────────────────────────────────────────────────

class TestLandRecordExtraction:

    @pytest.fixture(scope="class")
    def land_result(self, processor) -> ExtractionResult:
        return processor.process_document("uploads/land_record_khasra.jpg")

    def test_land_success(self, land_result):
        """Land record URL must produce success=True."""
        assert land_result.success is True

    def test_land_doc_type(self, land_result):
        """document_type must be LAND_RECORD."""
        assert land_result.document_type == DocumentType.LAND_RECORD

    def test_land_has_khasra_number(self, land_result):
        """Extracted data must include 'khasra_number' — required for PM-KISAN."""
        assert "khasra_number" in land_result.extracted_data

    def test_land_has_owner_name(self, land_result):
        """Extracted data must include 'owner_name'."""
        assert "owner_name" in land_result.extracted_data

    def test_land_has_area(self, land_result):
        """Extracted data must include land area measurement."""
        assert "area_bigha" in land_result.extracted_data or "area_sqft" in land_result.extracted_data

    def test_land_confidence_above_threshold(self, land_result):
        """Confidence must be >= 0.85. (Req 2.5)"""
        assert land_result.confidence >= 0.85

    def test_khasra_alias_resolves_to_land_record(self, processor):
        """URL with 'khasra' keyword must also resolve to LAND_RECORD document type."""
        result = processor.process_document("s3://bucket/uploads/khasra_234B.jpg")
        assert result.document_type == DocumentType.LAND_RECORD


# ─────────────────────────────────────────────────────────────────
# 5. TestOtherDocumentTypes  (Req 2.4 — Ration Card, Bank Passbook)
# ─────────────────────────────────────────────────────────────────

class TestOtherDocumentTypes:

    def test_ration_card_success(self, processor):
        """'ration' URL must produce success=True."""
        result = processor.process_document("uploads/ration_card_photo.jpg")
        assert result.success is True

    def test_ration_card_doc_type(self, processor):
        """document_type must be RATION_CARD."""
        result = processor.process_document("uploads/ration_card.jpg")
        assert result.document_type == DocumentType.RATION_CARD

    def test_ration_has_card_number(self, processor):
        """Ration card must include card number."""
        result = processor.process_document("uploads/ration.jpg")
        assert "ration_card_number" in result.extracted_data

    def test_bank_passbook_success(self, processor):
        """'bank' URL must produce success=True."""
        result = processor.process_document("uploads/bank_passbook_front.jpg")
        assert result.success is True

    def test_bank_passbook_doc_type(self, processor):
        """document_type must be BANK_PASSBOOK."""
        result = processor.process_document("uploads/bank_passbook.jpg")
        assert result.document_type == DocumentType.BANK_PASSBOOK

    def test_bank_has_ifsc(self, processor):
        """Bank passbook must include IFSC code (needed for direct benefit transfer)."""
        result = processor.process_document("uploads/bank_passbook.jpg")
        assert "ifsc_code" in result.extracted_data

    def test_bank_has_account_last4(self, processor):
        """Bank passbook must include last 4 of account number (not full number)."""
        result = processor.process_document("uploads/bank_passbook.jpg")
        assert "account_number_last4" in result.extracted_data

    def test_passbook_alias_resolves(self, processor):
        """'passbook' keyword must also resolve to BANK_PASSBOOK."""
        result = processor.process_document("uploads/passbook_scan.jpg")
        assert result.document_type == DocumentType.BANK_PASSBOOK


# ─────────────────────────────────────────────────────────────────
# 6. TestExtractionResultContract
# ─────────────────────────────────────────────────────────────────

class TestExtractionResultContract:

    def test_processed_document_is_correct_type(self, processor):
        """processed_document must be an instance of the shared ProcessedDocument model."""
        result = processor.process_document("uploads/aadhaar_scan.jpg")
        assert isinstance(result.processed_document, ProcessedDocument)

    def test_processed_document_s3_key_matches_url(self, processor):
        """image_s3_key in ProcessedDocument must match the input image_url."""
        url = "s3://bucket/user/919876543210/aadhaar_001.jpg"
        result = processor.process_document(url)
        assert result.processed_document.image_s3_key == url

    def test_processed_document_has_timestamp(self, processor):
        """ProcessedDocument must have a processed_at datetime."""
        result = processor.process_document("uploads/aadhaar.jpg")
        assert result.processed_document.processed_at is not None

    def test_user_id_accepted_without_error(self, processor):
        """process_document must accept an optional user_id without error."""
        result = processor.process_document(
            image_url="uploads/aadhaar.jpg",
            user_id="919876543210",
        )
        assert isinstance(result, ExtractionResult)

    def test_success_result_has_empty_errors_list(self, processor):
        """Successful extraction must have an empty errors list."""
        result = processor.process_document("uploads/aadhaar.jpg")
        assert result.errors == []

    def test_failure_result_has_non_empty_errors(self, processor):
        """Quality failure must populate the errors list."""
        result = processor.process_document("uploads/blurry_doc.jpg")
        assert len(result.errors) > 0

    def test_confidence_in_valid_range(self, processor):
        """Confidence must always be in [0.0, 1.0] for both success and failure."""
        for url in ["uploads/aadhaar.jpg", "uploads/blurry.jpg", "uploads/income.jpg"]:
            result = processor.process_document(url)
            assert 0.0 <= result.confidence <= 1.0, f"Confidence out of range for {url}"
