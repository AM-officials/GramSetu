"""
GramSetu — Data Model Tests

Validates:
  1. PK / SK key generation for every table entity
  2. DynamoDB item serialization (to_dynamo_item)
  3. Round-trip fidelity (to_dynamo_item → from_dynamo_item)
  4. Partial UserData (incremental data collection pattern)
  5. ProcessedDocumentRecord SK timestamp format
  6. GovernmentScheme GSI key generation (active vs inactive)
  7. AgeRange cross-field validator
  8. Correct enum types from types.py are used
"""
import re
from datetime import datetime, timezone

import pytest

from src.shared.types import ConversationStep, DocumentType, SupportedLanguage
from src.shared.db_models import (
    AgeRange,
    ConversationState,
    EligibilityCriteria,
    FamilyInfo,
    FamilyMember,
    GovernmentScheme,
    IncomeInfo,
    Location,
    PendingConfirmation,
    PersonalInfo,
    ProcessedDocument,
    ProcessedDocumentRecord,
    UserData,
    UserProfile,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

PHONE = "919876543210"
FIXED_TS = datetime(2026, 3, 4, 9, 18, 15, tzinfo=timezone.utc)


@pytest.fixture
def basic_profile() -> UserProfile:
    return UserProfile(
        phone_number=PHONE,
        preferred_language=SupportedLanguage.HINDI,
        name="Ramesh Kumar",
        created_at=FIXED_TS,
        last_active=FIXED_TS,
    )


@pytest.fixture
def full_conversation_state() -> ConversationState:
    return ConversationState(
        user_id=PHONE,
        current_step=ConversationStep.COLLECTING_DOCUMENTS,
        target_scheme="pm-kisan",
        preferred_language=SupportedLanguage.ODIA,
        collected_data=UserData(
            personal_info=PersonalInfo(full_name="Ramesh", age=42, gender="male"),
            income=IncomeInfo(annual_income_inr=60000, income_source="agriculture"),
        ),
        pending_confirmations=[
            PendingConfirmation(
                field_name="personal_info.full_name",
                display_label="आपका नाम",
                current_value="Ramesh",
            )
        ],
        retry_count=1,
        last_message_at=FIXED_TS,
    )


@pytest.fixture
def aadhaar_document_record() -> ProcessedDocumentRecord:
    return ProcessedDocumentRecord(
        phone_number=PHONE,
        doc_type=DocumentType.AADHAAR,
        extracted_data={"name": "Ramesh Kumar", "dob": "1984-05-10"},
        confidence=0.93,
        image_s3_key="uploads/919876543210/aadhaar_001.jpg",
        processed_at=FIXED_TS,
    )


@pytest.fixture
def active_scheme() -> GovernmentScheme:
    return GovernmentScheme(
        scheme_id="pm-kisan",
        name="PM-KISAN",
        name_translations={"hi-IN": "पीएम-किसान", "or-IN": "ପ୍ରଧାନ ମନ୍ତ୍ରୀ କିଷାନ ସମ୍ମାନ"},
        description="Income support of Rs 6000/year for small & marginal farmers.",
        eligibility_criteria=EligibilityCriteria(
            income_limit_inr=200000,
            required_documents=[DocumentType.AADHAAR, DocumentType.LAND_RECORD],
        ),
        required_documents=[DocumentType.AADHAAR, DocumentType.LAND_RECORD],
        benefits=["₹6000/year direct transfer"],
        is_active=True,
        last_updated=FIXED_TS,
    )


@pytest.fixture
def inactive_scheme() -> GovernmentScheme:
    return GovernmentScheme(
        scheme_id="old-scheme",
        name="Old Scheme",
        description="Expired scheme.",
        is_active=False,
        last_updated=FIXED_TS,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. UserProfile — PK / SK
# ─────────────────────────────────────────────────────────────────────────────

class TestUserProfileKeys:
    def test_pk_format(self, basic_profile):
        assert basic_profile.pk == f"USER#{PHONE}"

    def test_sk_is_profile(self, basic_profile):
        assert basic_profile.sk == "PROFILE"

    def test_uses_supported_language_enum(self, basic_profile):
        """preferred_language must be a SupportedLanguage enum instance."""
        assert isinstance(basic_profile.preferred_language, SupportedLanguage)
        assert basic_profile.preferred_language == SupportedLanguage.HINDI


# ─────────────────────────────────────────────────────────────────────────────
# 2. UserProfile — DynamoDB serialization & round-trip
# ─────────────────────────────────────────────────────────────────────────────

class TestUserProfileSerialization:
    def test_to_dynamo_item_contains_pk_sk(self, basic_profile):
        item = basic_profile.to_dynamo_item()
        assert item["PK"] == f"USER#{PHONE}"
        assert item["SK"] == "PROFILE"

    def test_to_dynamo_item_no_gsi_keys(self, basic_profile):
        item = basic_profile.to_dynamo_item()
        assert "GSI1PK" not in item
        assert "GSI1SK" not in item

    def test_to_dynamo_item_language_is_string(self, basic_profile):
        """Enum values must be serialized as plain strings, not Enum wrappers."""
        item = basic_profile.to_dynamo_item()
        assert item["preferred_language"] == "hi-IN"
        assert isinstance(item["preferred_language"], str)

    def test_to_dynamo_item_datetime_is_iso_string(self, basic_profile):
        """Datetimes must serialize to ISO 8601 strings for DynamoDB."""
        item = basic_profile.to_dynamo_item()
        # Pydantic v2 serializes with timezone offset or Z
        assert isinstance(item["created_at"], str)
        assert "2026-03-04" in item["created_at"]

    def test_round_trip(self, basic_profile):
        """to_dynamo_item → from_dynamo_item must reproduce an equivalent model."""
        item = basic_profile.to_dynamo_item()
        restored = UserProfile.from_dynamo_item(item)
        assert restored.phone_number == basic_profile.phone_number
        assert restored.name == basic_profile.name
        assert restored.preferred_language == basic_profile.preferred_language

    def test_round_trip_strips_pk_sk(self, basic_profile):
        """from_dynamo_item must not leave PK/SK as model fields."""
        item = basic_profile.to_dynamo_item()
        restored = UserProfile.from_dynamo_item(item)
        # pk and sk are @property — ensure model dict has no raw 'PK'/'SK' fields
        dumped = restored.model_dump()
        assert "PK" not in dumped
        assert "SK" not in dumped


# ─────────────────────────────────────────────────────────────────────────────
# 3. ConversationState — PK / SK and partial data
# ─────────────────────────────────────────────────────────────────────────────

class TestConversationStateKeys:
    def test_pk_format(self, full_conversation_state):
        assert full_conversation_state.pk == f"USER#{PHONE}"

    def test_sk_is_state(self, full_conversation_state):
        assert full_conversation_state.sk == "STATE"


class TestConversationStateData:
    def test_partial_user_data_ok(self):
        """
        ConversationState must accept a UserData with only some sub-objects set.
        This represents data collected mid-conversation.
        """
        state = ConversationState(
            user_id=PHONE,
            collected_data=UserData(
                personal_info=PersonalInfo(full_name="Priya Devi"),
                # income, family, location, documents all absent
            ),
        )
        assert state.collected_data.personal_info.full_name == "Priya Devi"
        assert state.collected_data.income is None
        assert state.collected_data.family is None

    def test_empty_user_data_is_valid(self):
        """An empty UserData (nothing collected yet) must be valid."""
        state = ConversationState(user_id=PHONE)
        assert state.collected_data.personal_info is None
        assert state.collected_data.documents == []

    def test_current_step_default(self):
        state = ConversationState(user_id=PHONE)
        assert state.current_step == ConversationStep.WELCOME

    def test_round_trip(self, full_conversation_state):
        item = full_conversation_state.to_dynamo_item()
        restored = ConversationState.from_dynamo_item(item)
        assert restored.user_id == full_conversation_state.user_id
        assert restored.current_step == full_conversation_state.current_step
        assert restored.target_scheme == full_conversation_state.target_scheme
        assert restored.retry_count == full_conversation_state.retry_count
        assert (
            restored.collected_data.personal_info.full_name
            == full_conversation_state.collected_data.personal_info.full_name
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. ProcessedDocumentRecord — SK timestamp embedding
# ─────────────────────────────────────────────────────────────────────────────

class TestProcessedDocumentRecordKeys:
    def test_pk_format(self, aadhaar_document_record):
        assert aadhaar_document_record.pk == f"USER#{PHONE}"

    def test_sk_contains_doc_type(self, aadhaar_document_record):
        assert "DOC#aadhaar#" in aadhaar_document_record.sk

    def test_sk_contains_timestamp(self, aadhaar_document_record):
        """SK must embed the ISO timestamp so docs sort chronologically."""
        # FIXED_TS = 2026-03-04T09:18:15 UTC
        assert "2026-03-04T09:18:15" in aadhaar_document_record.sk

    def test_sk_full_format(self, aadhaar_document_record):
        expected = "DOC#aadhaar#2026-03-04T09:18:15"
        assert aadhaar_document_record.sk == expected

    def test_round_trip(self, aadhaar_document_record):
        item = aadhaar_document_record.to_dynamo_item()
        restored = ProcessedDocumentRecord.from_dynamo_item(item)
        assert restored.phone_number == aadhaar_document_record.phone_number
        assert restored.doc_type == aadhaar_document_record.doc_type
        assert restored.confidence == aadhaar_document_record.confidence


# ─────────────────────────────────────────────────────────────────────────────
# 5. GovernmentScheme — PK / SK and GSI keys
# ─────────────────────────────────────────────────────────────────────────────

class TestGovernmentSchemeKeys:
    def test_pk_format(self, active_scheme):
        assert active_scheme.pk == "SCHEME#pm-kisan"

    def test_sk_is_metadata(self, active_scheme):
        assert active_scheme.sk == "METADATA"

    def test_gsi1pk_constant(self, active_scheme):
        assert active_scheme.gsi1pk == "SCHEMES"

    def test_active_scheme_gsi1sk(self, active_scheme):
        assert active_scheme.gsi1sk == "ACTIVE#pm-kisan"

    def test_inactive_scheme_gsi1sk(self, inactive_scheme):
        assert inactive_scheme.gsi1sk == "INACTIVE#old-scheme"

    def test_to_dynamo_item_has_gsi_keys(self, active_scheme):
        item = active_scheme.to_dynamo_item()
        assert item["GSI1PK"] == "SCHEMES"
        assert item["GSI1SK"] == "ACTIVE#pm-kisan"

    def test_round_trip(self, active_scheme):
        item = active_scheme.to_dynamo_item()
        restored = GovernmentScheme.from_dynamo_item(item)
        assert restored.scheme_id == active_scheme.scheme_id
        assert restored.is_active == active_scheme.is_active
        assert restored.eligibility_criteria.income_limit_inr == 200000
        assert DocumentType.AADHAAR in restored.required_documents


# ─────────────────────────────────────────────────────────────────────────────
# 6. AgeRange cross-field validator
# ─────────────────────────────────────────────────────────────────────────────

class TestAgeRangeValidator:
    def test_valid_range(self):
        r = AgeRange(min_age=18, max_age=60)
        assert r.min_age == 18
        assert r.max_age == 60

    def test_invalid_range_raises(self):
        with pytest.raises(ValueError, match="max_age"):
            AgeRange(min_age=60, max_age=18)

    def test_equal_range_is_valid(self):
        r = AgeRange(min_age=18, max_age=18)
        assert r.min_age == r.max_age
