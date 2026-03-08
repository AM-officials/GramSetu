"""
GramSetu — Session Manager

Provides a 15-minute DynamoDB-backed session for each WhatsApp user.
The session accumulates extracted document data (name, income, land area, etc.)
across multiple messages so the AI never asks for documents already provided.

Public API
──────────
get_session(phone_number)             → dict  (empty dict if expired or missing)
save_to_session(phone_number, data)   → None

DynamoDB table schema
──────────────────────
  PhoneNumber   : String  (Partition Key)
  session_data  : Map     (accumulated extracted fields as a DynamoDB-native map)
  last_updated  : String  (ISO-8601 UTC timestamp)
  ttl           : Number  (Unix epoch — DynamoDB TTL auto-deletes after expiry)

Environment variable
────────────────────
SESSION_TABLE_NAME (required in Lambda) — set via SAM template
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS = 15 * 60  # 15 minutes


def _get_table():
    """Return a DynamoDB Table resource, or None if SESSION_TABLE_NAME is unset."""
    table_name = os.environ.get("SESSION_TABLE_NAME", "")
    if not table_name:
        logger.warning("SESSION_TABLE_NAME not set — session persistence disabled.")
        return None
    return boto3.resource("dynamodb").Table(table_name)


def get_session(phone_number: str) -> Dict[str, Any]:
    """
    Retrieve the user's accumulated session data from DynamoDB.

    Returns an empty dict if:
      - SESSION_TABLE_NAME is not configured
      - No session exists for this phone number
      - The session's last_updated is older than SESSION_TTL_SECONDS (15 min)
    """
    table = _get_table()
    if table is None:
        return {}

    try:
        response = table.get_item(Key={"PhoneNumber": phone_number})
    except ClientError as exc:
        logger.error("DynamoDB GetItem failed for %s: %s", phone_number, exc)
        return {}

    item = response.get("Item")
    if not item:
        return {}

    # Check staleness in code (belt-and-suspenders over DynamoDB TTL,
    # which can lag by several minutes).
    last_updated_str = item.get("last_updated", "")
    if last_updated_str:
        try:
            last_updated = datetime.fromisoformat(last_updated_str)
            age = datetime.now(tz=timezone.utc) - last_updated
            if age > timedelta(seconds=SESSION_TTL_SECONDS):
                logger.info("Session expired for %s (age=%s) — returning empty.", phone_number, age)
                return {}
        except ValueError:
            # Unreadable timestamp — treat as expired
            return {}

    session_data = item.get("session_data", {})
    # DynamoDB returns Decimal for numbers; convert to plain Python types.
    return json.loads(json.dumps(session_data, default=str))


def save_to_session(phone_number: str, new_data: Dict[str, Any]) -> None:
    """
    Merge new_data into the user's existing session and persist it.

    Merging strategy: existing keys are overwritten only when the new value
    is non-None and non-empty, so earlier documents' fields are preserved
    when later documents don't contain the same field.

    Also resets the 15-minute TTL countdown.
    """
    table = _get_table()
    if table is None:
        return

    # Retrieve current session to merge into (best-effort; ignore errors)
    existing: Dict[str, Any] = {}
    try:
        resp = table.get_item(Key={"PhoneNumber": phone_number})
        existing = resp.get("Item", {}).get("session_data", {})
        existing = json.loads(json.dumps(existing, default=str))
    except ClientError as exc:
        logger.warning("Could not read existing session for merge (%s): %s", phone_number, exc)

    # Merge: new non-null values win; existing values survive when new value is absent
    merged: Dict[str, Any] = {**existing}
    for key, value in new_data.items():
        if value is not None and value != "" and value != "null":
            merged[key] = value

    now = datetime.now(tz=timezone.utc)
    ttl_epoch = int(now.timestamp()) + SESSION_TTL_SECONDS

    try:
        table.update_item(
            Key={"PhoneNumber": phone_number},
            UpdateExpression=(
                "SET session_data = :data, last_updated = :ts, #ttl_attr = :ttl"
            ),
            ExpressionAttributeNames={"#ttl_attr": "ttl"},
            ExpressionAttributeValues={
                ":data": merged,
                ":ts": now.isoformat(),
                ":ttl": ttl_epoch,
            },
        )
        logger.info("Session saved for %s (%d fields).", phone_number, len(merged))
    except ClientError as exc:
        logger.error("DynamoDB UpdateItem failed for %s: %s", phone_number, exc)


def clear_session(phone_number: str) -> None:
    """
    Delete the user's session row from DynamoDB entirely.

    Called after a successful application submission so the user can start
    a fresh session without stale document data from their previous application.
    """
    table = _get_table()
    if table is None:
        return

    try:
        table.delete_item(Key={"PhoneNumber": phone_number})
        logger.info("Session cleared for %s.", phone_number)
    except ClientError as exc:
        logger.error("DynamoDB DeleteItem failed for %s: %s", phone_number, exc)
