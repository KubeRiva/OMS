"""
Shopify Billing API — App Store subscription management.

Handles the full Shopify recurring billing flow:
  - GET  /shopify/billing/plans           — list available plans (public)
  - POST /shopify/billing/subscribe       — create AppSubscription, return confirmationUrl
  - GET  /shopify/billing/confirm         — callback after merchant approves/declines in Shopify admin
  - POST /shopify/webhooks/billing        — app_subscriptions/update webhook from Shopify

Pricing tiers:
  STARTER    $49/month   — up to 500 orders/month
  GROWTH     $149/month  — up to 5,000 orders/month
  ENTERPRISE $399/month  — unlimited

All prices are charged through Shopify's revenue share model (20% for first $1M ARR).
The merchant approves the charge inside the Shopify admin before it activates.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select

from app.config import settings
from app.database.mongodb import get_mongo_db
from app.database.postgres import async_session_factory
from app.models.postgres.connector_models import (
    Connector,
    ConnectorStatus,
    ConnectorType,
)
from app.routers.shopify_oauth import _validate_shopify_hmac
from app.services.connectors.shopify_crypto import decrypt_access_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shopify/billing", tags=["Shopify Billing"])
billing_webhook_router = APIRouter(prefix="/shopify/webhooks", tags=["Shopify Billing"])

# ---------------------------------------------------------------------------
# Billing plan definitions
# ---------------------------------------------------------------------------

BILLING_PLANS = {
    "STARTER": {
        "name": "OMS Starter",
        "price": "49.00",
        "currency_code": "USD",
        "interval": "EVERY_30_DAYS",
        "trial_days": 14,
        "features": ["Up to 500 orders/month", "Basic sourcing rules", "Standard fulfillment"],
        "order_limit": 500,
    },
    "GROWTH": {
        "name": "OMS Growth",
        "price": "149.00",
        "currency_code": "USD",
        "interval": "EVERY_30_DAYS",
        "trial_days": 14,
        "features": ["Up to 5,000 orders/month", "AI sourcing", "Pattern discovery", "A/B experiments"],
        "order_limit": 5000,
    },
    "ENTERPRISE": {
        "name": "OMS Enterprise",
        "price": "399.00",
        "currency_code": "USD",
        "interval": "EVERY_30_DAYS",
        "trial_days": 14,
        "features": ["Unlimited orders", "Multi-warehouse", "On-prem AI option", "Dedicated support"],
        "order_limit": None,  # unlimited
    },
}

_VALID_PLANS = frozenset(BILLING_PLANS.keys())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_connector_for_shop(shop_domain: str) -> Optional[Connector]:
    """Return the SHOPIFY Connector whose config["shop_url"] matches shop_domain, or None."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(Connector).where(Connector.connector_type == ConnectorType.SHOPIFY)
        )
        connectors = result.scalars().all()
        for connector in connectors:
            cfg: dict = connector.config or {}
            if cfg.get("shop_url") == shop_domain:
                return connector
    return None


def _get_plaintext_token(connector: Connector) -> str:
    """Return the decrypted Shopify access token stored in connector.config."""
    ciphertext = (connector.config or {}).get("access_token", "")
    return decrypt_access_token(ciphertext)


