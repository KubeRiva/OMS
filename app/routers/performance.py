"""Performance metrics router — system health, pipeline timing, and worker throughput."""
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from app.database.postgres import get_db
from app.database.mongodb import get_mongo_db
from app.database.redis_client import get_redis
from app.dependencies.auth import require_superadmin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/performance", tags=["Performance"])

CELERY_QUEUES = ["sourcing", "fulfillment", "carrier", "notifications", "webhooks", "connectors"]
STAGE_EVENTS = [
    "order.created", "order.sourced", "order.shipped",
    "order.delivered", "order.backordered", "order.cancelled",
]


# ─── System Health ─────────────────────────────────────────────────────────────

@router.get("/system")
async def system_health(
    _: dict = Depends(require_superadmin),
    redis: aioredis.Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
    mdb=Depends(get_mongo_db),
):
    """Real-time snapshot of all infrastructure components."""

    # ── Redis ──
    redis_info: dict = {}
    queue_depths: dict = {}
    try:
        info = await redis.info()
        hits = info.get("keyspace_hits", 0)
        misses = info.get("keyspace_misses", 0)
        redis_info = {
            "status": "ok",
            "version": info.get("redis_version"),
            "uptime_seconds": info.get("uptime_in_seconds"),
            "used_memory_mb": round(info.get("used_memory", 0) / 1024 / 1024, 2),
            "peak_memory_mb": round(info.get("used_memory_peak", 0) / 1024 / 1024, 2),
            "connected_clients": info.get("connected_clients"),
            "ops_per_second": info.get("instantaneous_ops_per_sec"),
            "keyspace_hits": hits,
            "keyspace_misses": misses,
            "hit_rate_pct": round(hits / max(hits + misses, 1) * 100, 1),
        }
        for queue in CELERY_QUEUES:
            try:
                queue_depths[queue] = await redis.llen(queue)
            except Exception:
                queue_depths[queue] = -1
    except Exception as exc:
        redis_info = {"status": "error", "error": str(exc)[:200]}

    # ── PostgreSQL ──
    pg_info: dict = {}
    try:
        result = await db.execute(text("""
            SELECT relname, n_live_tup
            FROM pg_stat_user_tables
            WHERE relname IN (
                'orders', 'order_items', 'inventory_items',
                'shipments', 'fulfillment_allocations', 'connectors', 'webhook_endpoints'
            )
            ORDER BY n_live_tup DESC
        """))
        rows = result.all()
        t0 = datetime.utcnow()
        await db.execute(text("SELECT 1"))
        query_ms = round((datetime.utcnow() - t0).total_seconds() * 1000, 1)
        pg_info = {
            "status": "ok",
            "table_counts": {r.relname: r.n_live_tup for r in rows},
            "query_time_ms": query_ms,
        }
    except Exception as exc:
        pg_info = {"status": "error", "error": str(exc)[:200]}

    # ── MongoDB ──
    mongo_info: dict = {}
    try:
        t0 = datetime.utcnow()
        order_events = await mdb.order_events.count_documents({})
        error_events = await mdb.error_events.count_documents({})
        open_issues = await mdb.error_issues.count_documents({"status": "open"})
        query_ms = round((datetime.utcnow() - t0).total_seconds() * 1000, 1)
        mongo_info = {
            "status": "ok",
            "order_events_count": order_events,
            "error_events_count": error_events,
            "open_issues": open_issues,
            "query_time_ms": query_ms,
        }
    except Exception as exc:
        mongo_info = {"status": "error", "error": str(exc)[:200]}

    # ── Elasticsearch ──
    es_info: dict = {}
    try:
        from app.database.elasticsearch_client import es_client as _es
        if _es is not None:
            health = await _es.cluster.health()
            orders_resp = await _es.count(index="oms_orders")
            products_resp = await _es.count(index="oms_products")
            es_info = {
                "status": health.get("status", "unknown"),
                "cluster_name": health.get("cluster_name"),
                "active_shards": health.get("active_shards"),
                "orders_index_count": orders_resp.get("count", 0),
                "products_index_count": products_resp.get("count", 0),
            }
        else:
            es_info = {"status": "unavailable"}
    except Exception as exc:
        es_info = {"status": "error", "error": str(exc)[:200]}

    return {
        "redis": redis_info,
        "queue_depths": queue_depths,
        "postgres": pg_info,
        "mongodb": mongo_info,
        "elasticsearch": es_info,
        "collected_at": datetime.utcnow().isoformat(),
    }


# ─── Pipeline Metrics ──────────────────────────────────────────────────────────

