"""
GramSetu — Webhook Handler Entry Point

Usage:
    uvicorn run_webhook:app --reload --port 8000

For production-style run (no reload):
    uvicorn run_webhook:app --host 0.0.0.0 --port 8000
"""
import os

# Load .env before importing the app so env vars are available
from dotenv import load_dotenv
load_dotenv()

from src.webhook_handler.main import app  # noqa: E402  (import after dotenv)

__all__ = ["app"]
