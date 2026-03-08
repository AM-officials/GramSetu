"""
GramSetu — Core Data Models (Single-Table DynamoDB Design)

This module defines all Pydantic models that act as the contract between
every Lambda function in the GramSetu pipeline. No boto3 is imported here —
these are pure data-structure definitions ready for any storage backend.

Single-Table Design
───────────────────
Table name  : gramsetu-conversations  (from .env: DYNAMODB_TABLE_CONVERSATIONS)
Primary Key : PK (S) + SK (S)

┌─────────────────────────┬──────────────────────────────┬───────────────┬──────────────────┐
│ Entity                  │ PK                           │ SK            │ GSI1 (scheme list)│
├─────────────────────────┼──────────────────────────────┼───────────────┼──────────────────┤
│ UserProfile             │ USER#<phone>                 │ PROFILE       │ —                │
│ ConversationState       │ USER#<phone>                 │ STATE         │ —                │
│ ProcessedDocumentRecord │ USER#<phone>                 │ DOC#<type>#<ts>│ —               │
│ GovernmentScheme        │ SCHEME#<id>                  │ METADATA      │ SCHEMES / ACTIVE# │
└─────────────────────────┴──────────────────────────────┴───────────────┴──────────────────┘

Query patterns supported:
  - Get profile            : PK=USER#<phone>, SK=PROFILE
  - Get conversation state : PK=USER#<phone>, SK=STATE
  - List user documents    : PK=USER#<phone>, SK begins_with DOC#
  - Get scheme             : PK=SCHEME#<id>, SK=METADATA
  - List active schemes    : GSI1PK=SCHEMES, GSI1SK begins_with ACTIVE#

Refs: design.md §"Data Models", §"Government Scheme Models"
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from src.shared.types import ConversationStep, DocumentType, SupportedLanguage


# ═══════════════════════════════════════════════════════════════════
# SECTION 1 — Supporting (embedded) models — no PK/SK needed
# ═══════════════════════════════════════════════════════════════════


class Location(BaseModel):
    """Geographic location information, coarse-grained for rural India."""
    state: str
    district: str
    village: Optional[str] = None
    block: Optional[str] = None          # administrative sub-district
    pincode: Optional[str] = None


class PersonalInfo(BaseModel):
    """Basic personal details extracted from voice/document processing."""
    full_name: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None         # male / female / other
    aadhaar_last4: Optional[str] = None  # Only last 4 digits stored for security


class FamilyMember(BaseModel):
    """A single member of the applicant's family."""
    name: str
    age: int
    gender: str
    relation: str                         # e.g. "spouse", "son", "daughter"


class FamilyInfo(BaseModel):
    """Household / family composition."""
    size: int = 1
    head_of_family: Optional[str] = None
    members: List[FamilyMember] = Field(default_factory=list)


class IncomeInfo(BaseModel):
    """Annual income details for scheme eligibility checks."""
    annual_income_inr: Optional[int] = None
    income_source: Optional[str] = None  # e.g. "agriculture", "labour", "business"
    bpl_card_number: Optional[str] = None
    bpl_category: Optional[str] = None   # e.g. "AAY", "PHH"


class ProcessedDocument(BaseModel):
    """
    A document whose text has been extracted by the Document Processor.
    This is an *embedded* model stored inside ConversationState.collected_data;
    for long-term persistence each document gets its own DynamoDB row
    (see ProcessedDocumentRecord below).
    """
    doc_type: DocumentType
    extracted_data: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    image_s3_key: str
    processed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PendingConfirmation(BaseModel):
    """
    A single data point awaiting explicit user confirmation.
    The AI Reasoner generates these before creating a PDF.
    """
    field_name: str           # e.g. "personal_info.full_name"
    display_label: str        # Human-readable label in the user's language
    current_value: Any        # The extracted or inferred value
    confirmed_by_user: bool = False
    confirmed_at: Optional[datetime] = None


