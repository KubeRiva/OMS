"""
Central error capture service for the OMS monitoring and traceability console.

Usage in async contexts (FastAPI, sourcing worker):
    await capture_error(exc, source_service="api", request_context={...})

Usage in sync Celery workers (fulfillment, carrier, webhooks):
    capture_error_sync(exc, source_service="fulfillment_worker", task_context={...})

Both functions are fire-and-forget: they swallow any capture failure so they
never impact the primary operation.
"""
import hashlib
import logging
import traceback
import uuid
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Source service labels ────────────────────────────────────────────────────

SOURCE_API = "api"
SOURCE_SOURCING = "sourcing_worker"
SOURCE_FULFILLMENT = "fulfillment_worker"
SOURCE_CARRIER = "carrier_worker"
SOURCE_WEBHOOK = "webhook_worker"
SOURCE_CONNECTOR = "connector_worker"
SOURCE_DATABASE = "database"


# ─── Fingerprint ──────────────────────────────────────────────────────────────

def make_fingerprint(error_type: str, source_service: str, tb: str = "") -> str:
    """Generate a stable 16-char fingerprint that groups duplicate errors."""
    top_frame = ""
    if tb:
        for line in reversed(tb.strip().splitlines()):
            if 'File "' in line and ", line" in line:
                top_frame = line.strip()
                break
    raw = f"{source_service}:{error_type}:{top_frame}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ─── Stack frame parser ────────────────────────────────────────────────────────

def _parse_stack_frames(tb: str) -> list:
    """Extract structured frame objects from a Python traceback string."""
    frames = []
    lines = tb.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('File "') and ", line" in stripped:
            try:
                parts = stripped.split('", line ')
                filename = parts[0].replace('File "', "")
                rest = parts[1].split(", in ")
                lineno = int(rest[0])
                func_name = rest[1] if len(rest) > 1 else ""
                context = lines[i + 1].strip() if i + 1 < len(lines) else ""
                frames.append(
                    {"filename": filename, "lineno": lineno, "function": func_name, "context_line": context}
                )
            except Exception:
                pass
    return frames


# ─── Async capture (FastAPI / async workers) ──────────────────────────────────

async def capture_error(
    exc: Exception,
    source_service: str,
    level: str = "ERROR",
    request_context: Optional[dict] = None,
    task_context: Optional[dict] = None,
    order_context: Optional[dict] = None,
    tags: Optional[list] = None,
    extra: Optional[dict] = None,
) -> None:
    """
    Write one error_event to MongoDB and upsert the error_issues aggregate.
    Never raises — all failures are swallowed via logger.warning.
    """
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        from app.config import settings

        error_type = type(exc).__name__
        error_message = str(exc)
        tb = traceback.format_exc()
        fingerprint = make_fingerprint(error_type, source_service, tb)
        event_id = str(uuid.uuid4())
        now = datetime.utcnow()

        event_doc = {
            "event_id": event_id,
            "fingerprint": fingerprint,
            "timestamp": now,
            "level": level,
            "source_service": source_service,
            "error_type": error_type,
            "error_message": error_message,
            "stack_trace": tb,
            "stack_frames": _parse_stack_frames(tb),
            "request_context": request_context or {},
            "task_context": task_context or {},
            "order_context": order_context or {},
            "environment": settings.ENVIRONMENT,
            "tags": tags or [],
            "extra": extra or {},
        }

        client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=3000)
        try:
            db = client[settings.MONGODB_DB]
            await db.error_events.insert_one(event_doc)

            # Upsert aggregate issue document
            await db.error_issues.update_one(
                {"fingerprint": fingerprint},
                {
                    "$inc": {"occurrence_count": 1},
                    "$set": {
                        "error_type": error_type,
                        "error_message": error_message,
                        "source_service": source_service,
                        "level": level,
                        "last_seen_at": now,
                        "last_event_id": event_id,
                        "tags": tags or [],
                    },
                    "$setOnInsert": {
                        "fingerprint": fingerprint,
                        "status": "open",
                        "first_seen_at": now,
                        "assigned_to": None,
                        "resolved_at": None,
                        "muted_until": None,
                        "resolution_note": None,
                    },
                },
                upsert=True,
            )
        finally:
            client.close()

    except Exception as capture_exc:
        logger.warning("capture_error failed (swallowed): %s", capture_exc)


# ─── Sync capture (Celery sync workers) ──────────────────────────────────────

def capture_error_sync(
    exc: Exception,
    source_service: str,
    level: str = "ERROR",
    task_context: Optional[dict] = None,
    order_context: Optional[dict] = None,
    tags: Optional[list] = None,
    extra: Optional[dict] = None,
) -> None:
    """
    Sync wrapper around capture_error for use in synchronous Celery workers.

    Handles two cases:
    1. No running event loop  → use asyncio.run() directly.
    2. Already inside a running event loop (e.g. async Celery worker) →
       spawn a daemon thread so asyncio.run() gets its own fresh loop,
       avoiding the "Future attached to different loop" RuntimeError.

    Never raises — all failures are swallowed via logger.warning.
    """
    import asyncio
    import threading

    def _run_coro() -> None:
        asyncio.run(
            capture_error(
                exc=exc,
                source_service=source_service,
                level=level,
                task_context=task_context,
                order_context=order_context,
                tags=tags,
                extra=extra,
            )
        )

    try:
        try:
            asyncio.get_running_loop()
            # There IS a running event loop in this thread.
            # Spawn a daemon thread so asyncio.run() gets an isolated loop.
            t = threading.Thread(target=_run_coro, daemon=True)
            t.start()
            t.join(timeout=5)
        except RuntimeError:
            # No running loop — safe to call asyncio.run() directly.
            _run_coro()
    except Exception as capture_exc:
        logger.warning("capture_error_sync failed (swallowed): %s", capture_exc)
