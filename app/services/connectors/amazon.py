"""Amazon SP-API connector: inbound order polling + outbound shipment confirmation."""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

from app.services.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

# SP-API regional endpoints
_REGION_HOSTS = {
    "na": "sellingpartnerapi-na.amazon.com",
    "eu": "sellingpartnerapi-eu.amazon.com",
    "fe": "sellingpartnerapi-fe.amazon.com",
}

# Amazon order statuses we want to import
AMAZON_INBOUND_STATUSES = ["Unshipped", "PartiallyShipped"]

# LWA token URL
_LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"


class AmazonSPConnector(BaseConnector):
    """
    Bidirectional Amazon Seller Central SP-API integration.

    Inbound:  OMS polls Amazon every N minutes for Unshipped/PartiallyShipped orders
    Outbound: OMS → Amazon shipment confirmation when order status → SHIPPED
              OMS → Amazon order cancel acknowledgement when order status → CANCELLED

    Required config keys:
      client_id         SP-API app client ID (amzn1.application-oa2-client.xxx)
      client_secret     SP-API app client secret
      refresh_token     LWA refresh token for this seller
      marketplace_id    e.g. "ATVPDKIKX0DER" for US
      seller_id         Merchant/seller ID
      region            "na" | "eu" | "fe"  (default "na")
      api_version       Orders API version (default "v0")
    """

    DEFAULT_REGION = "na"
    DEFAULT_ORDERS_VERSION = "v0"

    # ─── Authentication ───────────────────────────────────────────────────────

    async def _get_access_token(self) -> str:
        """Exchange LWA refresh token for a short-lived access token."""
        client_id = self.config.get("client_id", "")
        client_secret = self.config.get("client_secret", "")
        refresh_token = self.config.get("refresh_token", "")

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                _LWA_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                },
            )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def _base_url(self) -> str:
        region = (self.config.get("region") or self.DEFAULT_REGION).lower()
        host = _REGION_HOSTS.get(region, _REGION_HOSTS["na"])
        return f"https://{host}"

    async def _sp_get(self, path: str, params: dict = None) -> dict:
        """Authenticated GET against the SP-API."""
        token = await self._get_access_token()
        url = f"{self._base_url()}{path}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                url,
                params=params or {},
                headers={
                    "x-amz-access-token": token,
                    "Content-Type": "application/json",
                },
            )
        resp.raise_for_status()
        return resp.json()

    async def _sp_post(self, path: str, body: dict) -> dict:
        """Authenticated POST against the SP-API."""
        token = await self._get_access_token()
        url = f"{self._base_url()}{path}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                json=body,
                headers={
                    "x-amz-access-token": token,
                    "Content-Type": "application/json",
                },
            )
        resp.raise_for_status()
        return resp.json()

    # ─── Inbound: Webhook stubs (Amazon uses polling, not webhooks) ───────────

    def validate_webhook(self, headers: dict, raw_body: bytes) -> bool:
        """Amazon orders arrive via polling, not webhooks. Always True here."""
        return True

    def get_event_type(self, headers: dict) -> str:
        return "orders/poll"

    def get_inbound_topics(self) -> set[str]:
        return set()  # Amazon does not use inbound webhooks

    # ─── Inbound: Polling ─────────────────────────────────────────────────────

    async def fetch_new_orders(self, created_after: Optional[datetime] = None) -> list[dict]:
        """
        Poll Amazon for recently created orders.
        Returns a list of raw Amazon order dicts (OrderList items).
        Handles pagination via NextToken.
        """
        marketplace_id = self.config.get("marketplace_id", "")
        version = self.config.get("api_version") or self.DEFAULT_ORDERS_VERSION

        if not created_after:
            created_after = datetime.now(timezone.utc) - timedelta(minutes=20)

        created_after_str = created_after.strftime("%Y-%m-%dT%H:%M:%SZ")

        orders = []
        next_token = None

        while True:
            params = {
                "MarketplaceIds": marketplace_id,
                "OrderStatuses": ",".join(AMAZON_INBOUND_STATUSES),
                "MaxResultsPerPage": 100,
            }
            if next_token:
                params = {"NextToken": next_token, "MarketplaceIds": marketplace_id}
            else:
                params["CreatedAfter"] = created_after_str

            data = await self._sp_get(f"/orders/{version}/orders", params=params)
            payload = data.get("payload", {})
            orders.extend(payload.get("Orders", []))

            next_token = payload.get("NextToken")
            if not next_token:
                break

        return orders

    async def fetch_order_items(self, amazon_order_id: str) -> list[dict]:
        """Fetch line items for a specific Amazon order."""
        version = self.config.get("api_version") or self.DEFAULT_ORDERS_VERSION
        data = await self._sp_get(f"/orders/{version}/orders/{amazon_order_id}/orderItems")
        return data.get("payload", {}).get("OrderItems", [])

    # ─── Inbound: Order Normalization ─────────────────────────────────────────

    def normalize_order(self, payload: dict) -> dict:
        """
        Transform an Amazon SP-API order dict (from Orders/v0/orders)
        into an OMS OrderCreate dict.

        Amazon order fields used:
          AmazonOrderId, PurchaseDate, OrderStatus,
          BuyerInfo.BuyerEmail, BuyerInfo.BuyerName,
          ShippingAddress (Name, AddressLine1-3, City, StateOrRegion, PostalCode, CountryCode)
          OrderTotalAmount (Amount, CurrencyCode)
          ShipmentServiceLevelCategory
          line_items injected as payload["_line_items"] by the polling task
        """
        amazon_order_id = payload.get("AmazonOrderId", "")
        buyer = payload.get("BuyerInfo", {})
        shipping_addr = payload.get("ShippingAddress", {})

        # ── Customer ──
        customer_email = (
            buyer.get("BuyerEmail")
            or f"amazon.{amazon_order_id}@noemail.placeholder"
        )
        customer_name = buyer.get("BuyerName") or shipping_addr.get("Name")
        customer_id = f"amazon:{amazon_order_id}"

        # ── Shipping Address ──
        shipping = None
        if shipping_addr:
            addr1 = shipping_addr.get("AddressLine1") or ""
            addr2 = shipping_addr.get("AddressLine2") or shipping_addr.get("AddressLine3")
            shipping = {
                "name": shipping_addr.get("Name"),
                "address1": addr1,
                "address2": addr2,
                "city": shipping_addr.get("City") or "",
                "state": shipping_addr.get("StateOrRegion") or "",
                "postal_code": shipping_addr.get("PostalCode") or "",
                "country": shipping_addr.get("CountryCode") or "US",
            }

        # ── Currency / Total ──
        order_total = payload.get("OrderTotal", {})
        currency = order_total.get("CurrencyCode") or "USD"

        # ── Line Items (injected by polling task) ──
        raw_items = payload.get("_line_items", [])
        oms_line_items = []
        for item in raw_items:
            sku = (
                item.get("SellerSKU")
                or item.get("ASIN")
                or f"AMAZON-{item.get('OrderItemId', '')}"
            )
            qty = int(item.get("QuantityOrdered", 1))
            unit_price = float(
                (item.get("ItemPrice") or {}).get("Amount", 0)
            ) / max(qty, 1)
            item_tax = float(
                (item.get("ItemTax") or {}).get("Amount", 0)
            ) / max(qty, 1)
            discount = float(
                (item.get("PromotionDiscount") or {}).get("Amount", 0)
            ) / max(qty, 1)

            oms_line_items.append({
                "sku": sku,
                "product_name": item.get("Title") or sku,
                "quantity": qty,
                "unit_price": round(unit_price, 4),
                "discount_amount": round(discount, 4),
                "tax_amount": round(item_tax, 4),
                "weight_lbs": 0.0,
                "metadata": {
                    "amazon_order_item_id": item.get("OrderItemId"),
                    "amazon_asin": item.get("ASIN"),
                    "amazon_seller_sku": item.get("SellerSKU"),
                },
            })

        # ── Fulfillment type ──
        service_level = payload.get("ShipmentServiceLevelCategory", "")
        fulfillment_type = "STORE_PICKUP" if "Pickup" in service_level else "SHIP_TO_HOME"

        return {
            "channel": "MARKETPLACE",
            "fulfillment_type": fulfillment_type,
            "customer_email": customer_email,
            "customer_name": customer_name,
            "customer_id": customer_id,
            "customer_phone": None,
            "line_items": oms_line_items,
            "shipping_address": shipping,
            "currency": currency,
            "shipping_amount": 0.0,
            "discount_amount": 0.0,
            "external_order_id": amazon_order_id,
            "tags": ["amazon"],
            "notes": None,
            "metadata": {
                "amazon_order_id": amazon_order_id,
                "amazon_order_status": payload.get("OrderStatus"),
                "amazon_marketplace_id": payload.get("MarketplaceId"),
                "amazon_sales_channel": payload.get("SalesChannel"),
                "amazon_fulfillment_channel": payload.get("FulfillmentChannel"),
                "amazon_purchase_date": payload.get("PurchaseDate"),
            },
        }

    # ─── Outbound: Push Fulfillment ───────────────────────────────────────────

    async def push_fulfillment(self, order, shipment) -> dict:
        """
        Confirm shipment for an Amazon order via Orders/v0 API.
        POST /orders/v0/orders/{orderId}/shipment
        """
        version = self.config.get("api_version") or self.DEFAULT_ORDERS_VERSION
        amazon_order_id = order.external_order_id

        if not amazon_order_id:
            raise ValueError(f"Amazon push_fulfillment: order {order.id} has no external_order_id")

        carrier_code = getattr(shipment, "carrier", None) or "Other"
        tracking_number = shipment.tracking_number

        body = {
            "marketplaceId": self.config.get("marketplace_id", ""),
            "fulfillmentDate": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fulfillmentInstruction": {
                "fulfillmentSupplySourceId": self.config.get("seller_id", ""),
            },
            "shippingSpeedCategory": "Standard",
            "shipmentItems": [
                {
                    "carrierCode": carrier_code,
                    "trackingNumber": tracking_number,
                }
            ],
        }

        return await self._sp_post(
            f"/orders/{version}/orders/{amazon_order_id}/shipment", body
        )

    # ─── Outbound: Push Order Cancel ──────────────────────────────────────────

    async def push_order_cancel(self, order) -> dict:
        """
        Amazon does not have a seller-initiated cancel API for orders.
        We acknowledge the cancellation in OMS but cannot push it to Amazon
        (buyer must request cancellation on Amazon's side).
        """
        logger.info(
            "push_order_cancel: Amazon order %s — seller-initiated cancel not supported via SP-API; "
            "buyer must cancel on Amazon. OMS record updated.",
            order.external_order_id,
        )
        return {"skipped": True, "reason": "Amazon SP-API does not support seller-initiated order cancel"}

    # ─── Outbound: Push Inventory ─────────────────────────────────────────────

    async def push_inventory_update(self, sku: str, quantity_available: int, mapping) -> dict:
        """
        Update FBM (merchant-fulfilled) inventory quantity on Amazon via
        Listings Items API (2021-08-01).
        Requires: seller_id, marketplace_id, and amazon_asin or platform_sku in the mapping.
        """
        seller_id = self.config.get("seller_id", "")
        marketplace_id = self.config.get("marketplace_id", "")
        platform_sku = mapping.platform_sku or sku

        if not all([seller_id, marketplace_id, platform_sku]):
            raise ValueError(
                f"Amazon push_inventory_update missing seller_id, marketplace_id, or platform_sku for SKU {sku}"
            )

        body = {
            "productType": "PRODUCT",
            "patches": [
                {
                    "op": "replace",
                    "path": "/attributes/fulfillment_availability",
                    "value": [
                        {
                            "fulfillment_channel_code": "DEFAULT",
                            "quantity": quantity_available,
                            "marketplace_id": marketplace_id,
                        }
                    ],
                }
            ],
        }

        return await self._sp_post(
            f"/listings/2021-08-01/items/{seller_id}/{platform_sku}?marketplaceIds={marketplace_id}",
            body,
        )

    # ─── Test Connection ──────────────────────────────────────────────────────

    async def test_connection(self) -> dict:
        """
        Test Amazon SP-API credentials by fetching marketplace participations.
        GET /sellers/v1/marketplaceParticipations
        """
        client_id = self.config.get("client_id", "")
        client_secret = self.config.get("client_secret", "")
        refresh_token = self.config.get("refresh_token", "")
        marketplace_id = self.config.get("marketplace_id", "")

        if not all([client_id, client_secret, refresh_token, marketplace_id]):
            return {
                "success": False,
                "message": "Missing client_id, client_secret, refresh_token, or marketplace_id",
                "details": None,
            }

        try:
            token = await self._get_access_token()

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self._base_url()}/sellers/v1/marketplaceParticipations",
                    headers={"x-amz-access-token": token},
                )

            if resp.status_code != 200:
                return {
                    "success": False,
                    "message": f"HTTP {resp.status_code}: {resp.text[:200]}",
                    "details": None,
                }

            participations = resp.json().get("payload", [])
            marketplace_names = [
                p.get("marketplace", {}).get("name")
                for p in participations
                if p.get("marketplace", {}).get("id") == marketplace_id
            ]
            name = marketplace_names[0] if marketplace_names else marketplace_id

            return {
                "success": True,
                "message": f"Connected to Amazon marketplace: {name}",
                "details": {
                    "marketplace_id": marketplace_id,
                    "marketplace_name": name,
                    "seller_id": self.config.get("seller_id"),
                    "region": self.config.get("region", self.DEFAULT_REGION),
                    "participations": len(participations),
                },
            }

        except Exception as exc:
            return {"success": False, "message": str(exc), "details": None}
