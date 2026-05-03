"""Pydantic schemas for the Connector system."""
from __future__ import annotations
from typing import Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, model_validator

from app.models.postgres.connector_models import (
    ConnectorType, ConnectorDirection, ConnectorStatus,
)

# Sensitive config keys that are masked in API responses
_SENSITIVE_KEYS = {"access_token", "webhook_secret", "api_key", "api_secret",
                   "consumer_secret", "client_secret", "refresh_token", "secret"}


def _mask_config(config: dict) -> dict:
    """Replace sensitive config values with '***' for API responses."""
    if not config:
        return {}
    return {k: "***" if k in _SENSITIVE_KEYS and v else v for k, v in config.items()}


# ─── Request Schemas ──────────────────────────────────────────────────────────

class ConnectorCreate(BaseModel):
    name: str
    connector_type: ConnectorType
    direction: ConnectorDirection = ConnectorDirection.BIDIRECTIONAL
    config: dict = {}


class ConnectorUpdate(BaseModel):
    name: Optional[str] = None
    direction: Optional[ConnectorDirection] = None
    status: Optional[ConnectorStatus] = None
    config: Optional[dict] = None


# ─── Response Schemas ─────────────────────────────────────────────────────────

class ConnectorResponse(BaseModel):
    id: UUID
    name: str
    connector_type: ConnectorType
    direction: ConnectorDirection
    status: ConnectorStatus
    config: dict           # sensitive fields masked
    orders_received: int
    orders_synced: int
    last_error: Optional[str] = None
    last_error_at: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    webhook_url: Optional[str] = None  # populated in router

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def mask_sensitive(cls, values):
        if hasattr(values, "__dict__"):
            # SQLAlchemy ORM object
            d = values.__dict__
            raw_config = d.get("config") or {}
            values.__dict__["config"] = _mask_config(raw_config)
        elif isinstance(values, dict):
            if "config" in values:
                values["config"] = _mask_config(values["config"] or {})
        return values


class ConnectorEventResponse(BaseModel):
    id: UUID
    connector_id: UUID
    order_id: Optional[UUID] = None
    external_order_id: Optional[str] = None
    event_type: str
    direction: str
    status: str
    error_message: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConnectorTestResult(BaseModel):
    success: bool
    message: str
    details: Optional[dict] = None


class ConnectorToggleResponse(BaseModel):
    id: UUID
    status: ConnectorStatus
