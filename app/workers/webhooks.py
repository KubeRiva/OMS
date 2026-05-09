"""Webhooks worker — HMAC-signed delivery with retry logic."""
import logging
from datetime import datetime, timedelta

from app.workers.celery_app import celery_app
from app.services.webhook import WebhookService

logger = logging.getLogger(__name__)


def _get_sync_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.config import settings
    engine = create_engine(settings.SYNC_DATABASE_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def _get_order_payload(session, order_id: str) -> dict:
    """Build webhook payload for an order."""
    from app.models.postgres.order_models import Order
    import app.models.postgres.brand_models          # noqa: F401
    import app.models.postgres.b2b_models            # noqa: F401
    import app.models.postgres.auth_models           # noqa: F401
    import app.models.postgres.node_models           # noqa: F401
    import app.models.postgres.sourcing_rule_models  # noqa: F401
    import app.models.postgres.connector_models      # noqa: F401
    order = session.query(Order).filter(Order.id == order_id).first()
    if not order:
        return {"order_id": order_id}
    return {
        "order_id": str(order.id),
        "order_number": order.order_number,
        "status": order.status.value if order.status else None,
        "channel": order.channel.value if order.channel else None,
        "fulfillment_type": order.fulfillment_type.value if order.fulfillment_type else None,
        "customer_email": order.customer_email,
        "total_amount": float(order.total_amount or 0),
        "currency": order.currency,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
    }


@celery_app.task(
    name="app.workers.webhooks.dispatch_webhook",
    queue="webhooks",
    bind=True,
    max_retries=5,
    acks_late=True,
    reject_on_worker_lost=True,
)
def dispatch_webhook(self, order_id: str, event_type: str):
    """Find all active endpoints subscribed to event_type and deliver."""
    from app.models.postgres.order_models import WebhookEndpoint, WebhookEvent
    from app.config import settings

    session, engine = _get_sync_session()
    svc = WebhookService()

    try:
        endpoints = session.query(WebhookEndpoint).filter(
            WebhookEndpoint.is_active == True
        ).all()

        if not endpoints:
            return

        order_payload = _get_order_payload(session, order_id)
        payload = {
            "event_type": event_type,
            "event_id": str(__import__("uuid").uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "data": order_payload,
        }

        for endpoint in endpoints:
            # Check if endpoint is subscribed to this event type
            if endpoint.event_types and event_type not in endpoint.event_types:
                continue

            # Create event record
            event = WebhookEvent(
                endpoint_id=endpoint.id,
                order_id=order_id if order_id else None,
                event_type=event_type,
                payload=payload,
                status="PENDING",
                attempt_count=0,
            )
            session.add(event)
            session.flush()

            # Deliver
            try:
                status_code, response_body = svc.deliver_sync(
                    endpoint.url,
                    endpoint.secret,
                    payload,
                    endpoint.headers or {},
                )
                if 200 <= status_code < 300:
                    event.status = "DELIVERED"
                    event.delivered_at = datetime.utcnow()
                    event.last_response_code = status_code
                    logger.info(f"Webhook delivered to {endpoint.url}: {status_code}")
                else:
                    event.status = "FAILED"
                    event.last_response_code = status_code
                    event.last_response_body = response_body[:500]
                    event.next_retry_at = datetime.utcnow() + timedelta(minutes=5)
                    logger.warning(f"Webhook to {endpoint.url} returned {status_code}")
            except Exception as e:
                event.status = "FAILED"
                event.last_response_body = str(e)[:500]
                event.next_retry_at = datetime.utcnow() + timedelta(minutes=5)
                logger.warning(f"Webhook delivery error to {endpoint.url}: {e}")

            event.attempt_count += 1
            session.commit()

    except Exception as exc:
        session.rollback()
        logger.exception(f"dispatch_webhook failed: {exc}")
        from app.services.monitoring import capture_error_sync, SOURCE_WEBHOOK
        capture_error_sync(exc, SOURCE_WEBHOOK,
            task_context={"task": "dispatch_webhook", "queue": "webhooks", "retry": self.request.retries},
            order_context={"order_id": order_id} if order_id else {})
        raise self.retry(exc=exc, countdown=60)
    finally:
        session.close()
        engine.dispose()


@celery_app.task(
    name="app.workers.webhooks.retry_failed_webhooks",
    queue="webhooks",
)
def retry_failed_webhooks():
    """Periodic: retry all FAILED webhook events that are due."""
    from app.models.postgres.order_models import WebhookEndpoint, WebhookEvent
    from app.config import settings

    session, engine = _get_sync_session()
    svc = WebhookService()

    try:
        now = datetime.utcnow()
        due_events = session.query(WebhookEvent).filter(
            WebhookEvent.status == "FAILED",
            WebhookEvent.next_retry_at <= now,
            WebhookEvent.attempt_count < settings.WEBHOOK_MAX_RETRIES,
        ).limit(50).all()

        logger.info(f"Retrying {len(due_events)} failed webhook events")

        for event in due_events:
            endpoint = session.query(WebhookEndpoint).filter(
                WebhookEndpoint.id == event.endpoint_id
            ).first()
            if not endpoint or not endpoint.is_active:
                event.status = "ABANDONED"
                continue

            try:
                status_code, body = svc.deliver_sync(
                    endpoint.url,
                    endpoint.secret,
                    event.payload,
                    endpoint.headers or {},
                )
                if 200 <= status_code < 300:
                    event.status = "DELIVERED"
                    event.delivered_at = now
                    event.last_response_code = status_code
                else:
                    event.attempt_count += 1
                    backoff = min(5 * (2 ** event.attempt_count), 60)  # cap at 60 min
                    event.next_retry_at = now + timedelta(minutes=backoff)
                    if event.attempt_count >= settings.WEBHOOK_MAX_RETRIES:
                        event.status = "ABANDONED"
            except Exception as e:
                event.attempt_count += 1
                event.last_response_body = str(e)[:500]
                if event.attempt_count >= settings.WEBHOOK_MAX_RETRIES:
                    event.status = "ABANDONED"

        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()
        engine.dispose()


@celery_app.task(
    name="app.workers.webhooks.retry_webhook_event",
    queue="webhooks",
)
def retry_webhook_event(event_id: str):
    """Retry a specific webhook event by ID."""
    from app.models.postgres.order_models import WebhookEndpoint, WebhookEvent

    session, engine = _get_sync_session()
    svc = WebhookService()

    try:
        event = session.query(WebhookEvent).filter(WebhookEvent.id == event_id).first()
        if not event:
            return

        endpoint = session.query(WebhookEndpoint).filter(
            WebhookEndpoint.id == event.endpoint_id
        ).first()
        if not endpoint:
            return

        status_code, body = svc.deliver_sync(
            endpoint.url,
            endpoint.secret,
            event.payload,
            endpoint.headers or {},
        )
        if 200 <= status_code < 300:
            event.status = "DELIVERED"
            event.delivered_at = datetime.utcnow()
        else:
            event.status = "FAILED"
            event.last_response_code = status_code
        event.attempt_count += 1
        session.commit()
    finally:
        session.close()
        engine.dispose()