async def _create_app_subscription(
    shop_domain: str,
    access_token: str,
    plan_key: str,
    return_url: str,
) -> str:
    """
    Create a Shopify AppSubscription via the GraphQL Admin API.

    Returns the confirmationUrl the merchant must visit to approve the charge.
    Raises ValueError if Shopify returns userErrors.
    Raises httpx.RequestError on network failure.
    """
    plan = BILLING_PLANS[plan_key]
    api_url = f"https://{shop_domain}/admin/api/{settings.SHOPIFY_API_VERSION}/graphql.json"
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }

    mutation = """
mutation appSubscriptionCreate(
  $name: String!
  $returnUrl: URL!
  $lineItems: [AppSubscriptionLineItemInput!]!
  $trialDays: Int
) {
  appSubscriptionCreate(
    name: $name
    returnUrl: $returnUrl
    lineItems: $lineItems
    trialDays: $trialDays
  ) {
    appSubscription {
      id
      status
    }
    confirmationUrl
    userErrors {
      field
      message
    }
  }
}
"""
    variables = {
        "name": plan["name"],
        "returnUrl": return_url,
        "trialDays": plan["trial_days"],
        "lineItems": [
            {
                "plan": {
                    "appRecurringPricingDetails": {
                        "price": {
                            "amount": plan["price"],
                            "currencyCode": plan["currency_code"],
                        },
                        "interval": plan["interval"],
                    }
                }
            }
        ],
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            api_url,
            json={"query": mutation, "variables": variables},
            headers=headers,
        )

    response.raise_for_status()
    data = response.json()

    result = data.get("data", {}).get("appSubscriptionCreate", {})
    user_errors = result.get("userErrors", [])
    if user_errors:
        messages = "; ".join(f"{e.get('field', '')}: {e.get('message', '')}" for e in user_errors)
        logger.error(
            "Shopify appSubscriptionCreate userErrors for shop=%s plan=%s: %s",
            shop_domain,
            plan_key,
            messages,
        )
        raise ValueError(f"Shopify billing error: {messages}")

    confirmation_url = result.get("confirmationUrl")
    if not confirmation_url:
        raise ValueError("Shopify did not return a confirmationUrl")

    logger.info(
        "Created Shopify AppSubscription for shop=%s plan=%s",
        shop_domain,
        plan_key,
    )
    return confirmation_url


async def _get_subscription_status(
    shop_domain: str,
    access_token: str,
    charge_id: str,
) -> str:
    """
    Query Shopify for the current status of an AppSubscription node.

    charge_id is the raw numeric ID from the redirect query param; we build
    the full GID internally.
    Returns the status string (e.g. ACTIVE, PENDING, DECLINED, CANCELLED).
    Raises ValueError on unexpected response shape.
    """
    # Shopify appends the numeric charge ID in the redirect; build the GID.
    if charge_id.startswith("gid://"):
        gid = charge_id
    else:
        gid = f"gid://shopify/AppSubscription/{charge_id}"

    api_url = f"https://{shop_domain}/admin/api/{settings.SHOPIFY_API_VERSION}/graphql.json"
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }

    query = """
query getSubscription($id: ID!) {
  node(id: $id) {
    ... on AppSubscription {
      id
      status
    }
  }
}
"""
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            api_url,
            json={"query": query, "variables": {"id": gid}},
            headers=headers,
        )

    response.raise_for_status()
    data = response.json()

    node = data.get("data", {}).get("node")
    if not node:
        raise ValueError(f"Shopify returned no node for subscription id={charge_id}")

    status = node.get("status")
    if not status:
        raise ValueError(f"Shopify returned node with no status for id={charge_id}")

    return status


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/plans")
async def list_billing_plans() -> JSONResponse:
    """
    Return all available billing plans as an ordered array.

    Public endpoint — no authentication required.
    """
    plans = [
        {
            "name": plan_key,
            "display_name": plan["name"],
            "price": float(plan["price"]),
            "currency": plan["currency_code"],
            "interval": plan["interval"],
            "trial_days": plan["trial_days"],
            "features": plan["features"],
        }
        for plan_key, plan in BILLING_PLANS.items()
    ]
    return JSONResponse(content=plans)


