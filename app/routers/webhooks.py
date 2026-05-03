"""Webhooks router — HMAC-signed endpoint management."""
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
from uuid import UUID
import secrets

from app.database.postgres import get_db
from app.dependencies.auth import require_superadmin, get_current_user
from app.models.postgres.order_models import WebhookEndpoint, WebhookEvent
from app.schemas.webhooks import (
    WebhookEndpointCreate, WebhookEndpointUpdate,
    WebhookEndpointResponse, WebhookEventResponse, WebhookDeliveryTest,
)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.get("/event-types", response_model=dict)
async def get_event_types(_: dict = Depends(get_current_user)):
    """Return all supported webhook event types grouped by category."""
    return {
        "event_types": [
            "order.created", "order.confirmed", "order.sourced", "order.sourcing_failed",
            "order.picking", "order.packing", "order.ready_to_ship",
            "order.shipped", "order.out_for_delivery", "order.delivered",
            "order.cancelled", "order.returned", "order.test",
        ],
        "groups": [
            {"label": "Lifecycle", "events": ["order.created", "order.confirmed"]},
            {"label": "Fulfillment", "events": ["order.sourced", "order.sourcing_failed", "order.picking", "order.packing", "order.ready_to_ship"]},
            {"label": "Shipping", "events": ["order.shipped", "order.out_for_delivery", "order.delivered"]},
            {"label": "Post-order", "events": ["order.cancelled", "order.returned"]},
        ],
    }


@router.post("/endpoints", response_model=WebhookEndpointResponse, status_code=201)
async def create_webhook_endpoint(
    payload: WebhookEndpointCreate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    endpoint = WebhookEndpoint(
        name=payload.name,
        url=payload.url,
        secret=payload.secret,
        is_active=payload.is_active,
        event_types=payload.event_types,
        headers=payload.headers,
    )
    db.add(endpoint)
    await db.flush()
    await db.refresh(endpoint)
    return endpoint


@router.get("/endpoints", response_model=list[WebhookEndpointResponse])
async def list_webhook_endpoints(
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    query = select(WebhookEndpoint)
    if is_active is not None:
        query = query.where(WebhookEndpoint.is_active == is_active)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/endpoints/{endpoint_id}", response_model=WebhookEndpointResponse)
async def get_webhook_endpoint(
    endpoint_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    endpoint = await db.get(WebhookEndpoint, endpoint_id)
    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")
    return endpoint


@router.patch("/endpoints/{endpoint_id}", response_model=WebhookEndpointResponse)
async def update_webhook_endpoint(
    endpoint_id: UUID,
    payload: WebhookEndpointUpdate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    endpoint = await db.get(WebhookEndpoint, endpoint_id)
    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(endpoint, field, value)
    await db.flush()
    await db.refresh(endpoint)
    return endpoint


@router.delete("/endpoints/{endpoint_id}", status_code=204)
async def delete_webhook_endpoint(
    endpoint_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    endpoint = await db.get(WebhookEndpoint, endpoint_id)
    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")
    await db.delete(endpoint)
    await db.flush()


@router.post("/endpoints/{endpoint_id}/test", response_model=dict)
async def test_webhook_endpoint(
    endpoint_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    """Send a test event to the webhook endpoint."""
    endpoint = await db.get(WebhookEndpoint, endpoint_id)
    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")

    test_payload = {
        "event": "order.test",
        "test": True,
        "endpoint_id": str(endpoint_id),
        "message": "This is a test webhook delivery from OMS.",
    }

    background_tasks.add_task(_deliver_test_webhook, endpoint, test_payload)
    return {"message": "Test webhook queued for delivery", "endpoint_id": str(endpoint_id)}


async def _deliver_test_webhook(endpoint: WebhookEndpoint, payload: dict):
    """Deliver test webhook immediately."""
    try:
        from app.services.webhook import WebhookService
        svc = WebhookService()
        await svc.deliver(endpoint.url, endpoint.secret, payload, endpoint.headers or {})
    except Exception:
        pass


@router.get("/events", response_model=list[WebhookEventResponse])
async def list_webhook_events(
    endpoint_id: Optional[UUID] = None,
    status: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    query = select(WebhookEvent).order_by(WebhookEvent.created_at.desc())
    if endpoint_id:
        query = query.where(WebhookEvent.endpoint_id == endpoint_id)
    if status:
        query = query.where(WebhookEvent.status == status)

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/events/{event_id}/retry", response_model=dict)
async def retry_webhook_event(
    event_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    event = await db.get(WebhookEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Webhook event not found")

    if event.status == "DELIVERED":
        raise HTTPException(status_code=400, detail="Event already delivered")

    event.status = "PENDING"
    await db.flush()

    background_tasks.add_task(_retry_webhook_event, str(event_id))
    return {"message": "Retry queued", "event_id": str(event_id)}


async def _retry_webhook_event(event_id: str):
    try:
        from app.workers.celery_app import celery_app
        celery_app.send_task(
            "app.workers.webhooks.retry_webhook_event",
            args=[event_id],
            queue="webhooks",
        )
    except Exception:
        pass