class AgeRange(BaseModel):
    """Inclusive age range for scheme eligibility."""
    min_age: int = Field(ge=0)
    max_age: int = Field(le=120)

    @field_validator("max_age")
    @classmethod
    def max_must_exceed_min(cls, v: int, info) -> int:
        if "min_age" in info.data and v < info.data["min_age"]:
            raise ValueError(f"max_age ({v}) must be >= min_age ({info.data['min_age']})")
        return v


class EligibilityCriteria(BaseModel):
    """
    Rules that determine whether a user qualifies for a government scheme.
    All fields are Optional — a None value means "no restriction on this axis".
    """
    income_limit_inr: Optional[int] = None
    age_range: Optional[AgeRange] = None
    allowed_states: Optional[List[str]] = None   # None = all states
    min_family_size: Optional[int] = None
    required_documents: List[DocumentType] = Field(default_factory=list)
    gender_restriction: Optional[str] = None     # None = all genders
    caste_categories: Optional[List[str]] = None # e.g. ["SC", "ST", "OBC"]


class UserData(BaseModel):
    """
    Aggregated user data collected during a GramSetu conversation.
    All sub-objects are Optional to support incremental collection —
    the AI Reasoner fills these in one conversation turn at a time.
    """
    personal_info: Optional[PersonalInfo] = None
    documents: List[ProcessedDocument] = Field(default_factory=list)
    income: Optional[IncomeInfo] = None
    family: Optional[FamilyInfo] = None
    location: Optional[Location] = None


# ═══════════════════════════════════════════════════════════════════
# SECTION 2 — DynamoDB model base
# ═══════════════════════════════════════════════════════════════════

_STRIP_KEYS: ClassVar[frozenset] = frozenset({"PK", "SK", "GSI1PK", "GSI1SK"})


class DynamoModel(BaseModel):
    """
    Abstract base for all entities that live in the DynamoDB table.

    Subclasses MUST override `pk` and `sk` properties.

    Serialization contract:
    - `to_dynamo_item()` → dict suitable for DynamoDB PutItem / UpdateItem
    - `from_dynamo_item(item)` → model instance reconstructed from a GetItem result
    """

    # ── Key properties (override in subclasses) ──────────────────

    @property
    def pk(self) -> str:  # pragma: no cover
        raise NotImplementedError("Subclasses must implement `pk`")

    @property
    def sk(self) -> str:  # pragma: no cover
        raise NotImplementedError("Subclasses must implement `sk`")

    # ── Optional GSI keys (override in subclasses that use a GSI) ─

    @property
    def gsi1pk(self) -> Optional[str]:
        return None

    @property
    def gsi1sk(self) -> Optional[str]:
        return None

    # ── Serialization helpers ─────────────────────────────────────

    def to_dynamo_item(self) -> Dict[str, Any]:
        """
        Return a flat dict ready to be written to DynamoDB.
        - Datetimes are serialized as ISO 8601 strings.
        - Enums are serialized as their string values.
        - PK / SK (and optional GSI keys) are injected.
        """
        item: Dict[str, Any] = self.model_dump(mode="json")
        item["PK"] = self.pk
        item["SK"] = self.sk
        if self.gsi1pk is not None:
            item["GSI1PK"] = self.gsi1pk
        if self.gsi1sk is not None:
            item["GSI1SK"] = self.gsi1sk
        return item

    @classmethod
    def from_dynamo_item(cls, item: Dict[str, Any]) -> "DynamoModel":
        """
        Reconstruct a model from a raw DynamoDB item dict.
        Strips PK, SK, and any GSI keys before validation.
        """
        clean = {k: v for k, v in item.items() if k not in _STRIP_KEYS}
        return cls.model_validate(clean)


# ═══════════════════════════════════════════════════════════════════
# SECTION 3 — Table entities
# ═══════════════════════════════════════════════════════════════════


class UserProfile(DynamoModel):
    """
    Core user record — the long-lived profile that persists across sessions.

    DynamoDB key:
      PK = USER#<phone_number>   (e.g. USER#919876543210)
      SK = PROFILE
    """

    phone_number: str            # E.164 without "+" prefix, e.g. "919876543210"
    preferred_language: SupportedLanguage = SupportedLanguage.HINDI
    name: Optional[str] = None
    location: Optional[Location] = None
    eligible_schemes: List[str] = Field(default_factory=list)   # scheme IDs
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_active: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # ── DynamoDB keys ─────────────────────────────────────────────

    @property
    def pk(self) -> str:
        return f"USER#{self.phone_number}"

    @property
    def sk(self) -> str:
        return "PROFILE"


