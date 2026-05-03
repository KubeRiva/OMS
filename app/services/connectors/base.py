"""Abstract base class for all connector implementations."""
from abc import ABC, abstractmethod
from typing import Any


class BaseConnector(ABC):
    """
    Abstract connector that every platform integration must implement.

    Each subclass handles:
    - Validating inbound webhook authenticity (HMAC or similar)
    - Extracting the event type from platform-specific headers
    - Normalizing the inbound payload to an OMS-compatible order dict
    - Pushing fulfillment/tracking updates back to the platform
    - Testing connectivity with stored credentials
    """

    def __init__(self, connector: Any):
        self.connector = connector
        self.config: dict = connector.config or {}

    @abstractmethod
    def validate_webhook(self, headers: dict, raw_body: bytes) -> bool:
        """
        Validate the authenticity of an inbound webhook request.

        Returns True if the signature/HMAC is valid, False otherwise.
        """
        ...

    @abstractmethod
    def get_event_type(self, headers: dict) -> str:
        """
        Extract the platform-specific event type from headers.

        E.g. for Shopify: returns 'orders/create' from X-Shopify-Topic.
        """
        ...

    @abstractmethod
    def normalize_order(self, payload: dict) -> dict:
        """
        Transform a platform-specific order payload into an OMS OrderCreate-compatible dict.

        The returned dict must contain at minimum:
          channel, fulfillment_type, customer_email, line_items, external_order_id
        """
        ...

    @abstractmethod
    async def push_fulfillment(self, order: Any, shipment: Any) -> dict:
        """
        Push a fulfillment/tracking update to the external platform.

        Returns the platform's response as a dict.
        Raises on HTTP errors so the caller can log the failure.
        """
        ...

    @abstractmethod
    async def test_connection(self) -> dict:
        """
        Verify stored credentials and connectivity.

        Returns {"success": True/False, "message": str, "details": dict|None}
        """
        ...

    def get_inbound_topics(self) -> set[str]:
        """
        Return the set of event types this connector handles for order creation.
        Override in subclasses if needed.
        """
        return set()

    def get_product_topics(self) -> set[str]:
        """
        Return the set of event types this connector handles for product/catalog sync.
        Override in subclasses that support product webhooks.
        """
        return set()

    def normalize_product(self, payload: dict) -> list[dict]:
        """
        Transform a platform-specific product payload into a list of variant dicts.
        Each dict must contain: sku, product_name, quantity, unit_cost.
        Override in subclasses that support product webhooks.
        """
        return []

    async def push_inventory_update(self, sku: str, quantity_available: int, mapping: Any) -> dict:
        """
        Push a live inventory quantity update to the external platform.

        Args:
            sku: The OMS SKU being updated.
            quantity_available: The new available quantity to push.
            mapping: ConnectorInventoryMapping ORM row with platform-specific IDs.

        Returns the platform's response as a dict.
        Raises on HTTP errors so the caller can log the failure.

        Default is a no-op — override in connectors that support inventory push.
        """
        return {"skipped": True, "reason": "push_inventory_update not implemented for this connector"}

    async def push_order_cancel(self, order: Any) -> dict:
        """
        Cancel an order on the external platform when it is cancelled in the OMS.

        Default is a no-op — override in connectors that support cancellation.
        """
        return {"skipped": True, "reason": "push_order_cancel not implemented for this connector"}
