"""
GramSetu — PDF Generator

This module implements the PDF_Generator component from requirements.md §Req-4.
It is the final step of the GramSetu user journey — it validates all collected data,
then (in this mock) simulates creating a pre-filled government PDF.

Public API
──────────
PDFGenerator.generate_application(scheme_type, user_data, user_id="") → PDFResult

Internal pipeline
─────────────────
1. _validate()        — per-scheme field completeness check (returns missing_fields list)
2. _build_pdf()       — mock S3 placement; real impl uses WeasyPrint / Pillow + S3 upload
3. _get_instructions()— bilingual submission instructions for the specific office

Scheme templates supported (Req 4.5 — at least 3):
  pm-kisan   : PM Kisan Samman Nidhi  (5 required fields + LAND_RECORD doc)
  pmay       : PM Awas Yojana          (5 required fields + INCOME_CERTIFICATE doc)
  mgnrega    : MGNREGA Job Card        (3 required fields)
  pm-jan-dhan: PM Jan Dhan Yojana      (3 required fields)

Validation rule (Req 4.1): ALL required fields must be non-None.
If any are missing, generate_application() returns PDFResult(success=False, missing_fields=[...])
and the AI Reasoner can use `missing_fields` to ask targeted follow-up questions.

Swap-in path for production
───────────────────────────
Replace `_build_pdf()` with:
  1. Pull the form template from S3 (e.g., templates/pm-kisan-form-2024.pdf)
  2. Use PyMuPDF / WeasyPrint to fill form fields by ID (matching design.md field IDs)
  3. Upload the filled PDF to s3://gramsetu-forms/generated/<user_id>/<scheme>.pdf
  4. Generate a pre-signed URL for 24-hour download

Refs: design.md §"PDF Generator Lambda", requirements.md §Req-4
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from src.shared.db_models import UserData
from src.shared.types import DocumentType


# ═══════════════════════════════════════════════════════════════════
# Result model
# ═══════════════════════════════════════════════════════════════════


class PDFResult(BaseModel):
    """
    Output of PDFGenerator.generate_application().

    On success : success=True, pdf_s3_url set, submission_instructions populated.
    On failure : success=False, missing_fields explains what data is still needed.
    On unknown : success=False, errors list populated.
    """
    success: bool
    scheme_type: str
    pdf_s3_url: Optional[str] = None            # Populated on success
    submission_instructions: str = ""
    missing_fields: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    generated_at: Optional[datetime] = None


# ═══════════════════════════════════════════════════════════════════
# Validation helpers — pure functions, no side-effects
# ═══════════════════════════════════════════════════════════════════

def _has_name(ud: UserData) -> bool:
    return bool(ud.personal_info and ud.personal_info.full_name)

def _has_aadhaar(ud: UserData) -> bool:
    return bool(ud.personal_info and ud.personal_info.aadhaar_last4)

def _has_income(ud: UserData) -> bool:
    return bool(ud.income and ud.income.annual_income_inr is not None)

def _has_village(ud: UserData) -> bool:
    return bool(ud.location and ud.location.village)

def _has_district(ud: UserData) -> bool:
    return bool(ud.location and ud.location.district)

def _has_state(ud: UserData) -> bool:
    return bool(ud.location and ud.location.state)

def _has_doc(ud: UserData, doc_type: DocumentType) -> bool:
    """Return True if the user has uploaded a document of the given type."""
    return any(doc.doc_type == doc_type for doc in ud.documents)


# ═══════════════════════════════════════════════════════════════════
# Per-scheme validators
# ═══════════════════════════════════════════════════════════════════

def _validate_pm_kisan(user_data: UserData) -> List[str]:
    """
    PM-KISAN requires farmer identity, land ownership, income, and location.
    Missing field labels are human-readable for follow-up questions to the user.
    """
    missing: List[str] = []
    if not _has_name(user_data):
        missing.append("Applicant full name (आवेदक का पूरा नाम)")
    if not _has_aadhaar(user_data):
        missing.append("Aadhaar card last 4 digits (आधार कार्ड)")
    if not _has_income(user_data):
        missing.append("Annual household income in INR (वार्षिक आय)")
    if not _has_village(user_data) or not _has_district(user_data):
        missing.append("Home village and district (गाँव और जिला)")
    if not _has_doc(user_data, DocumentType.LAND_RECORD):
        missing.append("Land ownership record / Khasra photo (ज़मीन का दस्तावेज़)")
    return missing


def _validate_pmay(user_data: UserData) -> List[str]:
    """
    PMAY requires identity, income (eligibility threshold), address, and income certificate.
    """
    missing: List[str] = []
    if not _has_name(user_data):
        missing.append("Applicant full name (आवेदक का पूरा नाम)")
    if not _has_aadhaar(user_data):
        missing.append("Aadhaar card last 4 digits (आधार कार्ड)")
    if not _has_income(user_data):
        missing.append("Annual household income in INR (वार्षिक आय)")
    if not _has_village(user_data) or not _has_district(user_data):
        missing.append("Home village and district (गाँव और जिला)")
    if not _has_state(user_data):
        missing.append("State of residence (राज्य)")
    if not _has_doc(user_data, DocumentType.INCOME_CERTIFICATE):
        missing.append("Income certificate photo (आय प्रमाण पत्र)")
    return missing


def _validate_mgnrega(user_data: UserData) -> List[str]:
    """
    MGNREGA Job Card has lower data requirements — any adult rural resident qualifies.
    """
    missing: List[str] = []
    if not _has_name(user_data):
        missing.append("Applicant full name (आवेदक का पूरा नाम)")
    if not _has_aadhaar(user_data):
        missing.append("Aadhaar card last 4 digits (आधार कार्ड)")
    if not _has_village(user_data) or not _has_district(user_data):
        missing.append("Home village and district in the Gram Panchayat (गाँव और जिला)")
    return missing


def _validate_pm_jan_dhan(user_data: UserData) -> List[str]:
    """
    PM Jan Dhan zero-balance account — minimal data needed.
    """
    missing: List[str] = []
    if not _has_name(user_data):
        missing.append("Applicant full name (आवेदक का पूरा नाम)")
    if not _has_aadhaar(user_data):
        missing.append("Aadhaar card last 4 digits (आधार कार्ड)")
    if not _has_village(user_data):
        missing.append("Home village (गाँव का नाम)")
    return missing


# Map scheme slug → validator
_SCHEME_VALIDATORS: Dict[str, Callable[[UserData], List[str]]] = {
    "pm-kisan":    _validate_pm_kisan,
    "pmkisan":     _validate_pm_kisan,   # alias (no hyphen)
    "pmay":        _validate_pmay,
    "mgnrega":     _validate_mgnrega,
    "pm-jan-dhan": _validate_pm_jan_dhan,
    "jan-dhan":    _validate_pm_jan_dhan,
}


# ═══════════════════════════════════════════════════════════════════
# Submission instructions (bilingual — English + Hindi)
# ═══════════════════════════════════════════════════════════════════

_SUBMISSION_INSTRUCTIONS: Dict[str, str] = {
    "pm-kisan": (
        "📄 PM-KISAN Application — Submission Instructions\n\n"
        "Take this PDF + originals of:\n"
        "  • Aadhaar card\n"
        "  • Land ownership record (Khasra/Patta)\n"
        "  • Bank passbook (for direct benefit transfer)\n\n"
        "Visit: Your nearest Common Service Centre (CSC) / Gram Panchayat office\n"
        "Ask for: 'PM-KISAN Registration'\n"
        "The CSC operator will upload your form to pmkisan.gov.in.\n\n"
        "——\n"
        "📄 पीएम-किसान आवेदन — जमा करने के निर्देश\n\n"
        "यह PDF और मूल दस्तावेज़ साथ लें:\n"
        "  • आधार कार्ड\n"
        "  • ज़मीन का कागज़ (खसरा/पट्टा)\n"
        "  • बैंक पासबुक\n\n"
        "कहाँ जाएं: नज़दीकी जन सेवा केंद्र (CSC) या ग्राम पंचायत कार्यालय\n"
        "क्या मांगें: 'पीएम-किसान पंजीकरण'"
    ),
    "pmay": (
        "📄 PMAY Application — Submission Instructions\n\n"
        "Take this PDF + originals of:\n"
        "  • Aadhaar card\n"
        "  • Income certificate\n"
        "  • Address proof\n\n"
        "Visit: District Collector's office (rural) or\n"
        "       Urban Local Body / Municipality (urban)\n"
        "Ask for: 'PMAY Application' / 'PMAY counter'\n\n"
        "——\n"
        "📄 पीएमएवाई आवेदन — जमा करने के निर्देश\n\n"
        "यह PDF और मूल दस्तावेज़ साथ लें:\n"
        "  • आधार कार्ड\n"
        "  • आय प्रमाण पत्र\n"
        "  • पते का प्रमाण\n\n"
        "कहाँ जाएं: ज़िला कलेक्टर कार्यालय (ग्रामीण) या शहरी स्थानीय निकाय (शहरी)\n"
        "क्या मांगें: 'पीएमएवाई आवेदन काउंटर'"
    ),
    "mgnrega": (
        "📄 MGNREGA Job Card — Submission Instructions\n\n"
        "Take this PDF + originals of:\n"
        "  • Aadhaar card\n"
        "  • Proof of address in the Gram Panchayat area\n\n"
        "Visit: Your Gram Panchayat office\n"
        "Ask for: 'MGNREGA Job Card Application'\n"
        "Your Job Card will be issued within 15 days of submission.\n\n"
        "——\n"
        "📄 मनरेगा जॉब कार्ड — जमा करने के निर्देश\n\n"
        "यह PDF और मूल दस्तावेज़ साथ लें:\n"
        "  • आधार कार्ड\n"
        "  • ग्राम पंचायत क्षेत्र का पता प्रमाण\n\n"
        "कहाँ जाएं: अपनी ग्राम पंचायत का कार्यालय\n"
        "क्या मांगें: 'मनरेगा जॉब कार्ड आवेदन'\n"
        "आवेदन के 15 दिन के भीतर जॉब कार्ड मिलेगा।"
    ),
    "pm-jan-dhan": (
        "📄 PM Jan Dhan Yojana — Submission Instructions\n\n"
        "Take this PDF + original Aadhaar card to:\n"
        "  • Any nationalised bank branch (SBI, Bank of India, PNB, etc.)\n"
        "  • Or your nearest Business Correspondent (Bank Mittra)\n\n"
        "Ask for: 'Jan Dhan Account opening'\n"
        "Your zero-balance account will be opened the same day.\n\n"
        "——\n"
        "📄 पीएम जन धन योजना — जमा करने के निर्देश\n\n"
        "यह PDF और मूल आधार कार्ड लेकर जाएं:\n"
        "  • किसी भी राष्ट्रीयकृत बैंक शाखा (SBI, बैंक ऑफ इंडिया, PNB, आदि)\n"
        "  • या नज़दीकी बैंक मित्र (बिज़नेस कॉरेस्पोंडेंट)\n\n"
        "क्या मांगें: 'जन धन खाता खोलना'\n"
        "उसी दिन शून्य-बैलेंस खाता खुल जाएगा।"
    ),
}


# ═══════════════════════════════════════════════════════════════════
# PDFGenerator
# ═══════════════════════════════════════════════════════════════════


class PDFGenerator:
    """
    Mock implementation of the PDF Generator Lambda.

    Public API
    ──────────
    generate_application(scheme_type, user_data, user_id="") → PDFResult

    Internal pipeline:
    1. Normalise scheme_type slug (lower-case, strip spaces)
    2. Validate user_data completeness for the scheme (per-scheme validator)
    3. If validation passes → build mock S3 URL and return instructions
    4. If validation fails → return PDFResult(success=False, missing_fields=[...])

    Swap-in path for production
    ───────────────────────────
    Replace `_build_pdf()` with a real PDF-filling pipeline:
      • Fetch form template from s3://gramsetu-templates/<scheme>.pdf
      • Use PyMuPDF (fitz) to fill AcroForm fields by ID
      • Upload filled PDF to s3://gramsetu-forms/generated/<user_id>/<scheme>.pdf
      • Generate a 24-hour pre-signed URL for WhatsApp file upload
    """

    # ── Validation ────────────────────────────────────────────────

    def _validate(self, scheme_type: str, user_data: UserData) -> List[str]:
        """
        Invoke the per-scheme validator and return missing field labels.
        Returns an empty list when all required fields are present.
        """
        validator = _SCHEME_VALIDATORS.get(scheme_type)
        if validator is None:
            return []   # Unknown scheme — let the caller handle the error
        return validator(user_data)

    # ── Mock PDF build ────────────────────────────────────────────

    def _build_pdf(self, scheme_type: str, user_data: UserData, user_id: str) -> str:
        """
        Return a mock S3 URL representing the generated PDF.

        Real implementation: fill form template → upload → return presigned URL.
        """
        safe_user = user_id.replace("+", "") if user_id else "anonymous"
        return f"s3://gramsetu-forms/generated/{safe_user}/{scheme_type}.pdf"

    # ── Submission instructions ───────────────────────────────────

    def _get_instructions(self, scheme_type: str) -> str:
        """Return bilingual submission instructions for the given scheme."""
        # Normalise aliases
        canonical = "pm-jan-dhan" if scheme_type in ("jan-dhan",) else scheme_type
        canonical = "pm-kisan" if scheme_type in ("pmkisan",) else canonical
        return _SUBMISSION_INSTRUCTIONS.get(
            canonical,
            (
                "Please take this PDF and your original documents to the nearest "
                "government office or Common Service Centre (CSC).\n\n"
                "कृपया यह PDF और मूल दस्तावेज़ लेकर नज़दीकी सरकारी कार्यालय या "
                "जन सेवा केंद्र (CSC) जाएं।"
            ),
        )

    # ── Public API ────────────────────────────────────────────────

    def generate_application(
        self,
        scheme_type: str,
        user_data: UserData,
        user_id: str = "",
    ) -> PDFResult:
        """
        Validate collected data and (mock-)generate a pre-filled government PDF.

        Parameters
        ──────────
        scheme_type : URL-safe scheme slug, e.g. "pm-kisan", "pmay", "mgnrega".
                      Case-insensitive; leading/trailing whitespace is stripped.
        user_data   : Aggregated user data collected during the GramSetu conversation.
                      Must be a `src.shared.db_models.UserData` instance.
        user_id     : E.164 phone number without "+", used for the S3 path.
                      Optional; defaults to "anonymous" in the mock URL.

        Returns
        ───────
        PDFResult — always returned.
          • success=False + missing_fields  → AI Reasoner asks follow-up questions
          • success=True + pdf_s3_url       → Webhook handler sends PDF via WhatsApp
        """
        scheme_type = scheme_type.strip().lower()

        # Guard: unknown scheme
        if scheme_type not in _SCHEME_VALIDATORS:
            return PDFResult(
                success=False,
                scheme_type=scheme_type,
                errors=[
                    f"Unknown scheme type: '{scheme_type}'. "
                    f"Supported: {sorted(_SCHEME_VALIDATORS.keys())}"
                ],
            )

        # Step 1 — Validate completeness
        missing = self._validate(scheme_type, user_data)
        if missing:
            return PDFResult(
                success=False,
                scheme_type=scheme_type,
                missing_fields=missing,
            )

        # Step 2 — Generate (mock) PDF
        pdf_url = self._build_pdf(scheme_type, user_data, user_id)

        # Step 3 — Build submission instructions
        instructions = self._get_instructions(scheme_type)

        return PDFResult(
            success=True,
            scheme_type=scheme_type,
            pdf_s3_url=pdf_url,
            submission_instructions=instructions,
            generated_at=datetime.now(timezone.utc),
        )


# ─────────────────────────────────────────────────────────────────
# AWS Lambda entry point
# ─────────────────────────────────────────────────────────────────

_generator = PDFGenerator()


def handler(event: dict, context: object) -> dict:
    """
    Lambda handler invoked synchronously by AIReasoner after the user confirms data.

    Expected event shape:
      {
        "scheme_type": "pm-kisan",
        "user_id":     "+919876543210",
        "user_data":   { ... UserData model_dump() ... }
      }

    Returns a JSON-serialisable dict of PDFResult fields.
    WebhookHandler reads pdf_s3_url and sends it via WhatsApp Cloud API.
    """
    scheme_type = event.get("scheme_type", "")
    user_id = event.get("user_id", "")
    user_data_dict = event.get("user_data", {})

    user_data = UserData.model_validate(user_data_dict)
    result = _generator.generate_application(
        scheme_type=scheme_type,
        user_data=user_data,
        user_id=user_id,
    )
    return result.model_dump(mode="json")

