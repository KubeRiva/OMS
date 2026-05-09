"""
TechOps / SRE router — log intelligence, order traces, error explorer, AI RCA.

All endpoints require superadmin authentication.
"""
import asyncio
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional, AsyncGenerator

import httpx
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.database.mongodb import get_mongo_db
from app.dependencies.auth import require_superadmin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops", tags=["TechOps / SRE"])

SERVICES = ["api", "celery_worker", "celery_beat", "flower", "frontend"]

FLOWER_URL = os.getenv("FLOWER_URL", "http://flower:5555")

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _serialize(doc: dict) -> dict:
    doc.pop("_id", None)
    for k, v in list(doc.items()):
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
        elif isinstance(v, dict):
            doc[k] = _serialize(v)
    return doc


def _minutes_ago(n: int) -> datetime:
    return datetime.utcnow() - timedelta(minutes=n)


async def _flower_stats() -> dict:
    """Fetch Celery queue + worker stats from Flower API."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            workers_r = await client.get(f"{FLOWER_URL}/api/workers?refresh=true")
            tasks_r = await client.get(f"{FLOWER_URL}/api/tasks?limit=100&state=FAILURE")
            workers = workers_r.json() if workers_r.status_code == 200 else {}
            failed_tasks = tasks_r.json() if tasks_r.status_code == 200 else {}
            return {"workers": workers, "failed_tasks": failed_tasks}
    except Exception as exc:
        logger.warning("Flower unreachable: %s", exc)
        return {"workers": {}, "failed_tasks": {}}


def _read_docker_logs(container: str, since_minutes: int = 30, tail: int = 200) -> list[dict]:
    """
    Read structured JSON logs from a Docker container via the Docker SDK.
    Falls back gracefully if Docker is not available.
    """
    try:
        import docker as docker_sdk
        from datetime import timezone

        client = docker_sdk.from_env()
        since_dt = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
        container_obj = client.containers.get(f"oms_{container}")
        raw_logs = container_obj.logs(
            since=since_dt,
            tail=tail,
            timestamps=True,
            stream=False,
        )
        lines = raw_logs.decode("utf-8", errors="replace").splitlines()
        parsed = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts = line.split(" ", 1)
            ts_raw, content = (parts[0], parts[1]) if len(parts) == 2 else ("", line)
            try:
                obj = json.loads(content)
                obj.setdefault("container", container)
                obj.setdefault("raw", content)
                if ts_raw and "ts" not in obj:
                    obj["ts"] = ts_raw.rstrip("Z")
            except (json.JSONDecodeError, ValueError):
                obj = {
                    "ts": ts_raw.rstrip("Z") if ts_raw else datetime.utcnow().isoformat(),
                    "level": "ERROR" if "error" in content.lower() or "exception" in content.lower()
                             else "WARN" if "warn" in content.lower()
                             else "INFO",
                    "msg": content,
                    "container": container,
                    "raw": content,
                }
            parsed.append(obj)
        client.close()
        return parsed
    except Exception as exc:
        logger.warning("Could not read docker logs for %s: %s", container, exc)
        return []


# ─── Health ───────────────────────────────────────────────────────────────────

@router.get("/health")
async def ops_health(
    _: dict = Depends(require_superadmin),
    db=Depends(get_mongo_db),
):
    """
    Aggregate health: worker status (Flower), queue depths, recent error counts.
    """
    flower = await _flower_stats()
    workers_raw = flower.get("workers", {})
    failed_tasks = flower.get("failed_tasks", {})

    # Parse Flower worker data
    services = []
    for name, info in workers_raw.items():
        label = name.split("@")[0].replace("celery", "worker")
        active = info.get("active", {})
        active_count = sum(len(v) for v in active.values()) if isinstance(active, dict) else 0
        services.append({
            "name": name,
            "label": label,
            "status": "live" if info.get("status") else "offline",
            "active_tasks": active_count,
            "processed": info.get("total", {}).get("app.workers", 0),
        })

    # Queue depths from Flower active + reserved counts
    queues: dict[str, int] = defaultdict(int)
    for name, info in workers_raw.items():
        for q_name, tasks in (info.get("active", {}) or {}).items():
            queues[q_name] += len(tasks)
        for q_name, tasks in (info.get("reserved", {}) or {}).items():
            queues[q_name] += len(tasks)

    # Recent errors from MongoDB (last 1h)
    since = datetime.utcnow() - timedelta(hours=1)
    total_errors_1h = await db.error_events.count_documents({"timestamp": {"$gte": since}})

    # Error rate per service (last 1h)
    pipeline = [
        {"$match": {"timestamp": {"$gte": since}}},
        {"$group": {"_id": "$source_service", "count": {"$sum": 1}}},
    ]
    error_by_service = {}
    async for doc in db.error_events.aggregate(pipeline):
        error_by_service[doc["_id"]] = doc["count"]

    # Recent errors list (last 10)
    recent_cursor = db.error_events.find(
        {"timestamp": {"$gte": datetime.utcnow() - timedelta(hours=6)}},
    ).sort("timestamp", -1).limit(10)
    recent_errors = [_serialize(d) async for d in recent_cursor]

    # Error sparkline (last 60 min, per 5-min bucket)
    sparkline = []
    for i in range(12):
        bucket_start = since + timedelta(minutes=i * 5)
        bucket_end = bucket_start + timedelta(minutes=5)
        count = await db.error_events.count_documents({
            "timestamp": {"$gte": bucket_start, "$lt": bucket_end}
        })
        sparkline.append({"t": bucket_start.isoformat(), "count": count})

    # Failed Celery tasks count
    failed_count = len(failed_tasks) if isinstance(failed_tasks, dict) else 0

    return {
        "services": services,
        "queues": dict(queues),
        "errors_last_1h": total_errors_1h,
        "errors_by_service": error_by_service,
        "failed_celery_tasks": failed_count,
        "recent_errors": recent_errors,
        "sparkline": sparkline,
        "checked_at": datetime.utcnow().isoformat(),
    }


# ─── Logs ─────────────────────────────────────────────────────────────────────

@router.get("/logs")
async def ops_logs(
    service: Optional[str] = Query(default=None, description="Container name, e.g. celery_worker"),
    level: Optional[str] = Query(default=None, description="MIN level: DEBUG|INFO|WARN|ERROR"),
    since_minutes: int = Query(default=30, ge=1, le=1440),
    tail: int = Query(default=200, ge=10, le=1000),
    search: Optional[str] = Query(default=None, description="Keyword or order ID"),
    _: dict = Depends(require_superadmin),
    db=Depends(get_mongo_db),
):
    """
    Return structured log lines from Docker containers + MongoDB error events merged.
    """
    level_order = {"DEBUG": 0, "INFO": 1, "WARN": 2, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
    min_level = level_order.get((level or "DEBUG").upper(), 0)

    # Gather docker logs
    containers = [service] if service else SERVICES
    all_lines = []
    for c in containers:
        lines = _read_docker_logs(c, since_minutes=since_minutes, tail=tail)
        all_lines.extend(lines)

    # Also pull from MongoDB error_events for rich structured data
    since = datetime.utcnow() - timedelta(minutes=since_minutes)
    q: dict = {"timestamp": {"$gte": since}}
    if service:
        q["source_service"] = service
    if level and level.upper() in ("ERROR", "CRITICAL"):
        q["level"] = {"$in": ["ERROR", "CRITICAL"]}

    mongo_cursor = db.error_events.find(q).sort("timestamp", -1).limit(200)
    async for doc in mongo_cursor:
        doc = _serialize(doc)
        all_lines.append({
            "ts": doc.get("timestamp", ""),
            "level": doc.get("level", "ERROR"),
            "msg": doc.get("message", doc.get("error_type", "")),
            "container": doc.get("source_service", ""),
            "order_id": doc.get("order_context", {}).get("order_id"),
            "fingerprint": doc.get("fingerprint"),
            "exc": doc.get("stack_trace"),
            "source": "mongodb",
            "raw": json.dumps(doc),
        })

    # Filter by level
    def _log_level(line: dict) -> int:
        lv = (line.get("level") or "INFO").upper()
        return level_order.get(lv, 1)

    filtered = [l for l in all_lines if _log_level(l) >= min_level]

    # Filter by keyword/order_id
    if search:
        s = search.lower()
        filtered = [l for l in filtered if s in json.dumps(l).lower()]

    # Sort by timestamp desc
    def _ts(line: dict) -> str:
        return line.get("ts") or ""

    filtered.sort(key=_ts, reverse=True)

    return {"items": filtered[:tail], "total": len(filtered)}


# ─── Order Trace ──────────────────────────────────────────────────────────────

@router.get("/trace/{order_id}")
async def ops_order_trace(
    order_id: str,
    _: dict = Depends(require_superadmin),
    db=Depends(get_mongo_db),
):
    """
    Full lifecycle trace for one order: MongoDB order_events + error_events merged
    into a single chronological timeline.
    """
    # Order audit events
    events_cursor = db.order_events.find({"order_id": order_id}).sort("timestamp", 1)
    audit_events = [_serialize(d) async for d in events_cursor]

    # Error events linked to this order
    errors_cursor = db.error_events.find(
        {"order_context.order_id": order_id}
    ).sort("timestamp", 1)
    error_events = [_serialize(d) async for d in errors_cursor]

    # Merge into unified timeline
    timeline = []
    for ev in audit_events:
        timeline.append({
            "ts": ev.get("timestamp", ""),
            "kind": "audit",
            "event_type": ev.get("event_type", ""),
            "status": ev.get("data", {}).get("status"),
            "worker": ev.get("data", {}).get("worker") or "api",
            "data": ev.get("data", {}),
            "ok": True,
        })
    for ev in error_events:
        timeline.append({
            "ts": ev.get("timestamp", ""),
            "kind": "error",
            "event_type": ev.get("error_type", "Error"),
            "status": None,
            "worker": ev.get("source_service", ""),
            "message": ev.get("message", ""),
            "stack_trace": ev.get("stack_trace", ""),
            "data": ev,
            "ok": False,
        })

    timeline.sort(key=lambda x: x["ts"] or "")

    # Determine current stuck state
    statuses = [t["status"] for t in timeline if t.get("status")]
    last_status = statuses[-1] if statuses else None
    last_error = next((t for t in reversed(timeline) if not t["ok"]), None)

    return {
        "order_id": order_id,
        "timeline": timeline,
        "last_status": last_status,
        "last_error": last_error,
        "audit_count": len(audit_events),
        "error_count": len(error_events),
    }


# ─── Error Groups ─────────────────────────────────────────────────────────────

@router.get("/errors")
async def ops_errors(
    since_hours: int = Query(default=24, ge=1, le=168),
    service: Optional[str] = None,
    _: dict = Depends(require_superadmin),
    db=Depends(get_mongo_db),
):
    """
    Grouped error fingerprints with frequency, affected orders, and sample traces.
    """
    since = datetime.utcnow() - timedelta(hours=since_hours)
    q: dict = {"timestamp": {"$gte": since}}
    if service:
        q["source_service"] = service

    # Aggregate by fingerprint
    pipeline = [
        {"$match": q},
        {"$group": {
            "_id": "$fingerprint",
            "count": {"$sum": 1},
            "first_seen": {"$min": "$timestamp"},
            "last_seen": {"$max": "$timestamp"},
            "source_service": {"$first": "$source_service"},
            "error_type": {"$first": "$error_type"},
            "message": {"$first": "$message"},
            "sample_id": {"$first": "$event_id"},
            "order_ids": {"$addToSet": "$order_context.order_id"},
        }},
        {"$sort": {"count": -1}},
        {"$limit": 50},
    ]

    groups = []
    async for doc in db.error_events.aggregate(pipeline):
        order_ids = [o for o in (doc.get("order_ids") or []) if o]
        groups.append({
            "fingerprint": doc["_id"],
            "count": doc["count"],
            "first_seen": doc["first_seen"].isoformat() if isinstance(doc["first_seen"], datetime) else doc["first_seen"],
            "last_seen": doc["last_seen"].isoformat() if isinstance(doc["last_seen"], datetime) else doc["last_seen"],
            "source_service": doc.get("source_service", ""),
            "error_type": doc.get("error_type", ""),
            "message": doc.get("message", ""),
            "sample_event_id": doc.get("sample_id", ""),
            "affected_orders": order_ids,
            "affected_order_count": len(order_ids),
        })

    # Also pull from error_issues collection (richer data)
    issues_cursor = db.error_issues.find(
        {"last_seen_at": {"$gte": since}}
    ).sort("occurrence_count", -1).limit(50)
    issues = [_serialize(d) async for d in issues_cursor]

    return {
        "groups": groups,
        "issues": issues,
        "since_hours": since_hours,
        "total_groups": len(groups),
    }


# ─── AI Analyze ───────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    order_id: Optional[str] = None
    fingerprint: Optional[str] = None
    question: Optional[str] = None
    context_minutes: int = 60


async def _stream_ai_analysis(
    system_prompt: str,
    user_message: str,
) -> AsyncGenerator[str, None]:
    """Stream KubeAI analysis via Anthropic API with SSE."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        yield f"data: {json.dumps({'type': 'text', 'text': 'ANTHROPIC_API_KEY not configured. Set it in your environment.'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)

        async with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            async for text in stream.text_stream:
                yield f"data: {json.dumps({'type': 'text', 'text': text})}\n\n"

        yield "data: [DONE]\n\n"
    except Exception as exc:
        logger.exception("AI analyze streaming error")
        yield f"data: {json.dumps({'type': 'error', 'text': 'An error occurred during analysis'})}\n\n"
        yield "data: [DONE]\n\n"


@router.post("/analyze")
async def ops_analyze(
    req: AnalyzeRequest,
    _: dict = Depends(require_superadmin),
    db=Depends(get_mongo_db),
):
    """
    AI-powered root cause analysis. Accepts order_id, error fingerprint, or free question.
    Streams response as SSE.
    """
    context_parts = []

    # Gather order trace if order_id provided
    if req.order_id:
        events_cursor = db.order_events.find({"order_id": req.order_id}).sort("timestamp", 1)
        audit = [_serialize(d) async for d in events_cursor]
        errors_cursor = db.error_events.find(
            {"order_context.order_id": req.order_id}
        ).sort("timestamp", 1)
        errors = [_serialize(d) async for d in errors_cursor]

        context_parts.append(f"## Order Audit Trail (order_id={req.order_id})\n")
        for ev in audit:
            context_parts.append(f"- {ev.get('timestamp','')} [{ev.get('event_type','')}] {json.dumps(ev.get('data',{}))}")
        if errors:
            context_parts.append(f"\n## Errors for this order\n")
            for ev in errors:
                context_parts.append(f"- {ev.get('timestamp','')} [{ev.get('source_service','')}] {ev.get('error_type','')} — {ev.get('message','')}")
                if ev.get("stack_trace"):
                    context_parts.append(f"  Stack: {ev['stack_trace'][:500]}")

    # Gather error group if fingerprint provided
    if req.fingerprint:
        issue = await db.error_issues.find_one({"fingerprint": req.fingerprint})
        if issue:
            issue = _serialize(issue)
            context_parts.append(f"\n## Error Issue\n")
            context_parts.append(f"Type: {issue.get('error_type','')}")
            context_parts.append(f"Count: {issue.get('occurrence_count', 0)} occurrences")
            context_parts.append(f"Service: {issue.get('source_service','')}")
            context_parts.append(f"Message: {issue.get('message','')}")
            if issue.get("stack_trace"):
                context_parts.append(f"Stack:\n{issue['stack_trace'][:1000]}")

        # Recent events for this fingerprint
        recent_cursor = db.error_events.find({"fingerprint": req.fingerprint}).sort("timestamp", -1).limit(5)
        recent = [_serialize(d) async for d in recent_cursor]
        if recent:
            context_parts.append(f"\nRecent occurrences ({len(recent)}):")
            for ev in recent:
                order_ctx = ev.get("order_context", {}) or {}
                context_parts.append(f"  - {ev.get('timestamp','')} order={order_ctx.get('order_id','n/a')} {ev.get('message','')[:200]}")

    # Recent system errors (last N minutes) if no specific context
    if not req.order_id and not req.fingerprint:
        since = datetime.utcnow() - timedelta(minutes=req.context_minutes)
        recent_cursor = db.error_events.find(
            {"timestamp": {"$gte": since}, "level": {"$in": ["ERROR", "CRITICAL"]}}
        ).sort("timestamp", -1).limit(20)
        recent = [_serialize(d) async for d in recent_cursor]
        context_parts.append(f"## Recent Errors (last {req.context_minutes} min)\n")
        for ev in recent:
            context_parts.append(f"- {ev.get('timestamp','')} [{ev.get('source_service','')}] {ev.get('error_type','')} — {ev.get('message','')[:200]}")

    context = "\n".join(context_parts)
    question = req.question or "What went wrong? Identify the root cause, which orders are affected, and suggest a fix."

    system_prompt = """You are KubeAI, an expert SRE assistant for an omni-channel Order Management System (OMS).

The OMS has these services:
- api: FastAPI app handling HTTP requests
- celery_worker: Processes sourcing, fulfillment, connector, and learning Celery tasks
- celery_beat: Schedules periodic tasks (source_pending_orders every 2 min, retry_backordered every min)
- connector_worker: Syncs with Shopify and Amazon SP-API

Order lifecycle: CONFIRMED → SOURCING → SOURCED → PICKING → PACKING → READY_TO_SHIP → SHIPPED → DELIVERED

Key concepts:
- MissingGreenlet: SQLAlchemy async session misuse in sync context
- source_pending_orders: Celery task that picks up CONFIRMED orders and runs sourcing engine
- Sourcing engine: Evaluates fulfillment nodes by distance, cost, capacity, and AI scores
- FulfillmentAllocation: Links an order to a specific node for picking/packing

Provide: root cause, affected scope, immediate fix, and recovery steps.
Be concise. Use markdown. Lead with the most important finding."""

    user_message = f"{context}\n\n---\n\nQuestion: {question}"

    return StreamingResponse(
        _stream_ai_analysis(system_prompt, user_message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ─── Re-queue stuck orders ────────────────────────────────────────────────────

@router.post("/requeue-stuck")
async def requeue_stuck_orders(
    status: str = Query(default="CONFIRMED", description="Status to re-queue"),
    _: dict = Depends(require_superadmin),
):
    """
    Manually trigger sourcing for all orders in the given status.
    Useful after fixing a worker bug.
    """
    try:
        from app.workers.sourcing import source_pending_orders
        from app.workers.env_utils import list_active_environment_ids
        env_ids = await list_active_environment_ids()
        triggered = 0
        for env_id in env_ids:
            source_pending_orders.apply_async(kwargs={"environment_id": env_id})
            triggered += 1
        return {"triggered": triggered, "environments": env_ids, "status_targeted": status}
    except Exception as exc:
        logger.exception("Trigger sourcing error")
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})
