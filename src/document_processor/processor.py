"""
GramSetu — Document Photo Processor

This module implements the Document_Processor component from requirements.md §Req-2.
It is a *mock* implementation that simulates AWS Textract behaviour via URL-pattern
inspection — no real AWS calls or image processing is performed.

Public API
──────────
DocumentProcessor.process_document(image_url, user_id="") → ExtractionResult

Internal pipeline
─────────────────
1. _assess_image_quality()  — detect blurry / dark images (Req 2.2)
2. _detect_document_type()  — infer document type from URL hints (Req 2.4)
3. _call_textract()         — return mocked extracted text + confidence (Req 2.1)
4. Build ProcessedDocument  — using the shared db_models.ProcessedDocument class
5. Return ExtractionResult  — wrapping all of the above

Swap-in path for production (step 3 only):
    textract = boto3.client("textract", region_name=os.getenv("AWS_REGION"))
    response = textract.analyze_document(
        Document={"S3Object": {"Bucket": bucket, "Name": s3_key}},
        FeatureTypes=["FORMS", "TABLES"],
    )
    # parse response["Blocks"] → extracted_data dict

Supported document types (Req 2.4):
  AADHAAR, INCOME_CERTIFICATE, LAND_RECORD,
  RATION_CARD, BANK_PASSBOOK, CASTE_CERTIFICATE, BIRTH_CERTIFICATE

Confidence threshold ≥ 0.85 for critical fields (Req 2.5).

Refs: design.md §"Document Photo Processor Lambda", requirements.md §Req-2
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from src.shared.db_models import ProcessedDocument
from src.shared.types import DocumentType


# ═══════════════════════════════════════════════════════════════════
# Result models
# ═══════════════════════════════════════════════════════════════════


class ImageQualityIssue(str, Enum):
    """Specific defect detected in a document photo."""
    BLURRY = "blurry"
    TOO_DARK = "too_dark"
    TOO_BRIGHT = "too_bright"
    PARTIALLY_VISIBLE = "partially_visible"
    GLARE = "glare"


class ImageQualityAssessment(BaseModel):
    """Quality evaluation returned by the pre-flight check."""
    is_acceptable: bool = True
    issues: List[ImageQualityIssue] = Field(default_factory=list)
    retry_guidance: Optional[str] = None


class ExtractionResult(BaseModel):
    """
    Full output of DocumentProcessor.process_document().

    On success : success=True, processed_document is populated, confidence >= 0.85
    On failure : success=False, errors list explains the problem, processed_document is None
    """
    success: bool
    document_type: DocumentType
    extracted_data: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    errors: List[str] = Field(default_factory=list)
    processed_document: Optional[ProcessedDocument] = None
    quality_assessment: Optional[ImageQualityAssessment] = None


# ═══════════════════════════════════════════════════════════════════
# Mock data tables — realistic content for rural India applicant
# ═══════════════════════════════════════════════════════════════════

_MOCK_EXTRACTIONS: Dict[DocumentType, Tuple[Dict[str, Any], float]] = {
    DocumentType.AADHAAR: (
        {
            "aadhaar_number_masked": "XXXX XXXX 3742",
            "aadhaar_last4": "3742",
            "name": "RAMESH KUMAR",
            "dob": "15/08/1980",
            "gender": "Male",
            "address": "Village Dharampur, District Sundargarh, Odisha 770001",
            "pincode": "770001",
        },
        0.92,
    ),
    DocumentType.INCOME_CERTIFICATE: (
        {
            "name": "Ramesh Kumar",
            "father_name": "Shiv Kumar",
            "annual_income_inr": 60000,
            "income_in_words": "Sixty Thousand Rupees Only",
            "issuing_authority": "Tehsildar, Sundargarh",
            "issue_date": "12/01/2024",
            "certificate_number": "INC/SNG/2024/00423",
            "district": "Sundargarh",
            "state": "Odisha",
        },
        0.88,
    ),
    DocumentType.LAND_RECORD: (
        {
            "owner_name": "Ramesh Kumar",
            "khasra_number": "234/B",
            "area_bigha": "2.5",
            "area_sqft": "19602",
            "land_type": "Agricultural",
            "village": "Dharampur",
            "tehsil": "Sundargarh",
            "district": "Sundargarh",
            "state": "Odisha",
            "record_date": "05/03/2023",
        },
        0.85,
    ),
    DocumentType.RATION_CARD: (
        {
            "card_holder_name": "Ramesh Kumar",
            "ration_card_number": "RC-OD-SNG-2019-00234",
            "family_size": 5,
            "category": "PHH",
            "district": "Sundargarh",
            "state": "Odisha",
            "issued_date": "10/06/2019",
        },
        0.90,
    ),
    DocumentType.BANK_PASSBOOK: (
        {
            "account_holder_name": "RAMESH KUMAR",
            "account_number_last4": "7823",
            "bank_name": "Bank of India",
            "branch": "Sundargarh Main Branch",
            "ifsc_code": "BKID0007823",
            "account_type": "Savings",
            "address": "Main Road, Sundargarh, Odisha 770001",
        },
        0.87,
    ),
    DocumentType.CASTE_CERTIFICATE: (
        {
            "name": "Ramesh Kumar",
            "father_name": "Shiv Kumar",
            "caste": "Scheduled Tribe",
            "sub_caste": "Munda",
            "certificate_number": "CC/SNG/2020/00981",
            "issuing_authority": "District Welfare Officer, Sundargarh",
            "issue_date": "14/09/2020",
            "state": "Odisha",
        },
        0.89,
    ),
    DocumentType.BIRTH_CERTIFICATE: (
        {
            "name": "Raju Kumar",
            "father_name": "Ramesh Kumar",
            "mother_name": "Sita Devi",
            "dob": "22/04/2005",
            "birth_place": "CHC Sundargarh",
            "registration_number": "BC/SNG/2005/02341",
            "district": "Sundargarh",
            "state": "Odisha",
        },
        0.91,
    ),
}

# Retry guidance messages for image quality failures
_BLURRY_GUIDANCE = (
    "Your photo is blurry. Please retake it:\n"
    "  • Hold your phone very still — use both hands.\n"
    "  • Ensure bright, even lighting (near a window works well).\n"
    "  • Make sure all 4 corners of the document are visible.\n"
    "  • Tap the document on screen to focus before shooting.\n\n"
    "आपकी फ़ोटो धुंधली है। कृपया दोबारा लें:\n"
    "  • फ़ोन को दोनों हाथों से पकड़ें, हिलाएँ नहीं।\n"
    "  • खिड़की के पास अच्छी रोशनी में फ़ोटो लें।\n"
    "  • दस्तावेज़ के चारों कोने दिखने चाहिए।"
)

_DARK_GUIDANCE = (
    "Your photo is too dark to read. Please retake it:\n"
    "  • Go to a well-lit area — natural daylight is best.\n"
    "  • Turn on a room light or use your phone torch BEHIND the phone.\n"
    "  • Avoid shadows falling on the document.\n\n"
    "आपकी फ़ोटो बहुत अंधेरे में है। कृपया दोबारा लें:\n"
    "  • धूप या तेज़ रोशनी वाली जगह पर जाएँ।\n"
    "  • दस्तावेज़ पर कोई छाया न पड़े।"
)

_GENERIC_QUALITY_GUIDANCE = (
    "The document photo could not be processed. Please retake it in a well-lit area, "
    "holding the phone steady with all corners of the document visible.\n\n"
    "दस्तावेज़ की फ़ोटो स्पष्ट नहीं है। अच्छी रोशनी में, स्थिर हाथों से, "
    "दस्तावेज़ के चारों कोने दिखाकर दोबारा फ़ोटो लें।"
)

# URL hint → document type mapping (case-insensitive)
_DOC_TYPE_HINTS: Dict[str, DocumentType] = {
    "aadhaar": DocumentType.AADHAAR,
    "aadhar": DocumentType.AADHAAR,
    "uid": DocumentType.AADHAAR,
    "income": DocumentType.INCOME_CERTIFICATE,
    "income_cert": DocumentType.INCOME_CERTIFICATE,
    "income_certificate": DocumentType.INCOME_CERTIFICATE,
    "land": DocumentType.LAND_RECORD,
    "khasra": DocumentType.LAND_RECORD,
    "patta": DocumentType.LAND_RECORD,
    "land_record": DocumentType.LAND_RECORD,
    "ration": DocumentType.RATION_CARD,
    "ration_card": DocumentType.RATION_CARD,
    "bank": DocumentType.BANK_PASSBOOK,
    "passbook": DocumentType.BANK_PASSBOOK,
    "bank_passbook": DocumentType.BANK_PASSBOOK,
    "caste": DocumentType.CASTE_CERTIFICATE,
    "caste_cert": DocumentType.CASTE_CERTIFICATE,
    "birth": DocumentType.BIRTH_CERTIFICATE,
    "birth_cert": DocumentType.BIRTH_CERTIFICATE,
}


# ═══════════════════════════════════════════════════════════════════
# DocumentProcessor
# ═══════════════════════════════════════════════════════════════════


class DocumentProcessor:
    """
    Mock implementation of the Document Photo Processor Lambda.

    Public API
    ──────────
    process_document(image_url, user_id="") → ExtractionResult

    Internal pipeline (all private, replacing real AWS Textract calls):
    1. _assess_image_quality  — Req 2.2: detect blurry / dark images
    2. _detect_document_type  — Req 2.4: identify document from URL hints
    3. _call_textract         — Req 2.1: return mocked extracted fields + confidence

    Swap-in path for production
    ───────────────────────────
    Replace `_call_textract()` body with actual boto3 Textract call.
    `_assess_image_quality()` can be replaced with a pre-flight Rekognition
    image quality check (DetectLabels → look for "blurry", "dark" labels).
    All Pydantic result types and the public interface remain unchanged.
    """

    # ── Internal helpers ──────────────────────────────────────────

    def _assess_image_quality(self, image_url: str) -> ImageQualityAssessment:
        """
        Check the image URL for quality-indicator keywords.

        Real implementation:
          Use Amazon Rekognition DetectLabels or a custom quality-scoring
          model deployed on SageMaker / Lambda to assess sharpness, brightness,
          and document visibility before sending to Textract.
        """
        url_lower = image_url.lower()
        issues: List[ImageQualityIssue] = []
        guidance: Optional[str] = None

        if "blurry" in url_lower or "blur" in url_lower or "shaky" in url_lower:
            issues.append(ImageQualityIssue.BLURRY)
            guidance = _BLURRY_GUIDANCE

        if "dark" in url_lower or "night" in url_lower or "dim" in url_lower:
            issues.append(ImageQualityIssue.TOO_DARK)
            guidance = _DARK_GUIDANCE if guidance is None else _GENERIC_QUALITY_GUIDANCE

        if "glare" in url_lower or "bright" in url_lower or "overexposed" in url_lower:
            issues.append(ImageQualityIssue.GLARE)
            guidance = guidance or _GENERIC_QUALITY_GUIDANCE

        if "partial" in url_lower or "cut" in url_lower or "cropped" in url_lower:
            issues.append(ImageQualityIssue.PARTIALLY_VISIBLE)
            guidance = guidance or _GENERIC_QUALITY_GUIDANCE

        if issues:
            return ImageQualityAssessment(
                is_acceptable=False,
                issues=issues,
                retry_guidance=guidance or _GENERIC_QUALITY_GUIDANCE,
            )

        return ImageQualityAssessment()   # is_acceptable=True by default

    def _detect_document_type(self, image_url: str) -> DocumentType:
        """
        Infer the document type from URL keywords.

        Real implementation:
          AWS Textract AnalyzeID API for Aadhaar / PAN detection.
          A downstream classification model for other document types.
        """
        url_lower = image_url.lower()
        for hint, doc_type in _DOC_TYPE_HINTS.items():
            if hint in url_lower:
                return doc_type
        # Default: Aadhaar is the most commonly uploaded first document
        return DocumentType.AADHAAR

    def _call_textract(
        self,
        image_url: str,
        doc_type: DocumentType,
    ) -> Tuple[Dict[str, Any], float]:
        """
        Return (extracted_data_dict, confidence_float) for the given document type.

        Real implementation:
          response = textract_client.analyze_document(
              Document={"S3Object": {"Bucket": bucket, "Name": s3_key}},
              FeatureTypes=["FORMS", "TABLES"],
          )
          # Parse response["Blocks"] to reconstruct key-value pairs.
        """
        if doc_type in _MOCK_EXTRACTIONS:
            return _MOCK_EXTRACTIONS[doc_type]
        # Fallback: generic unknown document
        return (
            {"raw_text": "Document text could not be fully parsed.", "doc_type_hint": doc_type.value},
            0.50,
        )

    # ── Public API ────────────────────────────────────────────────

    def process_document(self, image_url: str, user_id: str = "") -> ExtractionResult:
        """
        Full document processing pipeline: quality check → type detection → text extraction.

        Parameters
        ──────────
        image_url : URL (S3 presigned URL or local path) of the document image.
                    In this mock, URL substrings drive the response:
                      'blurry' / 'dark'  → image quality error (Req 2.2)
                      'aadhaar'          → Aadhaar extraction    (Req 2.4)
                      'income'           → Income certificate    (Req 2.4)
                      'land' / 'khasra'  → Land record           (Req 2.4)
                      'ration'           → Ration card           (Req 2.4)
                      'bank' / 'passbook'→ Bank passbook         (Req 2.4)
                      any other URL      → Aadhaar (default)
        user_id   : Phone number of the requesting user (reserved for audit logging).

        Returns
        ───────
        ExtractionResult — always returned; inspect `success` first.
        """

        # Step 1 — Image quality gate (Req 2.2)
        quality = self._assess_image_quality(image_url)
        if not quality.is_acceptable:
            return ExtractionResult(
                success=False,
                document_type=DocumentType.UNKNOWN,
                confidence=0.0,
                errors=[
                    f"Image quality issues detected: {[i.value for i in quality.issues]}. "
                    f"Please retake the photo."
                ],
                quality_assessment=quality,
            )

        # Step 2 — Document type identification
        doc_type = self._detect_document_type(image_url)

        # Step 3 — Text extraction (mock AWS Textract call)
        extracted_data, confidence = self._call_textract(image_url, doc_type)

        # Step 4 — Build ProcessedDocument (from shared db_models)
        processed_doc = ProcessedDocument(
            doc_type=doc_type,
            extracted_data=extracted_data,
            confidence=confidence,
            image_s3_key=image_url,       # In production: the S3 key after upload
            processed_at=datetime.now(timezone.utc),
        )

        # Step 5 — Return ExtractionResult
        return ExtractionResult(
            success=True,
            document_type=doc_type,
            extracted_data=extracted_data,
            confidence=confidence,
            errors=[],
            processed_document=processed_doc,
            quality_assessment=quality,
        )


# ─────────────────────────────────────────────────────────────────
# AWS Lambda entry point
# ─────────────────────────────────────────────────────────────────

_processor = DocumentProcessor()


def handler(event: dict, context: object) -> dict:
    """
    Lambda handler invoked asynchronously by WebhookHandler.

    Expected event shape:
      {
        "image_url": "s3://gramsetu-media-<account>-<env>/incoming/<phone>/<id>.jpg",
        "user_id":   "+919876543210"
      }

    Returns a JSON-serialisable dict of ExtractionResult fields.
    The AI Reasoner Lambda is invoked next with the extracted data.
    """
    image_url = event.get("image_url", "")
    user_id = event.get("user_id", "")
    result = _processor.process_document(image_url=image_url, user_id=user_id)
    return result.model_dump(mode="json")

