"""Celery application factory with 5 named queues."""
from celery import Celery
from celery.schedules import crontab
from app.config import settings

celery_app = Celery(
    "oms",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.workers.sourcing",
        "app.workers.fulfillment",
        "app.workers.carrier",
        "app.workers.notifications",
        "app.workers.webhooks",
        "app.workers.connectors",
        "app.workers.inventory_sync",
        "app.workers.learning",
        "app.workers.sla",
    ],
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Queues
    task_default_queue="fulfillment",
    task_queues={
        "sourcing": {
            "exchange": "sourcing",
            "routing_key": "sourcing",
        },
        "fulfillment": {
            "exchange": "fulfillment",
            "routing_key": "fulfillment",
        },
        "carrier": {
            "exchange": "carrier",
            "routing_key": "carrier",
        },
        "notifications": {
            "exchange": "notifications",
            "routing_key": "notifications",
        },
        "webhooks": {
            "exchange": "webhooks",
            "routing_key": "webhooks",
        },
        "connectors": {
            "exchange": "connectors",
            "routing_key": "connectors",
        },
        "learning": {
            "exchange": "learning",
            "routing_key": "learning",
        },
    },

    # Task routing
    task_routes={
        "app.workers.sourcing.*": {"queue": "sourcing"},
        "app.workers.fulfillment.*": {"queue": "fulfillment"},
        "app.workers.carrier.*": {"queue": "carrier"},
        "app.workers.notifications.*": {"queue": "notifications"},
        "app.workers.webhooks.*": {"queue": "webhooks"},
        "app.workers.connectors.*": {"queue": "connectors"},
        "app.workers.inventory_sync.*": {"queue": "connectors"},
        "app.workers.learning.*": {"queue": "learning"},
    },

    # Retry config
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_max_retries=3,
    task_default_retry_delay=60,

    # Result expiry
    result_expires=86400,  # 1 day

    # Beat schedule
    beat_schedule={
        "reset-daily-node-counters": {
            "task": "app.workers.fulfillment.reset_node_daily_counters",
            "schedule": crontab(hour=0, minute=0),
        },
        "retry-failed-webhooks": {
            "task": "app.workers.webhooks.retry_failed_webhooks",
            "schedule": crontab(minute="*/5"),
        },
        "process-packed-allocations": {
            "task": "app.workers.carrier.process_packed_allocations_without_shipments",
            "schedule": crontab(minute="*/10"),
        },
        "sync-carrier-tracking": {
            "task": "app.workers.carrier.sync_all_tracking",
            "schedule": crontab(minute="*/15"),
        },
        "retry-backordered-orders": {
            "task": "app.workers.sourcing.retry_backordered_orders_fanout",
            "schedule": crontab(minute="*/1"),
        },
        "source-pending-orders": {
            "task": "app.workers.sourcing.source_pending_orders_fanout",
            "schedule": crontab(minute="*/2"),
        },
        "poll-amazon-orders": {
            "task": "app.workers.connectors.poll_amazon_orders",
            "schedule": crontab(minute="*/15"),
        },
        "label-sourcing-outcomes": {
            "task": "app.workers.learning.label_sourcing_outcomes_fanout",
            "schedule": crontab(minute=0),        # Hourly at :00
        },
        "discover-patterns": {
            "task": "app.workers.learning.discover_patterns_fanout",
            "schedule": crontab(hour=2, minute=0),  # Nightly at 02:00 UTC
        },
        "update-node-performance": {
            "task": "app.workers.learning.update_node_performance_fanout",
            "schedule": crontab(minute=0, hour="*/4"),  # Every 4 hours
        },
        "evaluate-ai-experiments": {
            "task": "app.workers.learning.evaluate_ai_experiments_fanout",
            "schedule": crontab(hour=3, minute=0),  # Daily at 03:00 UTC
        },
        "check-sla-breaches": {
            "task": "app.workers.sla.check_sla_breaches_fanout",
            "schedule": crontab(minute="*/15"),
        },
    },
)
