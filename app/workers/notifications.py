"""Notifications worker — email/SMS stub (logs to MongoDB)."""
import logging
from datetime import datetime

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _log_notification(order_id: str, notification_type: str, recipient: str, message: str):
    """Log notification to MongoDB."""
    try:
        from pymongo import MongoClient
        from app.config import settings
        client = MongoClient(settings.MONGODB_URL.replace("+srv", ""))
        db = client[settings.MONGODB_DB]
        db.notifications.insert_one({
            "order_id": order_id,
            "type": notification_type,
            "recipient": recipient,
            "message": message,
            "sent_at": datetime.utcnow(),
            "status": "SENT",
        })
        client.close()
    except Exception as e:
        logger.warning(f"Failed to log notification: {e}")


def _get_order_email(order_id: str) -> str:
    """Fetch customer email from PostgreSQL."""
    from sqlalchemy import create_engine, text
    from app.config import settings
    engine = create_engine(settings.SYNC_DATABASE_URL)
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT customer_email, customer_name FROM orders WHERE id = :id"),
            {"id": order_id}
        )
        row = result.fetchone()
        engine.dispose()
        return (row[0], row[1]) if row else ("unknown@example.com", "Customer")


@celery_app.task(name="app.workers.notifications.send_order_confirmation", queue="notifications")
def send_order_confirmation(order_id: str):
    email, name = _get_order_email(order_id)
    message = f"Hi {name}, your order has been confirmed! Order ID: {order_id}"
    logger.info(f"[EMAIL] To: {email} | {message}")
    _log_notification(order_id, "ORDER_CONFIRMATION", email, message)


@celery_app.task(name="app.workers.notifications.send_packing_notification", queue="notifications")
def send_packing_notification(order_id: str):
    email, name = _get_order_email(order_id)
    message = f"Hi {name}, your order is being packed and will ship soon!"
    logger.info(f"[EMAIL] To: {email} | {message}")
    _log_notification(order_id, "PACKING", email, message)


@celery_app.task(name="app.workers.notifications.send_shipment_notification", queue="notifications")
def send_shipment_notification(order_id: str, tracking_number: str, carrier: str, est_delivery: str):
    email, name = _get_order_email(order_id)
    message = (
        f"Hi {name}, your order has shipped! "
        f"Track it with {carrier}: {tracking_number}. "
        f"Estimated delivery: {est_delivery[:10]}"
    )
    logger.info(f"[EMAIL] To: {email} | {message}")
    _log_notification(order_id, "SHIPMENT", email, message)


@celery_app.task(name="app.workers.notifications.send_delivery_notification", queue="notifications")
def send_delivery_notification(order_id: str):
    email, name = _get_order_email(order_id)
    message = f"Hi {name}, your order has been delivered! Thank you for shopping with us."
    logger.info(f"[EMAIL] To: {email} | {message}")
    _log_notification(order_id, "DELIVERY", email, message)


@celery_app.task(name="app.workers.notifications.send_pickup_ready_notification", queue="notifications")
def send_pickup_ready_notification(order_id: str):
    email, name = _get_order_email(order_id)
    message = (
        f"Hi {name}, your order is ready for pickup! "
        f"Please bring a valid ID when you collect your order."
    )
    logger.info(f"[EMAIL] To: {email} | {message}")
    _log_notification(order_id, "PICKUP_READY", email, message)


@celery_app.task(name="app.workers.notifications.send_cancellation_notification", queue="notifications")
def send_cancellation_notification(order_id: str, reason: str):
    email, name = _get_order_email(order_id)
    message = f"Hi {name}, your order has been cancelled. Reason: {reason}"
    logger.info(f"[EMAIL] To: {email} | {message}")
    _log_notification(order_id, "CANCELLATION", email, message)


@celery_app.task(
    name="app.workers.notifications.send_approval_request_notification",
    queue="notifications",
)
def send_approval_request_notification(
    order_id: str,
    account_name: str,
    total_amount: float,
    order_number: str,
):
    """Log approval request — in production this would email the approver."""
    logger.info(
        "APPROVAL REQUIRED: Order %s (%s) for account '%s' — amount %.2f requires approval",
        order_number, order_id, account_name, total_amount,
    )
    # TODO: integrate with email/Slack when notification service is configured
    _log_notification(
        order_id,
        "APPROVAL_REQUEST",
        "approver@internal",
        (
            f"Order {order_number} for account '{account_name}' "
            f"requires approval — total: {total_amount:.2f}"
        ),
    )
