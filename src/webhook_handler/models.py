"""
GramSetu — Webhook Handler: Pydantic Models
Mirrors the WhatsApp Business API webhook payload schema exactly.
Reference: https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/payload-examples
"""
from typing import List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Message content variants
# ---------------------------------------------------------------------------

class TextContent(BaseModel):
    """Payload inside a 'text' type message."""
    body: str


class AudioContent(BaseModel):
    """Payload inside an 'audio' type message (voice notes are audio/ogg)."""
    id: str
    mime_type: str


class ImageContent(BaseModel):
    """Payload inside an 'image' type message."""
    id: str
    mime_type: str
    sha256: Optional[str] = None
    caption: Optional[str] = None


class DocumentContent(BaseModel):
    """Payload inside a 'document' type message."""
    id: str
    mime_type: str
    filename: Optional[str] = None
    sha256: Optional[str] = None
    caption: Optional[str] = None


# ---------------------------------------------------------------------------
# Core message model
# ---------------------------------------------------------------------------

class IncomingMessage(BaseModel):
    """
    A single incoming WhatsApp message.
    'from' is a reserved keyword in Python, so 'from_' is used internally
    and aliased to 'from' in the schema via Field(alias=...).
    """
    from_: str = Field(..., alias="from")
    id: str
    timestamp: str
    type: str

    # Content fields — only one will be populated depending on 'type'
    text: Optional[TextContent] = None
    audio: Optional[AudioContent] = None
    image: Optional[ImageContent] = None
    document: Optional[DocumentContent] = None

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Envelope models
# ---------------------------------------------------------------------------

class Profile(BaseModel):
    name: str


class Contact(BaseModel):
    profile: Profile
    wa_id: str


class Metadata(BaseModel):
    display_phone_number: str
    phone_number_id: str


class StatusEntry(BaseModel):
    """Delivery / read receipt — we accept but ignore these for now."""
    id: str
    status: str
    timestamp: str
    recipient_id: str


class Value(BaseModel):
    messaging_product: str
    metadata: Metadata
    contacts: Optional[List[Contact]] = None
    messages: Optional[List[IncomingMessage]] = None
    statuses: Optional[List[StatusEntry]] = None


class Change(BaseModel):
    field: str
    value: Value


class Entry(BaseModel):
    id: str
    changes: List[Change]


class WhatsAppWebhookPayload(BaseModel):
    """Top-level WhatsApp Business API webhook payload."""
    object: str
    entry: List[Entry]
