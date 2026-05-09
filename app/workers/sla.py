"""
SLA breach detection worker.

Scans in-flight orders against per-step SLA targets defined in their assigned
lifecycle.  For each order whose current status has been active longer than the
configured ``sla_hours``, the worker:

1. Emits an ``order.sla_breach`` audit event to the environment's MongoDB
   ``order_events`` collection.
2. Increments a daily Redis counter at key
   ``sla_breaches:{environment_id}:{YYYY-MM-DD}`` (TTL 24 h).

The ``GET /monitoring/sla-summary`` endpoint reads this counter so the frontend
can display a real-time breach count without querying MongoDB.

Tasks
-----
``check_sla_breaches(environment_id)``
    Per-environment task.  Uses a synchronous SQLAlchemy session (Celery
    context) and an ephemeral asyncio loop for the MongoDB write.

``check_sla_breaches_fanout``
    Beat task.  Dispatches ``check_sla_breaches`` for every active environment.
    Configured to run every 15 minutes via the Celery beat schedule.
"""
import logging
from datetime import datetime

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Statuses that are still in-flight and eligible for SLA monitoring
_SLA_TRACKED_STATUSES = (
    "PENDING",
    "CONFIRMED",
    "SOURCED",
    "BACKORDERED",
    "PICKING",
    "PACKING",
)


def _get_sync_session(environment_id: str = ""):
    """Create a synchronous SQLAlchemy session for Celery tasks."""
    import re
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.workers.env_utils import get_env_db_url

    sync_url = re.sub(r"\+asyncpg", "", get_env_db_url(environment_id))
    engine = create_engine(sync_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def _log_event_sync(order_id: str, event_type: str, data: dict, environment_id: str = ""):
    """Write an audit event to MongoDB from a synchronous Celery context."""
    import asyncio
    from app.config import settings
    from app.workers.env_utils import get_env_mongo_events_db

    mongo_events_db = get_env_mongo_events_db(environment_id)

    async def _do():
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=5000, uuidRepresentation="standard")
        try:
            await client[mongo_events_db].order_events.insert_one({
                "order_id": order_id,
                "event_type": event_type,
                "timestamp": datetime.utcnow(),
                "data": data,
            })
        finally:
            client.close()

    try:
        asyncio.run(_do())
    except Exception as exc:
        logger.warning(f"Failed to log event {event_type} for order {order_id}: {exc}")


@celery_app.task(
    name="app.workers.sla.check_sla_breaches",
    queue="fulfillment",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    acks_late=True,
    reject_on_worker_lost=True,
)
def check_sla_breaches(self, environment_id: str = "") -> int:
    """
    Scan orders in non-terminal statuses that have a lifecycle_id set.
    For each lifecycle step with sla_hours configured, emit an order.sla_breach
    event and increment a daily Redis counter when the elapsed time exceeds the SLA.
    Returns the count of breaches found.
    """
    import re
    from sqlalchemy import create_engine, text
    from app.config import settings
    from app.workers.env_utils import get_env_db_url

    now = datetime.utcnow()
    date_str = now.strftime("%Y-%m-%d")
    import re as _re
    _env_raw = environment_id or "default"
    env_label = _env_raw if _re.match(r'^[a-zA-Z0-9_-]+$', _env_raw) else "default"
    redis_key = f"sla_breaches:{env_label}:{date_str}"

    # Build a lookup of lifecycle step SLA hours keyed by (lifecycle_id, status)
    # using the same raw SQL pattern as resolve_lifecycle_sync in lifecycle_engine.py
    sync_url = re.sub(r"\+asyncpg", "", get_env_db_url(environment_id))
    engine = create_engine(sync_url, pool_pre_ping=True)

    try:
        with engine.connect() as conn:
            # Fetch all active lifecycle steps that carry an sla_hours value
            step_rows = conn.execute(text("""
                SELECT CAST(ls.lifecycle_id AS VARCHAR), ls.status, ls.sla_hours
                FROM lifecycle_steps ls
                JOIN lifecycles l ON l.id = ls.lifecycle_id
                WHERE l.is_active = TRUE
                  AND ls.sla_hours IS NOT NULL
                  AND ls.sla_hours > 0
            """)).fetchall()

            if not step_rows:
                logger.debug("check_sla_breaches: no lifecycle steps with sla_hours configured")
                return 0

            # Build lookup: (lifecycle_id_str, status_str) -> sla_hours
            sla_map: dict[tuple, float] = {}
            for row in step_rows:
                sla_map[(str(row[0]), str(row[1]))] = float(row[2])

            # Fetch orders in tracked non-terminal statuses that have a lifecycle assigned
            status_placeholders = ", ".join(f":s{i}" for i in range(len(_SLA_TRACKED_STATUSES)))
            status_params = {f"s{i}": s for i, s in enumerate(_SLA_TRACKED_STATUSES)}
            order_rows = conn.execute(
                text(f"""
                    SELECT CAST(id AS VARCHAR), CAST(lifecycle_id AS VARCHAR),
                           status, updated_at
                    FROM orders
                    WHERE status IN ({status_placeholders})
                      AND lifecycle_id IS NOT NULL
                """),
                status_params,
            ).fetchall()

        breach_count = 0

        try:
            import redis as redis_lib
            r = redis_lib.from_url(settings.REDIS_URL)
        except Exception as redis_exc:
            logger.warning(f"check_sla_breaches: Redis unavailable — breach counts will not be recorded: {redis_exc}")
            r = None

        for row in order_rows:
            order_id = str(row[0])
            lifecycle_id = str(row[1])
            status = str(row[2])
            updated_at = row[3]

            if updated_at is None:
                continue

            sla_hours = sla_map.get((lifecycle_id, status))
            if sla_hours is None:
                continue

            elapsed_hours = (now - updated_at).total_seconds() / 3600.0
            if elapsed_hours <= sla_hours:
                continue

            breach_count += 1
            logger.warning(
                f"SLA breach: order {order_id} has been in status {status} "
                f"for {elapsed_hours:.1f}h (SLA={sla_hours}h, lifecycle={lifecycle_id})"
            )

            # Emit audit event
            _log_event_sync(
                order_id,
                "order.sla_breach",
                {
                    "status": status,
                    "sla_hours": sla_hours,
                    "breach_hours": round(elapsed_hours, 2),
                    "lifecycle_id": lifecycle_id,
                },
                environment_id,
            )

            # Increment daily Redis counter
            if r is not None:
                try:
                    r.incr(redis_key)
                    r.expire(redis_key, 86400)
                except Exception as redis_inc_exc:
                    logger.warning(f"check_sla_breaches: failed to increment Redis counter: {redis_inc_exc}")

        logger.info(f"check_sla_breaches: {breach_count} breach(es) found (env={env_label})")
        return breach_count

    except Exception as exc:
        logger.exception(f"check_sla_breaches failed for env {env_label}: {exc}")
        raise self.retry(exc=exc)
    finally:
        engine.dispose()


@celery_app.task(
    name="app.workers.sla.check_sla_breaches_fanout",
    queue="fulfillment",
)
def check_sla_breaches_fanout():
    """Beat task: dispatch check_sla_breaches to every active environment."""
    from app.workers.env_utils import list_active_environment_ids

    for env_id in list_active_environment_ids():
        check_sla_breaches.delay(env_id)
