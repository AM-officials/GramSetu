"""
GramSetu — Webhook Handler: FastAPI App Factory
"""
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

from src.webhook_handler.router import router

# Loads .env on startup — safe to call even in Lambda (no-op if vars already set)
load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle events."""
    print("=" * 55)
    print(" GramSetu Webhook Handler — starting up")
    print(" POST /webhook  →  incoming WhatsApp messages")
    print(" GET  /webhook  →  hub challenge verification")
    print("=" * 55)
    yield
    print("[GramSetu] Webhook Handler shutting down.")


app = FastAPI(
    title="GramSetu Webhook Handler",
    description=(
        "Local development server mirroring the GramSetu Webhook Handler Lambda. "
        "Accepts WhatsApp Business API payloads and routes them through the processing pipeline."
    ),
    version="0.1.0",
    lifespan=lifespan,
    root_path="/prod",
)

app.include_router(router)


# ──────────────────────────────────────────────────────────────────
# AWS Lambda handler — used by SAM / AWS Lambda runtime.
# Mangum wraps the FastAPI ASGI app as a standard Lambda handler.
# The `try` guard keeps local `uvicorn` development working when
# Mangum is not installed in the local venv (it lives in the layer).
# ──────────────────────────────────────────────────────────────────
try:
    from mangum import Mangum
    handler = Mangum(app, lifespan="off")
except ImportError:
    handler = None  # Local dev — Mangum not required