@router.get("/pipeline")
async def pipeline_metrics(
    hours: int = Query(default=24, ge=1, le=720),
    _: dict = Depends(require_superadmin),
    mdb=Depends(get_mongo_db),
):
    """Order pipeline funnel, rates, and average stage durations for the selected period."""
    from_ts = datetime.utcnow() - timedelta(hours=hours)

    # Aggregate: first timestamp per (order_id, event_type) → group by order_id
    pipeline = [
        {"$match": {
            "event_type": {"$in": STAGE_EVENTS},
            "timestamp": {"$gte": from_ts},
        }},
        {"$group": {
            "_id": {"order_id": "$order_id", "event_type": "$event_type"},
            "ts": {"$min": "$timestamp"},
        }},
        {"$group": {
            "_id": "$_id.order_id",
            "events": {"$push": {"et": "$_id.event_type", "ts": "$ts"}},
        }},
    ]

    created = sourced = shipped = delivered = backordered = cancelled = 0
    dur_created_sourced: list[float] = []
    dur_sourced_shipped: list[float] = []
    dur_shipped_delivered: list[float] = []

    async for doc in mdb.order_events.aggregate(pipeline):
        ev_map = {e["et"]: e["ts"] for e in doc["events"]}

        if "order.created" in ev_map:
            created += 1
        if "order.sourced" in ev_map:
            sourced += 1
        if "order.shipped" in ev_map:
            shipped += 1
        if "order.delivered" in ev_map:
            delivered += 1
        if "order.backordered" in ev_map:
            backordered += 1
        if "order.cancelled" in ev_map:
            cancelled += 1

        # Compute stage durations (only if both events present and sane)
        if "order.created" in ev_map and "order.sourced" in ev_map:
            diff = (ev_map["order.sourced"] - ev_map["order.created"]).total_seconds()
            if 0 <= diff < 3600:
                dur_created_sourced.append(diff)

        if "order.sourced" in ev_map and "order.shipped" in ev_map:
            diff = (ev_map["order.shipped"] - ev_map["order.sourced"]).total_seconds()
            if 0 <= diff < 86400:
                dur_sourced_shipped.append(diff)

        if "order.shipped" in ev_map and "order.delivered" in ev_map:
            diff = (ev_map["order.delivered"] - ev_map["order.shipped"]).total_seconds()
            if 0 <= diff < 86400:
                dur_shipped_delivered.append(diff)

    def _avg(lst: list[float]):
        return round(sum(lst) / len(lst), 1) if lst else None

    return {
        "period_hours": hours,
        "from_ts": from_ts.isoformat(),
        "funnel": {
            "created": created,
            "sourced": sourced,
            "shipped": shipped,
            "delivered": delivered,
            "backordered": backordered,
            "cancelled": cancelled,
        },
        "rates": {
            "sourcing_success_rate": round(sourced / max(created, 1) * 100, 1),
            "backorder_rate": round(backordered / max(created, 1) * 100, 1),
            "fulfillment_rate": round(shipped / max(sourced, 1) * 100, 1),
            "delivery_rate": round(delivered / max(shipped, 1) * 100, 1),
        },
        "avg_durations_seconds": {
            "created_to_sourced": _avg(dur_created_sourced),
            "sourced_to_shipped": _avg(dur_sourced_shipped),
            "shipped_to_delivered": _avg(dur_shipped_delivered),
        },
        "sample_sizes": {
            "created_to_sourced": len(dur_created_sourced),
            "sourced_to_shipped": len(dur_sourced_shipped),
            "shipped_to_delivered": len(dur_shipped_delivered),
        },
    }


# ─── Throughput by Hour ────────────────────────────────────────────────────────

@router.get("/throughput")
async def throughput_by_hour(
    hours: int = Query(default=24, ge=1, le=720),
    _: dict = Depends(require_superadmin),
    mdb=Depends(get_mongo_db),
):
    """Orders created / shipped / delivered per time bucket for the selected period."""
    from_ts = datetime.utcnow() - timedelta(hours=hours)
    # Auto-select bucket granularity
    bin_size = 1 if hours <= 48 else (4 if hours <= 168 else 24)

    pipeline = [
        {"$match": {
            "event_type": {"$in": ["order.created", "order.shipped", "order.delivered"]},
            "timestamp": {"$gte": from_ts},
        }},
        {"$group": {
            "_id": {
                "bucket": {
                    "$dateTrunc": {
                        "date": "$timestamp",
                        "unit": "hour",
                        "binSize": bin_size,
                    }
                },
                "event_type": "$event_type",
            },
            "count": {"$sum": 1},
        }},
        {"$sort": {"_id.bucket": 1}},
    ]

    bucket_map: dict = {}
    async for doc in mdb.order_events.aggregate(pipeline):
        raw_bucket = doc["_id"]["bucket"]
        key = raw_bucket.isoformat() if isinstance(raw_bucket, datetime) else str(raw_bucket)
        et = doc["_id"]["event_type"]
        if key not in bucket_map:
            bucket_map[key] = {"hour": key, "created": 0, "shipped": 0, "delivered": 0}
        field = et.replace("order.", "")  # "created", "shipped", "delivered"
        bucket_map[key][field] = doc["count"]

    return sorted(bucket_map.values(), key=lambda x: x["hour"])