class ConversationState(DynamoModel):
    """
    Ephemeral conversation state for an ongoing GramSetu session.
    Stored separately from UserProfile so it can be updated frequently
    without touching the authoritative profile record.

    DynamoDB key:
      PK = USER#<phone_number>
      SK = STATE
    """

    user_id: str                  # phone_number — mirrors UserProfile.phone_number
    current_step: ConversationStep = ConversationStep.WELCOME
    target_scheme: Optional[str] = None    # scheme ID the user is applying for
    collected_data: UserData = Field(default_factory=UserData)
    pending_confirmations: List[PendingConfirmation] = Field(default_factory=list)
    retry_count: int = 0
    last_message_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    preferred_language: SupportedLanguage = SupportedLanguage.HINDI

    # ── DynamoDB keys ─────────────────────────────────────────────

    @property
    def pk(self) -> str:
        return f"USER#{self.user_id}"

    @property
    def sk(self) -> str:
        return "STATE"


class ProcessedDocumentRecord(DynamoModel):
    """
    A persistent record for every document the user has uploaded.
    Stored as a separate row from the profile/state so we can query
    all documents for a user with begins_with(SK, "DOC#").

    DynamoDB key:
      PK = USER#<phone_number>
      SK = DOC#<doc_type>#<iso_timestamp_utc>
    """

    phone_number: str
    doc_type: DocumentType
    extracted_data: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    image_s3_key: str             # path within the S3 bucket (or local storage)
    is_verified: bool = False     # True after AI Reasoner confirms the extracted data
    processed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # ── DynamoDB keys ─────────────────────────────────────────────

    @property
    def pk(self) -> str:
        return f"USER#{self.phone_number}"

    @property
    def sk(self) -> str:
        # ISO 8601 timestamp ensures lexicographic sort == chronological sort
        ts = self.processed_at.strftime("%Y-%m-%dT%H:%M:%S")
        return f"DOC#{self.doc_type.value}#{ts}"


class GovernmentScheme(DynamoModel):
    """
    Describes a single government scheme including eligibility rules,
    required documents, and localized names/descriptions.

    DynamoDB key:
      PK     = SCHEME#<scheme_id>
      SK     = METADATA
      GSI1PK = SCHEMES                         (for listing all schemes)
      GSI1SK = ACTIVE#<scheme_id>              (is_active=True)
               INACTIVE#<scheme_id>            (is_active=False)
    """

    scheme_id: str                                  # URL-safe slug, e.g. "pmay", "pm-kisan"
    name: str                                       # Canonical English name
    name_translations: Dict[str, str] = Field(      # keyed by BCP-47 code
        default_factory=dict,
        description="e.g. {'hi-IN': 'प्रधानमंत्री आवास योजना'}"
    )
    description: str
    description_translations: Dict[str, str] = Field(default_factory=dict)
    eligibility_criteria: EligibilityCriteria = Field(default_factory=EligibilityCriteria)
    required_documents: List[DocumentType] = Field(default_factory=list)
    application_template: str = ""          # template name / S3 key for the PDF template
    benefits: List[str] = Field(default_factory=list)
    application_deadline: Optional[datetime] = None
    is_active: bool = True
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # ── DynamoDB keys ─────────────────────────────────────────────

    @property
    def pk(self) -> str:
        return f"SCHEME#{self.scheme_id}"

    @property
    def sk(self) -> str:
        return "METADATA"

    # ── GSI keys for listing all schemes ──────────────────────────

    @property
    def gsi1pk(self) -> str:
        return "SCHEMES"

    @property
    def gsi1sk(self) -> str:
        status = "ACTIVE" if self.is_active else "INACTIVE"
        return f"{status}#{self.scheme_id}"
