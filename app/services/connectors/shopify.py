"""Shopify connector: inbound order webhook + outbound fulfillment sync."""
import base64
import hashlib
import hmac
import logging

import httpx

from app.services.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

# Topics that trigger order creation in the OMS
SHOPIFY_ORDER_TOPICS = {"orders/create", "orders/paid"}

# Topics that trigger product/inventory catalog sync
SHOPIFY_PRODUCT_TOPICS = {"products/create", "products/update"}


class ShopifyConnector(BaseConnector):
    """
    Bidirectional Shopify integration.

    Inbound:  Shopify → OMS via orders/create or orders/paid webhook
    Outbound: OMS → Shopify fulfillment update when order status → SHIPPED

    Required config keys:
      shop_url        e.g. "my-store.myshopify.com"
      access_token    Shopify Admin API access token (shpat_...)
      webhook_secret  Used to validate HMAC on inbound webhooks
      api_version     Optional, defaults to "2024-01"
    """

    DEFAULT_API_VERSION = "2024-01"
    FULFILLMENT_API_VERSION = "2024-07"

    # ─── Access Token ─────────────────────────────────────────────────────────

    def _get_access_token(self) -> str:
        return self.config.get("access_token", "")

    # ─── Inbound: Webhook Validation ─────────────────────────────────────────

    def validate_webhook(self, headers: dict, raw_body: bytes) -> bool:
        """Validate Shopify HMAC-SHA256 webhook signature."""
        webhook_secret = self.config.get("webhook_secret", "")
        if not webhook_secret:
            logger.warning("Shopify connector %s has no webhook_secret configured", self.connector.id)
            return False

        hmac_header = headers.get("x-shopify-hmac-sha256", "")
        if not hmac_header:
            return False

        digest = base64.b64encode(
            hmac.new(webhook_secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
        ).decode("utf-8")

        return hmac.compare_digest(digest, hmac_header)

    def get_event_type(self, headers: dict) -> str:
        return headers.get("x-shopify-topic", "unknown")

    def get_inbound_topics(self) -> set[str]:
        return SHOPIFY_ORDER_TOPICS

    def get_product_topics(self) -> set[str]:
        return SHOPIFY_PRODUCT_TOPICS

    def normalize_product(self, payload: dict) -> list[dict]:
        """
        Transform a Shopify products/create or products/update payload into a list
        of variant dicts — one per SKU that should exist in OMS inventory.

        Shopify product payload structure:
          payload.title          — product title
          payload.product_type   — category/type
          payload.vendor         — vendor name
          payload.status         — "active" | "draft" | "archived"
          payload.variants[]     — one entry per size/color/etc.
            .id, .sku, .title, .price, .inventory_quantity, .weight, .weight_unit
        """
        product_title = payload.get("title") or ""
        product_id = payload.get("id")
        product_type = payload.get("product_type") or ""
        vendor = payload.get("vendor") or ""
        shopify_status = payload.get("status", "active")
        is_active = shopify_status == "active"

        variants = payload.get("variants") or []
        result = []

        for variant in variants:
            sku = variant.get("sku") or f"SHOPIFY-{variant['id']}"
            variant_title = (variant.get("title") or "").strip()

            # Build a human-readable product name
            if variant_title and variant_title.lower() not in ("default title", "default"):
                product_name = f"{product_title} — {variant_title}".strip(" —")
            else:
                product_name = product_title or sku

            # Shopify stores weight in grams by default; convert to lbs
            weight_raw = float(variant.get("weight") or 0)
            weight_unit = (variant.get("weight_unit") or "g").lower()
            if weight_unit == "g":
                weight_lbs = weight_raw * 0.00220462
            elif weight_unit == "kg":
                weight_lbs = weight_raw * 2.20462
            elif weight_unit == "oz":
                weight_lbs = weight_raw * 0.0625
            else:  # already lbs
                weight_lbs = weight_raw

            result.append({
                "sku": sku,
                "product_name": product_name,
                "quantity": max(int(variant.get("inventory_quantity") or 0), 0),
                "unit_cost": float(variant.get("price") or 0),
                "weight_lbs": round(weight_lbs, 4),
                "is_active": is_active,
                "shopify_product_id": product_id,
                "shopify_variant_id": variant.get("id"),
                # inventory_item_id is Shopify's internal ID used for inventory level API calls
                "shopify_inventory_item_id": str(variant.get("inventory_item_id") or ""),
                "shopify_product_type": product_type,
                "shopify_vendor": vendor,
            })

        return result

    # ─── Inbound: Order Normalization ─────────────────────────────────────────

    def normalize_order(self, payload: dict) -> dict:
        """
        Transform a Shopify order webhook payload into an OMS OrderCreate dict.
        """
        customer = payload.get("customer") or {}
        shipping_addr = payload.get("shipping_address") or payload.get("billing_address") or {}
        line_items = payload.get("line_items") or []
        shipping_lines = payload.get("shipping_lines") or []

        # ── Customer ──
        customer_email = (
            customer.get("email")
            or payload.get("email")
            or payload.get("contact_email")
            or f"shopify.{payload['id']}@noemail.placeholder"
        )
        first = customer.get("first_name") or ""
        last = customer.get("last_name") or ""
        customer_name = (first + " " + last).strip() or shipping_addr.get("name") or None
        customer_id = f"shopify:{customer['id']}" if customer.get("id") else None
        customer_phone = customer.get("phone") or shipping_addr.get("phone")

        # ── Line Items ──
        oms_line_items = []
        for item in line_items:
            # Prefer explicit SKU, then fall back to variant_id (consistent with
            # normalize_product which also keys on variant['id']), and only use
            # the line-item id as a last resort when neither is present.
            sku = (
                item.get("sku")
                or (f"SHOPIFY-{item['variant_id']}" if item.get("variant_id") else None)
                or f"SHOPIFY-{item['id']}"
            )
            # Per-unit discount allocation
            disc_allocations = item.get("discount_allocations") or []
            item_discount = sum(float(d.get("amount", 0)) for d in disc_allocations)
            # Per-unit tax (total tax / qty to get per-unit)
            tax_lines = item.get("tax_lines") or []
            item_tax_total = sum(float(t.get("price", 0)) for t in tax_lines)
            qty = max(int(item.get("quantity", 1)), 1)
            item_tax_per_unit = round(item_tax_total / qty, 4)

            oms_line_items.append({
                "sku": sku,
                "product_name": item.get("name") or item.get("title") or sku,
                "quantity": qty,
                "unit_price": float(item.get("price", 0)),
                "discount_amount": round(item_discount, 4),
                "tax_amount": item_tax_per_unit,
                "weight_lbs": float(item.get("grams", 0)) * 0.00220462,  # grams → lbs
                "metadata": {
                    "shopify_line_item_id": item.get("id"),
                    "shopify_product_id": item.get("product_id"),
                    "shopify_variant_id": item.get("variant_id"),
                },
            })

        # ── Shipping Address ──
        shipping = None
        if shipping_addr:
            shipping = {
                "name": shipping_addr.get("name"),
                "address1": shipping_addr.get("address1") or "",
                "address2": shipping_addr.get("address2"),
                "city": shipping_addr.get("city") or "",
                "state": shipping_addr.get("province_code") or shipping_addr.get("province") or "",
                "postal_code": shipping_addr.get("zip") or "",
                "country": shipping_addr.get("country_code") or "US",
            }

        # ── Financials ──
        shipping_amount = sum(float(s.get("price", 0)) for s in shipping_lines)
        discount_amount = float(payload.get("total_discounts") or 0)

        # ── Fulfillment type ──
        # Use STORE_PICKUP if Shopify order has requires_shipping=False
        fulfillment_type = (
            "STORE_PICKUP" if payload.get("requires_shipping") is False else "SHIP_TO_HOME"
        )

        # ── Tags ──
        raw_tags = payload.get("tags") or ""
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()]

        return {
            "channel": "MARKETPLACE",
            "fulfillment_type": fulfillment_type,
            "customer_email": customer_email,
            "customer_name": customer_name,
            "customer_id": customer_id,
            "customer_phone": customer_phone,
            "line_items": oms_line_items,
            "shipping_address": shipping,
            "currency": payload.get("currency") or "USD",
            "shipping_amount": shipping_amount,
            "discount_amount": discount_amount,
            "external_order_id": str(payload["id"]),
            "tags": tags,
            "notes": payload.get("note"),
            # Stamp brand from connector so inbound orders are automatically attributed
            "brand_id": str(self.connector.brand_id) if self.connector.brand_id else None,
            "metadata": {
                "shopify_order_id": payload.get("id"),
                "shopify_order_number": payload.get("order_number"),
                "shopify_name": payload.get("name"),
                "shopify_source": payload.get("source_name"),
                "shopify_financial_status": payload.get("financial_status"),
            },
        }

    # ─── Outbound: Push Fulfillment ───────────────────────────────────────────

    async def push_fulfillment(self, order, shipment) -> dict:
        """
        Create a fulfillment record in Shopify using the Fulfillment Orders API
        (api-version >= 2024-07). This replaces the deprecated Legacy Fulfillment API.

        Flow:
          Step 1 — GET /orders/{id}/fulfillment_orders.json  →  collect open FOs
          Step 2 — POST /fulfillments.json                   →  create fulfillment

        Requires: order.external_order_id (Shopify order ID),
                  shipment.tracking_number (and optionally carrier, tracking_url).
        """
        shop_url = self.config.get("shop_url", "").rstrip("/")
        access_token = self._get_access_token()
        api_version = self.config.get("api_version") or self.FULFILLMENT_API_VERSION
        shopify_order_id = order.external_order_id

        if not shop_url or not access_token or not shopify_order_id:
            raise ValueError(
                "Shopify connector missing shop_url, access_token, or order has no external_order_id"
            )

        headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            # ── Step 1: Fetch fulfillment orders for this Shopify order ──────────
            fo_url = (
                f"https://{shop_url}/admin/api/{api_version}"
                f"/orders/{shopify_order_id}/fulfillment_orders.json"
            )
            logger.info(
                "Shopify push_fulfillment [connector=%s order=%s]: fetching fulfillment orders from %s",
                self.connector.id,
                shopify_order_id,
                fo_url,
            )
            fo_resp = await client.get(fo_url, headers=headers)

            if fo_resp.status_code != 200:
                logger.error(
                    "Shopify push_fulfillment [connector=%s order=%s]: "
                    "GET fulfillment_orders returned HTTP %s — %s",
                    self.connector.id,
                    shopify_order_id,
                    fo_resp.status_code,
                    fo_resp.text[:500],
                )
                fo_resp.raise_for_status()

            fulfillment_orders = fo_resp.json().get("fulfillment_orders", [])
            logger.info(
                "Shopify push_fulfillment [connector=%s order=%s]: received %d fulfillment order(s)",
                self.connector.id,
                shopify_order_id,
                len(fulfillment_orders),
            )

            # ── Filter to open FOs only ──────────────────────────────────────────
            open_fos = [fo for fo in fulfillment_orders if fo.get("status") == "open"]

            if not open_fos:
                logger.warning(
                    "Shopify push_fulfillment [connector=%s order=%s]: "
                    "no open fulfillment orders found (statuses: %s) — skipping fulfillment push",
                    self.connector.id,
                    shopify_order_id,
                    [fo.get("status") for fo in fulfillment_orders],
                )
                return {
                    "skipped": True,
                    "reason": "no_open_fulfillment_orders",
                    "fulfillment_order_count": len(fulfillment_orders),
                }

            # ── Build line_items_by_fulfillment_order (full fulfillment) ─────────
            line_items_by_fo = []
            for fo in open_fos:
                fo_id = fo["id"]
                fo_line_items = [
                    {"id": li["id"], "quantity": li["quantity"]}
                    for li in (fo.get("line_items") or [])
                ]
                line_items_by_fo.append({
                    "fulfillment_order_id": fo_id,
                    "fulfillment_order_line_items": fo_line_items,
                })
                logger.debug(
                    "Shopify push_fulfillment [connector=%s order=%s]: "
                    "queuing FO id=%s with %d line item(s)",
                    self.connector.id,
                    shopify_order_id,
                    fo_id,
                    len(fo_line_items),
                )

            # ── Build tracking_info — omit keys that are None/empty ──────────────
            tracking_number = shipment.tracking_number
            carrier = getattr(shipment, "carrier", None)
            tracking_url = getattr(shipment, "tracking_url", None)

            tracking_info: dict = {"number": tracking_number}
            if carrier:
                tracking_info["company"] = carrier
            if tracking_url:
                tracking_info["url"] = tracking_url

            # ── Step 2: Create fulfillment ───────────────────────────────────────
            fulfillment_url = (
                f"https://{shop_url}/admin/api/{api_version}/fulfillments.json"
            )
            fulfillment_payload = {
                "fulfillment": {
                    "message": "Order has been shipped",
                    "notify_customer": True,
                    "tracking_info": tracking_info,
                    "line_items_by_fulfillment_order": line_items_by_fo,
                }
            }

            logger.info(
                "Shopify push_fulfillment [connector=%s order=%s]: "
                "creating fulfillment for %d open FO(s) — tracking=%s carrier=%s",
                self.connector.id,
                shopify_order_id,
                len(open_fos),
                tracking_number,
                carrier,
            )
            fulfillment_resp = await client.post(
                fulfillment_url,
                json=fulfillment_payload,
                headers=headers,
            )

            if fulfillment_resp.status_code not in (200, 201):
                logger.error(
                    "Shopify push_fulfillment [connector=%s order=%s]: "
                    "POST /fulfillments.json returned HTTP %s — %s",
                    self.connector.id,
                    shopify_order_id,
                    fulfillment_resp.status_code,
                    fulfillment_resp.text[:500],
                )
                fulfillment_resp.raise_for_status()

        result = fulfillment_resp.json()
        logger.info(
            "Shopify push_fulfillment [connector=%s order=%s]: fulfillment created successfully — id=%s",
            self.connector.id,
            shopify_order_id,
            result.get("fulfillment", {}).get("id"),
        )
        return result

    # ─── Outbound: Register Webhooks ──────────────────────────────────────────

    async def register_webhooks(self, app_host: str) -> list[dict]:
        """
        Register all required OMS webhooks with this Shopify store.

        Posts one webhook registration per topic. Uses a single httpx.AsyncClient
        for all requests. Never raises — per-topic failures are caught, logged, and
        included in the returned results list.

        Returns list of dicts:
          [{"topic": str, "success": bool, "webhook_id": int|None, "error": str|None}]
        """
        shop_url = self.config.get("shop_url", "").rstrip("/")
        access_token = self._get_access_token()
        api_version = self.config.get("api_version") or self.FULFILLMENT_API_VERSION
        app_host = app_host.rstrip("/")

        topics = [
            "orders/create",
            "orders/updated",
            "products/create",
            "products/update",
            "app/uninstalled",
        ]

        headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        }
        webhooks_url = f"https://{shop_url}/admin/api/{api_version}/webhooks.json"
        results: list[dict] = []

        async with httpx.AsyncClient(timeout=30) as client:
            for topic in topics:
                # The uninstall topic points to a dedicated endpoint
                if topic == "app/uninstalled":
                    address = f"{app_host}/shopify/webhooks/uninstall"
                else:
                    address = f"{app_host}/connectors/{self.connector.id}/webhook"

                try:
                    logger.info(
                        "Shopify register_webhooks [connector=%s]: registering topic=%s address=%s",
                        self.connector.id,
                        topic,
                        address,
                    )
                    resp = await client.post(
                        webhooks_url,
                        json={"webhook": {"topic": topic, "address": address, "format": "json"}},
                        headers=headers,
                    )
                    resp.raise_for_status()
                    webhook_id = resp.json().get("webhook", {}).get("id")
                    logger.info(
                        "Shopify register_webhooks [connector=%s]: registered topic=%s webhook_id=%s",
                        self.connector.id,
                        topic,
                        webhook_id,
                    )
                    results.append({"topic": topic, "success": True, "webhook_id": webhook_id, "error": None})

                except Exception as exc:
                    error_msg = str(exc)
                    logger.error(
                        "Shopify register_webhooks [connector=%s]: failed to register topic=%s — %s",
                        self.connector.id,
                        topic,
                        error_msg,
                    )
                    results.append({"topic": topic, "success": False, "webhook_id": None, "error": error_msg})

        return results

    # ─── Test Connection ──────────────────────────────────────────────────────

    async def push_inventory_update(self, sku: str, quantity_available: int, mapping) -> dict:
        """
        Set inventory level at Shopify for a specific variant.
        Uses POST /admin/api/{version}/inventory_levels/set.json
        Requires: shopify_inventory_item_id and shopify_location_id from the mapping.
        """
        shop_url = self.config.get("shop_url", "").rstrip("/")
        access_token = self._get_access_token()
        api_version = self.config.get("api_version") or self.DEFAULT_API_VERSION
        shopify_inv_item_id = mapping.shopify_inventory_item_id
        shopify_location_id = mapping.shopify_location_id

        if not all([shop_url, access_token, shopify_inv_item_id, shopify_location_id]):
            raise ValueError(
                f"Shopify push_inventory_update missing required IDs for SKU {sku} — "
                f"inventory_item_id={shopify_inv_item_id}, location_id={shopify_location_id}. "
                "Trigger 'Test Connection' to fetch the location ID, and ensure the product "
                "was imported via a products/create webhook."
            )

        url = f"https://{shop_url}/admin/api/{api_version}/inventory_levels/set.json"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                json={
                    "location_id": int(shopify_location_id),
                    "inventory_item_id": int(shopify_inv_item_id),
                    "available": quantity_available,
                },
                headers={
                    "X-Shopify-Access-Token": access_token,
                    "Content-Type": "application/json",
                },
            )
        resp.raise_for_status()
        return resp.json()

    async def push_order_cancel(self, order) -> dict:
        """Cancel an order in Shopify when it is cancelled in the OMS."""
        shop_url = self.config.get("shop_url", "").rstrip("/")
        access_token = self._get_access_token()
        api_version = self.config.get("api_version") or self.DEFAULT_API_VERSION
        shopify_order_id = order.external_order_id

        if not all([shop_url, access_token, shopify_order_id]):
            raise ValueError(
                "Shopify push_order_cancel: missing shop_url, access_token, or external_order_id"
            )

        url = f"https://{shop_url}/admin/api/{api_version}/orders/{shopify_order_id}/cancel.json"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                json={},
                headers={
                    "X-Shopify-Access-Token": access_token,
                    "Content-Type": "application/json",
                },
            )
        resp.raise_for_status()
        return resp.json()

    async def test_connection(self) -> dict:
        """
        Test Shopify API credentials by fetching shop info.
        Also fetches the store's primary location_id and stores it in
        connector.config['primary_location_id'] for inventory sync.
        """
        shop_url = self.config.get("shop_url", "").rstrip("/")
        access_token = self._get_access_token()
        api_version = self.config.get("api_version") or self.DEFAULT_API_VERSION

        if not shop_url or not access_token:
            return {"success": False, "message": "Missing shop_url or access_token", "details": None}

        try:
            headers = {"X-Shopify-Access-Token": access_token}
            async with httpx.AsyncClient(timeout=10) as client:
                shop_resp = await client.get(
                    f"https://{shop_url}/admin/api/{api_version}/shop.json",
                    headers=headers,
                )

            if shop_resp.status_code != 200:
                return {
                    "success": False,
                    "message": f"HTTP {shop_resp.status_code}: {shop_resp.text[:200]}",
                    "details": None,
                }

            shop = shop_resp.json().get("shop", {})
            primary_location_id = None

            # Fetch primary location for inventory level API
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    loc_resp = await client.get(
                        f"https://{shop_url}/admin/api/{api_version}/locations.json",
                        headers=headers,
                    )
                if loc_resp.status_code == 200:
                    locations = loc_resp.json().get("locations", [])
                    active = [loc for loc in locations if loc.get("active")]
                    if active:
                        primary_location_id = str(active[0]["id"])
                        # Persist into connector config (caller must commit)
                        cfg = dict(self.config)
                        cfg["primary_location_id"] = primary_location_id
                        self.connector.config = cfg
            except Exception:
                pass  # location fetch is best-effort

            return {
                "success": True,
                "message": f"Connected to {shop.get('name', shop_url)}",
                "details": {
                    "shop_name": shop.get("name"),
                    "shop_email": shop.get("email"),
                    "plan": shop.get("plan_name"),
                    "domain": shop.get("domain"),
                    "primary_location_id": primary_location_id,
                },
            }
        except Exception as exc:
            return {"success": False, "message": str(exc), "details": None}
