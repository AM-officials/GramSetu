"""
GramSetu — Shared Types
Enumerations and base types derived from design.md, shared across all Lambda components.
"""
from enum import Enum


class MessageType(str, Enum):
    """Types of incoming WhatsApp messages."""
    TEXT = "text"
    AUDIO = "audio"
    IMAGE = "image"
    DOCUMENT = "document"
    STICKER = "sticker"
    UNKNOWN = "unknown"


class ConversationStep(str, Enum):
    """
    States in the GramSetu conversation state machine.

    Flow:
      WELCOME → LANGUAGE_DETECTION → COLLECTING_VOICE
      → COLLECTING_DOCUMENTS → CONFIRMING_DATA
      → GENERATING_PDF → COMPLETED
    """
    WELCOME = "welcome"
    LANGUAGE_DETECTION = "language_detection"
    COLLECTING_VOICE = "collecting_voice"
    COLLECTING_DOCUMENTS = "collecting_documents"
    CONFIRMING_DATA = "confirming_data"
    GENERATING_PDF = "generating_pdf"
    COMPLETED = "completed"
    ERROR = "error"


class DocumentType(str, Enum):
    """Government document types that GramSetu can process."""
    AADHAAR = "aadhaar"
    RATION_CARD = "ration_card"
    INCOME_CERTIFICATE = "income_certificate"
    LAND_RECORD = "land_record"
    BANK_PASSBOOK = "bank_passbook"
    CASTE_CERTIFICATE = "caste_certificate"
    BIRTH_CERTIFICATE = "birth_certificate"
    UNKNOWN = "unknown"


class SupportedLanguage(str, Enum):
    """
    Regional languages supported by GramSetu via AWS Transcribe.
    Values are BCP-47 language codes used by AWS services.
    """
    HINDI = "hi-IN"
    BENGALI = "bn-IN"
    ODIA = "or-IN"
    GUJARATI = "gu-IN"
    MARATHI = "mr-IN"
    ENGLISH_INDIAN = "en-IN"