@router.post("/subscribe")
async def subscribe(request: Request) -> JSONResponse:
    """
    Initiate a Shopify AppSubscription for the given shop and plan.

    Requires OMS session (JWT / cookie). Called by the OMS frontend when a
    merchant selects a plan. Returns a confirmationUrl the frontend must open
    (or redirect to) so the merchant can approve the charge inside Shopify admin.
    """
    try:
        body: dict = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"detail": "Invalid JSON body"})

    shop: str = body.get("shop", "").strip()
    plan: str = body.get("plan", "").strip().upper()

    if not shop:
        return JSONResponse(status_code=400, content={"detail": "Missing required field: shop"})

    if plan not in _VALID_PLANS:
        return JSONResponse(
            status_code=400,
            content={
                "detail": f"Invalid plan '{plan}'. Must be one of: {', '.join(sorted(_VALID_PLANS))}"
            },
        )

    connector = await _get_connector_for_shop(shop)
    if connector is None:
        logger.warning("Billing subscribe: no connector found for shop=%s", shop)
        return JSONResponse(
            status_code=404,
            content={"detail": f"No Shopify connector found for shop '{shop}'"},
        )

    access_token = _get_plaintext_token(connector)
    return_url = (
        f"{settings.SHOPIFY_APP_HOST}/shopify/billing/confirm"
        f"?shop={shop}&plan={plan}"
    )

    try:
        confirmation_url = await _create_app_subscription(
            shop_domain=shop,
            access_token=access_token,
            plan_key=plan,
            return_url=return_url,
        )
    except ValueError as exc:
        logger.error("Shopify subscription creation failed for shop=%s: %s", shop, exc)
        return JSONResponse(status_code=502, content={"detail": str(exc)})
    except httpx.RequestError as exc:
        logger.error("Network error creating Shopify subscription for shop=%s: %s", shop, exc)
        return JSONResponse(
            status_code=502,
            content={"detail": "Network error while contacting Shopify. Please try again."},
        )

    # Persist pending plan on the connector so the confirm callback can verify.
    async with async_session_factory() as session:
        db_connector = await session.get(Connector, connector.id)
        if db_connector is not None:
            cfg: dict = dict(db_connector.config or {})
            cfg["pending_plan"] = plan
            db_connector.config = cfg
            await session.commit()
            logger.info(
                "Stored pending_plan=%s on connector=%s for shop=%s",
                plan,
                connector.id,
                shop,
            )

    return JSONResponse(content={"confirmation_url": confirmation_url})


@router.get("/confirm")
async def confirm_subscription(
    request: Request,
    shop: str = "",
    plan: str = "",
    charge_id: str = "",
) -> RedirectResponse:
    """
    Handle the redirect back from Shopify after the merchant approves/declines.

    Shopify appends charge_id to the returnUrl we provided. We verify the
    subscription status via GraphQL, update the connector config, and redirect
    the merchant to the OMS dashboard.
    """
    # Accept query-param values regardless of casing.
    plan = plan.upper()

    if not shop:
        return JSONResponse(status_code=400, content={"detail": "Missing required query param: shop"})
    if not charge_id:
        return JSONResponse(status_code=400, content={"detail": "Missing required query param: charge_id"})

    connector = await _get_connector_for_shop(shop)
    if connector is None:
        logger.warning("Billing confirm: no connector found for shop=%s", shop)
        return JSONResponse(
            status_code=404,
            content={"detail": f"No Shopify connector found for shop '{shop}'"},
        )

    access_token = _get_plaintext_token(connector)

    # Verify subscription status with Shopify.
    try:
        sub_status = await _get_subscription_status(
            shop_domain=shop,
            access_token=access_token,
            charge_id=charge_id,
        )
    except (ValueError, httpx.RequestError) as exc:
        logger.error(
            "Failed to verify subscription status for shop=%s charge_id=%s: %s",
            shop,
            charge_id,
            exc,
        )
        return JSONResponse(
            status_code=502,
            content={"detail": "Failed to verify subscription status with Shopify."},
        )

    logger.info(
        "Shopify billing confirm: shop=%s plan=%s charge_id=%s status=%s",
        shop,
        plan,
        charge_id,
        sub_status,
    )

    if sub_status in ("DECLINED", "CANCELLED"):
        return JSONResponse(
            status_code=402,
            content={
                "detail": f"Subscription was {sub_status.lower()} by the merchant or Shopify.",
                "status": sub_status,
            },
        )

    # ACTIVE or PENDING — activate the plan on the connector.
    async with async_session_factory() as session:
        db_connector = await session.get(Connector, connector.id)
        if db_connector is not None:
            cfg: dict = dict(db_connector.config or {})
            cfg["plan"] = plan
            cfg["subscription_id"] = charge_id
            cfg["billing_status"] = sub_status
            cfg.pop("pending_plan", None)
            db_connector.config = cfg
            await session.commit()
            logger.info(
                "Activated plan=%s subscription_id=%s on connector=%s for shop=%s",
                plan,
                charge_id,
                connector.id,
                shop,
            )

    dashboard_url = settings.SHOPIFY_APP_HOST or "/"
    return RedirectResponse(url=dashboard_url)


