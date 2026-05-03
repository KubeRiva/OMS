"""
Monitoring & Traceability router.

All endpoints require superadmin authentication.
Data is stored in MongoDB collections: error_events + error_issues.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.database.mongodb import get_mongo_db
from app.dependencies.auth import require_superadmin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitoring", tags=["Monitoring"])

_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_SOURCES = {
    "api", "sourcing_worker", "fulfillment_worker",
    "carrier_worker", "webhook_worker", "connector_worker", "database",
}


def _serialize(doc: dict) -> dict:
    """Convert MongoDB doc to JSON-serialisable dict."""
    doc.pop("_id", None)
    for k, v in doc.items():
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc


def _build_event_query(
    from_ts: Optional[datetime],
    to_ts: Optional[datetime],
    level: Optional[list],
    source_service: Optional[str],
    error_type: Optional[str],
    order_id: Optional[str],
    fingerprint: Optional[str],
) -> dict:
    q: dict = {}
    ts: dict = {}
    if from_ts:
        ts["$gte"] = from_ts
    if to_ts:
        ts["$lte"] = to_ts
    if ts:
        q["timestamp"] = ts
    if level:
        q["level"] = {"$in": level}
    if source_service:
        q["source_service"] = source_service
    if error_type:
        import re as _re
        q["error_type"] = {"$regex": _re.escape(error_type), "$options": "i"}
    if order_id:
        q["order_context.order_id"] = order_id
    if fingerprint:
        q["fingerprint"] = fingerprint
    return q


# ─── Events ───────────────────────────────────────────────────────────────────

@router.get("/events")
async def list_events(
    from_ts: Optional[datetime] = None,
    to_ts: Optional[datetime] = None,
    level: Optional[list[str]] = Query(default=None),
    source_service: Optional[str] = None,
    error_type: Optional[str] = None,
    order_id: Optional[str] = None,
    fingerprint: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, le=200),
    _: dict = Depends(require_superadmin),
    db=Depends(get_mongo_db),
):
    """List raw error events with filtering."""
    if from_ts is None and to_ts is None:
        from_ts = datetime.utcnow() - timedelta(hours=24)

    q = _build_event_query(from_ts, to_ts, level, source_service, error_type, order_id, fingerprint)
    offset = (page - 1) * page_size

    total = await db.error_events.count_documents(q)
    cursor = db.error_events.find(q).sort("timestamp", -1).skip(offset).limit(page_size)
    items = [_serialize(doc) async for doc in cursor]

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/events/{event_id}")
async def get_event(
    event_id: str,
    _: dict = Depends(require_superadmin),
    db=Depends(get_mongo_db),
):
    """Get a single error event by event_id."""
    doc = await db.error_events.find_one({"event_id": event_id})
    if not doc:
        return JSONResponse(status_code=404, content={"detail": "Event not found"})
    return _serialize(doc)


# ─── Issues ───────────────────────────────────────────────────────────────────

@router.get("/issues")
async def list_issues(
    status: Optional[str] = None,
    source_service: Optional[str] = None,
    level: Optional[str] = None,
    from_ts: Optional[datetime] = None,
    sort_by: str = Query(default="last_seen", pattern="^(last_seen|count|first_seen)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, le=200),
    _: dict = Depends(require_superadmin),
    db=Depends(get_mongo_db),
):
    """List aggregated error issues."""
    q: dict = {}
    if status:
        # Explicit status filter (open / resolved / muted)
        q["status"] = status
    # When status is absent/empty, no status filter — return all statuses
    if source_service:
        q["source_service"] = source_service
    if level:
        q["level"] = level
    if from_ts:
        q["last_seen_at"] = {"$gte": from_ts}

    sort_field = {
        "last_seen": [("last_seen_at", -1)],
        "count": [("occurrence_count", -1)],
        "first_seen": [("first_seen_at", -1)],
    }[sort_by]

    offset = (page - 1) * page_size
    total = await db.error_issues.count_documents(q)
    cursor = db.error_issues.find(q).sort(sort_field).skip(offset).limit(page_size)
    items = [_serialize(doc) async for doc in cursor]

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/issues/{fingerprint}")
async def get_issue(
    fingerprint: str,
    _: dict = Depends(require_superadmin),
    db=Depends(get_mongo_db),
):
    """Get a single issue with its 10 most recent events."""
    issue = await db.error_issues.find_one({"fingerprint": fingerprint})
    if not issue:
        return JSONResponse(status_code=404, content={"detail": "Issue not found"})

    cursor = db.error_events.find({"fingerprint": fingerprint}).sort("timestamp", -1).limit(10)
    recent = [_serialize(doc) async for doc in cursor]

    return {"issue": _serialize(issue), "recent_events": recent}


@router.patch("/issues/{fingerprint}")
async def update_issue(
    fingerprint: str,
    body: dict,
    _: dict = Depends(require_superadmin),
    db=Depends(get_mongo_db),
):
    """Update issue status: resolve, mute, or reopen."""
    allowed = {"open", "resolved", "muted"}
    new_status = body.get("status")
    if new_status and new_status not in allowed:
        return JSONResponse(status_code=400, content={"detail": f"status must be one of {allowed}"})

    update: dict = {"$set": {}}
    if new_status:
        update["$set"]["status"] = new_status
        if new_status == "resolved":
            update["$set"]["resolved_at"] = datetime.utcnow()
            update["$set"]["resolution_note"] = body.get("resolution_note", "")
        elif new_status == "muted":
            hours = body.get("mute_hours", 24)
            update["$set"]["muted_until"] = datetime.utcnow() + timedelta(hours=hours)
        elif new_status == "open":
            update["$set"]["resolved_at"] = None
            update["$set"]["muted_until"] = None

    result = await db.error_issues.find_one_and_update(
        {"fingerprint": fingerprint},
        update,
        return_document=True,
    )
    if not result:
        return JSONResponse(status_code=404, content={"detail": "Issue not found"})
    return _serialize(result)


# ─── Metrics ──────────────────────────────────────────────────────────────────

@router.get("/metrics/rate")
async def metrics_rate(
    from_ts: Optional[datetime] = Query(None),
    to_ts: Optional[datetime] = Query(None),
    bucket_hours: int = Query(default=1, ge=1, le=24),
    source_service: Optional[str] = None,
    _: dict = Depends(require_superadmin),
    db=Depends(get_mongo_db),
):
    """Error rate over time, bucketed by hour."""
    if from_ts is None:
        from_ts = datetime.utcnow() - timedelta(hours=24)
    if to_ts is None:
        to_ts = datetime.utcnow()

    match: dict = {"timestamp": {"$gte": from_ts, "$lte": to_ts}}
    if source_service:
        match["source_service"] = source_service

    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id": {
                    "$dateTrunc": {
                        "date": "$timestamp",
                        "unit": "hour",
                        "binSize": bucket_hours,
                    }
                },
                "count": {"$sum": 1},
                "by_source": {"$push": "$source_service"},
                "by_level": {"$push": "$level"},
            }
        },
        {"$sort": {"_id": 1}},
    ]

    results = []
    async for doc in db.error_events.aggregate(pipeline):
        bucket_dt = doc["_id"]
        source_counts: dict = {}
        for s in doc.get("by_source", []):
            source_counts[s] = source_counts.get(s, 0) + 1
        results.append({
            "bucket": bucket_dt.isoformat() if isinstance(bucket_dt, datetime) else str(bucket_dt),
            "count": doc["count"],
            "by_source": source_counts,
        })

    return results


@router.get("/metrics/top")
async def metrics_top(
    from_ts: Optional[datetime] = Query(None),
    to_ts: Optional[datetime] = Query(None),
    limit: int = Query(default=10, ge=1, le=50),
    _: dict = Depends(require_superadmin),
    db=Depends(get_mongo_db),
):
    """Top N error issues by occurrence count in the selected period."""
    if from_ts is None:
        from_ts = datetime.utcnow() - timedelta(hours=24)
    if to_ts is None:
        to_ts = datetime.utcnow()

    pipeline = [
        {"$match": {"timestamp": {"$gte": from_ts, "$lte": to_ts}}},
        {
            "$group": {
                "_id": "$fingerprint",
                "count": {"$sum": 1},
                "error_type": {"$first": "$error_type"},
                "source_service": {"$first": "$source_service"},
                "level": {"$first": "$level"},
                "last_seen": {"$max": "$timestamp"},
                "error_message": {"$first": "$error_message"},
            }
        },
        {"$sort": {"count": -1}},
        {"$limit": limit},
    ]

    results = []
    async for doc in db.error_events.aggregate(pipeline):
        results.append({
            "fingerprint": doc["_id"],
            "count": doc["count"],
            "error_type": doc.get("error_type"),
            "source_service": doc.get("source_service"),
            "level": doc.get("level"),
            "last_seen": doc["last_seen"].isoformat() if isinstance(doc.get("last_seen"), datetime) else None,
            "error_message": doc.get("error_message", "")[:120],
        })

    return results


@router.get("/metrics/sources")
async def metrics_sources(
    from_ts: Optional[datetime] = Query(None),
    to_ts: Optional[datetime] = Query(None),
    _: dict = Depends(require_superadmin),
    db=Depends(get_mongo_db),
):
    """Error breakdown by source service."""
    if from_ts is None:
        from_ts = datetime.utcnow() - timedelta(hours=24)
    if to_ts is None:
        to_ts = datetime.utcnow()

    pipeline = [
        {"$match": {"timestamp": {"$gte": from_ts, "$lte": to_ts}}},
        {"$group": {"_id": "$source_service", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]

    rows = [{"source_service": d["_id"], "count": d["count"]} async for d in db.error_events.aggregate(pipeline)]
    total = sum(r["count"] for r in rows)
    for r in rows:
        r["percentage"] = round(r["count"] / total * 100, 1) if total else 0

    return rows


@router.post("/issues/bulk-resolve")
async def bulk_resolve_issues(
    body: dict = None,
    _: dict = Depends(require_superadmin),
    db=Depends(get_mongo_db),
):
    """
    Bulk-resolve matching open issues.
    Accepts optional filters: status (default 'open'), source_service, level, fingerprints list.
    """
    now = datetime.utcnow()
    q: dict = {"status": "open"}
    if body:
        if body.get("source_service"):
            q["source_service"] = body["source_service"]
        if body.get("level"):
            q["level"] = body["level"]
        if body.get("fingerprints"):
            q["fingerprint"] = {"$in": body["fingerprints"]}

    result = await db.error_issues.update_many(
        q,
        {"$set": {
            "status": "resolved",
            "resolved_at": now,
            "resolution_note": body.get("resolution_note", "Bulk resolved") if body else "Bulk resolved",
        }},
    )
    return {"resolved_count": result.modified_count}


@router.post("/test-error")
async def inject_test_error(
    body: dict = None,
    _: dict = Depends(require_superadmin),
):
    """
    Inject a synthetic test error into the monitoring pipeline.
    Useful for verifying that error capture, indexing, and the UI are all working.
    """
    from app.services.monitoring import capture_error, SOURCE_API
    try:
        raise RuntimeError(body.get("message", "Test error from monitoring console") if body else "Test error from monitoring console")
    except Exception as exc:
        await capture_error(
            exc,
            source_service=body.get("source", SOURCE_API) if body else SOURCE_API,
            level=body.get("level", "ERROR") if body else "ERROR",
            tags=["test"],
            extra={"injected": True},
        )
    return {"ok": True, "message": "Test error injected — check Issues and Events tabs"}


@router.get("/summary")
async def summary(
    _: dict = Depends(require_superadmin),
    db=Depends(get_mongo_db),
):
    """Quick stats: open issues, errors last 1h/24h, top source."""
    now = datetime.utcnow()
    last_1h = now - timedelta(hours=1)
    last_24h = now - timedelta(hours=24)

    open_issues = await db.error_issues.count_documents({"status": "open"})
    errors_1h = await db.error_events.count_documents({"timestamp": {"$gte": last_1h}, "level": {"$in": ["ERROR", "CRITICAL"]}})
    errors_24h = await db.error_events.count_documents({"timestamp": {"$gte": last_24h}, "level": {"$in": ["ERROR", "CRITICAL"]}})
    warnings_24h = await db.error_events.count_documents({"timestamp": {"$gte": last_24h}, "level": "WARNING"})

    # Top source in last 24h
    pipeline = [
        {"$match": {"timestamp": {"$gte": last_24h}}},
        {"$group": {"_id": "$source_service", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 1},
    ]
    top_source = None
    async for doc in db.error_events.aggregate(pipeline):
        top_source = doc["_id"]

    return {
        "open_issues": open_issues,
        "errors_last_1h": errors_1h,
        "errors_last_24h": errors_24h,
        "warnings_last_24h": warnings_24h,
        "top_error_source": top_source,
    }
