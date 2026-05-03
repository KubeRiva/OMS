"""Celery worker: outbound inventory sync to external connectors."""
import asyncio
import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from app.workers.celery_app import celery_app
from app.database.postgres import async_session_factory
from app.models.postgres.connector_models import (
    Connector, ConnectorEvent, ConnectorInventoryMapping, ConnectorStatus,
)

logger = logging.getLogger(__name__)


async def _async_push_inventory(inventory_item_id: str, quantity_available: int) -> None:
    """Push updated stock level to every active connector that has a mapping for this item."""
    from app.services.connectors.registry import get_connector
    from app.models.postgres.inventory_models import InventoryItem

    async with async_session_factory() as db:
        item = await db.get(InventoryItem, UUID(inventory_item_id))
        if not item:
            logger.warning("push_inventory: InventoryItem %s not found", inventory_item_id)
            return

        # Load all active connectors that map this inventory item
        result = await db.execute(
            select(ConnectorInventoryMapping, Connector)
            .join(Connector, ConnectorInventoryMapping.connector_id == Connector.id)
            .where(
                ConnectorInventoryMapping.inventory_item_id == UUID(inventory_item_id),
                Connector.status == ConnectorStatus.ACTIVE,
            )
        )
        rows = result.all()

        if not rows:
            logger.debug("push_inventory: no active connector mappings for item %s", inventory_item_id)
            return

        for mapping, connector in rows:
            try:
                impl = get_connector(connector)
                response = await impl.push_inventory_update(item.sku, quantity_available, mapping)

                event = ConnectorEvent(
                    connector_id=connector.id,
                    event_type="inventory.pushed",
                    direction="outbound",
                    status="success",
                    payload={
                        "inventory_item_id": str(item.id),
                        "sku": item.sku,
                        "quantity_available": quantity_available,
                    },
                    response=response,
                )
                db.add(event)
                connector.last_synced_at = datetime.utcnow()
                await db.commit()
                logger.info(
                    "push_inventory: pushed sku=%s qty=%d to connector %s",
                    item.sku, quantity_available, connector.id,
                )

            except Exception as exc:
                logger.exception(
                    "push_inventory: failed for sku=%s on connector %s", item.sku, connector.id
                )
                event = ConnectorEvent(
                    connector_id=connector.id,
                    event_type="inventory.pushed",
                    direction="outbound",
                    status="failed",
                    payload={
                        "inventory_item_id": str(item.id),
                        "sku": item.sku,
                        "quantity_available": quantity_available,
                    },
                    error_message=str(exc),
                )
                db.add(event)
                connector.status = ConnectorStatus.ERROR
                connector.last_error = str(exc)
                connector.last_error_at = datetime.utcnow()
                await db.commit()


@celery_app.task(
    name="app.workers.inventory_sync.push_inventory_to_connectors",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def push_inventory_to_connectors(self, inventory_item_id: str, quantity_available: int) -> None:
    """
    Push updated inventory quantity to all connector platforms that track this SKU.
    Triggered after any inventory adjustment (receive, count, adjustment).
    """
    try:
        asyncio.run(_async_push_inventory(inventory_item_id, quantity_available))
    except Exception as exc:
        logger.exception(
            "push_inventory_to_connectors task failed for item %s", inventory_item_id
        )
        from app.services.monitoring import capture_error_sync, SOURCE_CONNECTOR
        capture_error_sync(
            exc,
            SOURCE_CONNECTOR,
            task_context={
                "task": "push_inventory_to_connectors",
                "queue": "connectors",
                "retry": self.request.retries,
            },
            extra={"inventory_item_id": inventory_item_id, "quantity": quantity_available},
        )
        raise self.retry(exc=exc)