# ---------------------------------------------------------------------------
# Billing webhook (app_subscriptions/update) — separate router, exempt from JWT
# ---------------------------------------------------------------------------


@billing_webhook_router.post("/billing")
async def shopify_billing_webhook(request: Request) -> JSONResponse:
    """
    Handle app_subscriptions/update webhooks from Shopify.

    Validates HMAC, updates connector billing status, and logs to MongoDB.
    Always returns HTTP 200 — same pattern as GDPR endpoints — to prevent
    Shopify from retrying on transient processing errors.
    """
    raw_body = await request.body()
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")

    if not _validate_shopify_hmac(raw_body, hmac_header):
        logger.warning(
            "Shopify billing webhook HMAC validation failed — returning 200 to suppress retries"
        )
        return JSONResponse(status_code=200, content={"status": "ok"})

    try:
        body: dict = json.loads(raw_body)
    except Exception:
        body = {}

    # Shopify billing webhook payload shape:
    # { "app_subscription": { "admin_graphql_api_id": "gid://shopify/AppSubscription/...", "status": "...", "name": "..." } }
    subscription_data: dict = body.get("app_subscription", body)
    raw_subscription_id: str = (
        subscription_data.get("admin_graphql_api_id", "")
        or subscription_data.get("id", "")
    )
    status: str = subscription_data.get("status", "")
    name: str = subscription_data.get("name", "")
    shop_domain: str = request.headers.get("X-Shopify-Shop-Domain", "")

    # Normalise the subscription ID to the numeric portion for config storage
    # (consistent with what we stored during the confirm callback).
    subscription_id = raw_subscription_id
    if raw_subscription_id.startswith("gid://shopify/AppSubscription/"):
        subscription_id = raw_subscription_id.split("/")[-1]

    logger.info(
        "Shopify billing webhook received: shop=%s subscription_id=%s status=%s name=%s",
        shop_domain,
        subscription_id,
        status,
        name,
    )

    # Find the connector whose stored subscription_id matches.
    if subscription_id:
        try:
            async with async_session_factory() as session:
                result = await session.execute(
                    select(Connector).where(
                        Connector.connector_type == ConnectorType.SHOPIFY
                    )
                )
                connectors = result.scalars().all()
                for connector in connectors:
                    cfg: dict = connector.config or {}
                    stored_id = str(cfg.get("subscription_id", ""))
                    if stored_id == subscription_id:
                        cfg = dict(cfg)
                        cfg["billing_status"] = status
                        connector.config = cfg
                        if status in ("CANCELLED", "FROZEN"):
                            connector.status = ConnectorStatus.INACTIVE
                            logger.warning(
                                "Shopify billing: connector=%s marked INACTIVE due to subscription status=%s (shop=%s)",
                                connector.id,
                                status,
                                shop_domain,
                            )
                        await session.commit()
                        logger.info(
                            "Updated billing_status=%s on connector=%s for shop=%s",
                            status,
                            connector.id,
                            shop_domain,
                        )
                        break
        except Exception as exc:
            logger.error(
                "Failed to update connector for billing webhook (subscription_id=%s): %s",
                subscription_id,
                exc,
            )

    # Log to MongoDB regardless of processing outcome.
    try:
        db = await get_mongo_db()
        await db["shopify_billing_events"].insert_one(
            {
                "subscription_id": subscription_id,
                "raw_subscription_id": raw_subscription_id,
                "status": status,
                "name": name,
                "shop_domain": shop_domain,
                "payload": body,
                "received_at": datetime.now(timezone.utc),
            }
        )
    except Exception as exc:
        logger.error("Failed to log Shopify billing event to MongoDB: %s", exc)

    return JSONResponse(status_code=200, content={"status": "ok"})
