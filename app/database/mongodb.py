from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from typing import Optional
from app.config import settings
import logging

logger = logging.getLogger(__name__)

mongo_client: Optional[AsyncIOMotorClient] = None


async def connect_to_mongo():
    global mongo_client
    mongo_client = AsyncIOMotorClient(settings.MONGODB_URL)
    # Verify connection
    await mongo_client.admin.command("ping")
    logger.info("Connected to MongoDB")

    # Create indexes for both databases
    db = mongo_client[settings.MONGODB_DB]
    await _create_indexes(db)
    ai_db = mongo_client[settings.MONGODB_AI_DB]
    await _create_ai_indexes(ai_db)


async def close_mongo_connection():
    global mongo_client
    if mongo_client:
        mongo_client.close()
        logger.info("Disconnected from MongoDB")


async def get_mongo_db() -> AsyncIOMotorDatabase:
    """Returns the main events database (order_events, webhooks, errors)."""
    if mongo_client is None:
        raise RuntimeError("MongoDB client not initialized. Call connect_to_mongo() first.")
    return mongo_client[settings.MONGODB_DB]


async def get_mongo_ai_db() -> AsyncIOMotorDatabase:
    """Returns the AI learning database (sourcing_outcomes, sourcing_patterns, node_performance_metrics)."""
    if mongo_client is None:
        raise RuntimeError("MongoDB client not initialized. Call connect_to_mongo() first.")
    return mongo_client[settings.MONGODB_AI_DB]


async def _create_indexes(db: AsyncIOMotorDatabase):
    """Create MongoDB indexes for the main oms_events database."""
    # Order events collection
    await db.order_events.create_index([("order_id", 1), ("timestamp", -1)])
    await db.order_events.create_index([("event_type", 1)])
    await db.order_events.create_index([("timestamp", -1)])

    # Product catalog collection
    await db.product_catalog.create_index([("sku", 1)], unique=True)
    await db.product_catalog.create_index([("category", 1)])
    await db.product_catalog.create_index([("name", "text"), ("description", "text")])

    # Webhook delivery log
    await db.webhook_deliveries.create_index([("webhook_id", 1), ("created_at", -1)])
    await db.webhook_deliveries.create_index([("status", 1)])

    # ── Monitoring: error events (one doc per occurrence) ──────────────────
    await db.error_events.create_index([("timestamp", -1)])
    await db.error_events.create_index([("fingerprint", 1), ("timestamp", -1)])
    await db.error_events.create_index([("source_service", 1), ("timestamp", -1)])
    await db.error_events.create_index([("level", 1), ("timestamp", -1)])
    await db.error_events.create_index([("order_context.order_id", 1)])
    await db.error_events.create_index([("error_type", 1)])
    # 30-day TTL — raw events auto-expire
    await db.error_events.create_index(
        [("timestamp", 1)],
        expireAfterSeconds=2_592_000,
        name="error_events_ttl",
    )

    # ── Monitoring: error issues (one doc per fingerprint, aggregated) ─────
    await db.error_issues.create_index([("fingerprint", 1)], unique=True)
    await db.error_issues.create_index([("status", 1), ("last_seen_at", -1)])
    await db.error_issues.create_index([("source_service", 1), ("status", 1)])
    await db.error_issues.create_index([("level", 1), ("occurrence_count", -1)])
    await db.error_issues.create_index([("last_seen_at", -1)])

    logger.info("MongoDB indexes created (oms_events)")


async def _create_ai_indexes(db: AsyncIOMotorDatabase):
    """Create MongoDB indexes for the oms_ai_learning database."""

    # ── sourcing_outcomes: one doc per allocation decision ────────────────
    await db.sourcing_outcomes.create_index([("order_id", 1)])
    await db.sourcing_outcomes.create_index([("allocation_id", 1)])
    await db.sourcing_outcomes.create_index([("node_id", 1), ("sourced_at", -1)])
    await db.sourcing_outcomes.create_index([("cluster_key", 1), ("outcome_score", -1)])
    await db.sourcing_outcomes.create_index([("outcome_score", -1)])
    await db.sourcing_outcomes.create_index([("labeled_at", -1)])
    await db.sourcing_outcomes.create_index([("experiment_id", 1), ("strategy_used", 1)])
    await db.sourcing_outcomes.create_index(
        [("sourced_at", -1)],
        name="sourcing_outcomes_sourced_at",
    )
    # 90-day TTL — outcomes expire after 3 months; patterns retain the aggregated learnings
    await db.sourcing_outcomes.create_index(
        [("sourced_at", 1)],
        expireAfterSeconds=7_776_000,  # 90 days
        name="sourcing_outcomes_ttl",
    )

    # ── sourcing_patterns: one doc per cluster_key ────────────────────────
    await db.sourcing_patterns.create_index([("cluster_key", 1)], unique=True)
    await db.sourcing_patterns.create_index([("channel", 1), ("region", 1)])
    await db.sourcing_patterns.create_index([("sample_count", -1)])
    await db.sourcing_patterns.create_index([("computed_at", -1)])
    # 180-day TTL — stale patterns expire; nightly discovery re-creates active ones
    await db.sourcing_patterns.create_index(
        [("computed_at", 1)],
        expireAfterSeconds=15_552_000,  # 180 days
        name="sourcing_patterns_ttl",
    )

    # ── node_performance_metrics: rolling stats per node ─────────────────
    await db.node_performance_metrics.create_index(
        [("node_id", 1), ("period_days", 1)], unique=True
    )
    await db.node_performance_metrics.create_index([("avg_outcome_score", -1)])
    await db.node_performance_metrics.create_index([("computed_at", -1)])

    logger.info("MongoDB indexes created (oms_ai_learning)")
