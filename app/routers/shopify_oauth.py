"""
Shopify App Store OAuth, GDPR mandatory endpoints, and webhook handlers.

This router handles the full Shopify App Store install flow:
  - OAuth install initiation  (GET /shopify/install)
  - OAuth callback            (GET /shopify/callback)
  - App uninstall webhook     (POST /shopify/webhooks/uninstall)
  - GDPR customer data export (POST /shopify/gdpr/customers/data_request)
  - GDPR customer redact      (POST /shopify/gdpr/customers/redact)
  - GDPR shop redact          (POST /shopify/gdpr/shop/redact)

All GDPR and webhook endpoints are exempt from JWT auth (they originate from
Shopify servers). Their authenticity is verified via HMAC-SHA256 using
SHOPIFY_API_SECRET.
"""
import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.config import settings
from app.database.mongodb import get_mongo_db
from app.database.postgres import async_session_factory, control_session_factory
from app.database.redis_client import get_redis_client
from app.models.postgres.connector_models import (
    Connector,
    ConnectorDirection,
    ConnectorStatus,
    ConnectorType,
)
from app.models.postgres.org_models import (
    Environment,
    EnvironmentStatus,
    EnvironmentType,
    Organization,
)

from jose import jwt as jose_jwt, JWTError as JoseJWTError

from app.core.security import create_access_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shopify", tags=["Shopify App"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SHOP_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\-]*\.myshopify\.com$")
_OAUTH_STATE_TTL = 600  # 10 minutes
_TIMESTAMP_TOLERANCE = 300  # 5 minutes
_WEBHOOK_TOPICS = [
    "orders/create",
    "orders/updated",
    "products/create",
    "products/update",
    "fulfillments/create",
]


# ---------------------------------------------------------------------------
# HMAC helpers
# ---------------------------------------------------------------------------


def _validate_shopify_hmac(raw_body: bytes, hmac_header: str) -> bool:
    """Validate HMAC-SHA256 for Shopify webhook/GDPR callbacks.

    Shopify sends: base64-encoded HMAC-SHA256(secret, raw_body) in the
    X-Shopify-Hmac-Sha256 header.
    """
    if not settings.SHOPIFY_API_SECRET or not hmac_header:
        return False
    expected = base64.b64encode(
        hmac.new(
            settings.SHOPIFY_API_SECRET.encode(),
            raw_body,
            hashlib.sha256,
        ).digest()
    ).decode()
    return hmac.compare_digest(expected, hmac_header)


def _validate_oauth_callback_hmac(params: dict[str, str]) -> bool:
    """Validate HMAC for OAuth callback query parameters.

    Shopify signs the callback by building a sorted key=value message from all
    query params *except* hmac, then HMAC-SHA256 with SHOPIFY_API_SECRET.
    """
    provided_hmac = params.get("hmac", "")
    if not settings.SHOPIFY_API_SECRET or not provided_hmac:
        return False

    filtered = sorted(
        (k, v) for k, v in params.items() if k != "hmac"
    )
    message = "&".join(f"{k}={v}" for k, v in filtered)
    expected = hmac.new(
        settings.SHOPIFY_API_SECRET.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, provided_hmac)


# ---------------------------------------------------------------------------
# Access-token encryption helpers  (moved to shared module)
# ---------------------------------------------------------------------------
# The encrypt/decrypt implementations live in app/services/connectors/shopify_crypto
# so that ShopifyConnector can decrypt tokens without importing from a router.
# ---------------------------------------------------------------------------
from app.services.connectors.shopify_crypto import (
    encrypt_access_token as _encrypt_access_token,
    decrypt_access_token as _decrypt_access_token,  # noqa: F401 — kept for any future direct use
)

# ---------------------------------------------------------------------------
# Provisioning helpers
# ---------------------------------------------------------------------------


async def _provision_shopify_merchant(
    shop_domain: str,
    access_token: str,
) -> Connector:
    """
    Auto-provision an Organization + Environment + Connector for a Shopify merchant.

    If a Connector already exists for this shop_domain, its access_token is
    updated and the existing record is returned (idempotent re-installs).
    """
    # --- Check for an existing connector (data-plane) -----------------------
    async with async_session_factory() as session:
        result = await session.execute(
            select(Connector).where(
                Connector.connector_type == ConnectorType.SHOPIFY
            )
        )
        existing_connectors = result.scalars().all()
        for connector in existing_connectors:
            cfg: dict = connector.config or {}
            if cfg.get("shop_url") == shop_domain:
                # Re-install: update access token only.
                cfg["access_token"] = _encrypt_access_token(access_token)
                connector.config = cfg
                connector.status = ConnectorStatus.ACTIVE
                await session.commit()
                await session.refresh(connector)
                logger.info(
                    "Shopify re-install: updated access token for connector %s (shop=%s)",
                    connector.id,
                    shop_domain,
                )
                return connector

    # --- New install: provision org + env in the control-plane DB -----------
    # Organization and Environment rows live in oms_db (control plane).
    # control_session_factory always targets the shared oms_db, regardless of
    # whether this code runs on the main pod or a tenant pod.
    org_slug = re.sub(r"[.\-]", "_", shop_domain)
    org_slug = org_slug[:80]

    async with control_session_factory() as ctrl_session:
        org = Organization(
            name=shop_domain,
            slug=org_slug,
            description=f"Auto-provisioned via Shopify App Store install for {shop_domain}",
        )
        ctrl_session.add(org)
        await ctrl_session.flush()  # populate org.id

        env_db_name = f"oms_{org_slug}_prod"
        env = Environment(
            organization_id=org.id,
            name="Production",
            slug="prod",
            env_type=EnvironmentType.PROD,
            status=EnvironmentStatus.ACTIVE,
            db_name=env_db_name,
            mongo_events_db=f"oms_events_{org_slug}_prod",
            mongo_ai_db=f"oms_ai_{org_slug}_prod",
            es_index_prefix=f"{org_slug}_prod",
            is_default=False,
            provisioned_at=datetime.now(timezone.utc),
        )
        ctrl_session.add(env)
        await ctrl_session.flush()  # populate env.id
        org_id = org.id
        env_id = env.id
        await ctrl_session.commit()

    # --- Create the Connector in the data-plane DB --------------------------
    async with async_session_factory() as session:
        webhook_secret = secrets.token_urlsafe(32)
        connector = Connector(
            name=f"Shopify \u2014 {shop_domain}",
            connector_type=ConnectorType.SHOPIFY,
            direction=ConnectorDirection.BIDIRECTIONAL,
            status=ConnectorStatus.ACTIVE,
            config={
                "shop_url": shop_domain,
                "access_token": _encrypt_access_token(access_token),
                "api_version": settings.SHOPIFY_API_VERSION,
                "webhook_secret": webhook_secret,
            },
        )
        session.add(connector)
        await session.commit()
        await session.refresh(connector)

        logger.info(
            "Shopify install: provisioned org=%s env=%s connector=%s for shop=%s",
            org_id,
            env_id,
            connector.id,
            shop_domain,
        )
        return connector


async def _register_shopify_webhooks(
    shop_domain: str,
    access_token: str,
    connector_id: Any,  # UUID
) -> None:
    """
    Register Shopify webhooks via the REST Admin API.

    Webhook registration is best-effort: failures are logged but do NOT abort
    the install flow. Merchants can trigger re-registration manually.
    """
    base_url = f"https://{shop_domain}/admin/api/{settings.SHOPIFY_API_VERSION}/webhooks.json"
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }
    oms_webhook_url = f"{settings.SHOPIFY_APP_HOST}/connectors/{connector_id}/webhook"
    uninstall_url = f"{settings.SHOPIFY_APP_HOST}/shopify/webhooks/uninstall"

    topics: list[tuple[str, str]] = [
        (topic, oms_webhook_url) for topic in _WEBHOOK_TOPICS
    ]
    topics.append(("app/uninstalled", uninstall_url))

    async with httpx.AsyncClient(timeout=15.0) as client:
        for topic, address in topics:
            payload = {
                "webhook": {
                    "topic": topic,
                    "address": address,
                    "format": "json",
                }
            }
            try:
                resp = await client.post(base_url, json=payload, headers=headers)
                if resp.status_code in (200, 201):
                    logger.info(
                        "Registered Shopify webhook: topic=%s connector=%s",
                        topic,
                        connector_id,
                    )
                else:
                    logger.warning(
                        "Failed to register Shopify webhook: topic=%s status=%d body=%s",
                        topic,
                        resp.status_code,
                        resp.text[:200],
                    )
            except Exception as exc:
                logger.warning(
                    "Exception registering Shopify webhook: topic=%s error=%s",
                    topic,
                    exc,
                )


# ---------------------------------------------------------------------------
# OAuth install flow
# ---------------------------------------------------------------------------


@router.get("/install")
async def shopify_install(shop: str) -> RedirectResponse:
    """
    Initiate the Shopify OAuth install flow.

    Validates the shop hostname, generates a one-time state nonce stored in
    Redis (TTL 10 min), and redirects the merchant to Shopify's OAuth screen.
    """
    if not _SHOP_HOSTNAME_RE.match(shop):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid shop hostname. Must match *.myshopify.com"},
        )

    if not settings.SHOPIFY_API_KEY:
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "Shopify App Store integration is not configured. "
                    "Set SHOPIFY_API_KEY and SHOPIFY_API_SECRET to enable it."
                )
            },
        )

    state = secrets.token_urlsafe(32)

    redis = get_redis_client()
    if redis:
        try:
            await redis.set(f"shopify_oauth_state:{state}", shop, ex=_OAUTH_STATE_TTL)
        except Exception as exc:
            logger.error("Redis unavailable during OAuth install for shop %s: %s", shop, exc)
            return JSONResponse(
                status_code=503,
                content={"detail": "Service temporarily unavailable. Please try again."}
            )
        finally:
            await redis.aclose()
    else:
        logger.error("Redis unavailable — cannot store OAuth state nonce")
        return JSONResponse(
            status_code=503,
            content={"detail": "Redis unavailable. Cannot initiate OAuth flow."},
        )

    redirect_uri = f"{settings.SHOPIFY_APP_HOST}/shopify/callback"
    params = urlencode(
        {
            "client_id": settings.SHOPIFY_API_KEY,
            "scope": settings.SHOPIFY_SCOPES,
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    oauth_url = f"https://{shop}/admin/oauth/authorize?{params}"
    logger.info("Initiating Shopify OAuth for shop=%s state=%s", shop, state[:8] + "...")
    return RedirectResponse(url=oauth_url)


@router.get("/callback")
async def shopify_callback(request: Request) -> RedirectResponse:
    """
    Complete the Shopify OAuth flow after the merchant approves the app.

    Validates state nonce, HMAC, and timestamp; exchanges the code for an
    access token; provisions the merchant; registers webhooks; then redirects
    the merchant to the OMS dashboard.
    """
    params: dict[str, str] = dict(request.query_params)
    code = params.get("code", "")
    shop = params.get("shop", "")
    state = params.get("state", "")
    timestamp_str = params.get("timestamp", "")

    # --- Validate shop hostname ---
    if not _SHOP_HOSTNAME_RE.match(shop):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid shop hostname in callback."},
        )

    # --- Validate state nonce (one-time use) ---
    redis = get_redis_client()
    if redis is None:
        logger.error("Redis unavailable during OAuth callback for shop=%s", shop)
        return JSONResponse(
            status_code=503,
            content={"detail": "Redis unavailable. Cannot complete OAuth flow."},
        )
    try:
        redis_key = f"shopify_oauth_state:{state}"
        # HIGH fix: use atomic GETDEL (Redis 6.2+) to consume the nonce in a
        # single round-trip. A non-atomic GET + DELETE has a race window where
        # two concurrent callbacks carrying the same state value could both pass
        # the "nonce exists" check before either deletes it, defeating CSRF
        # protection. GETDEL eliminates that window entirely.
        stored_shop = await redis.getdel(redis_key)
        if not stored_shop:
            logger.warning("Invalid or expired OAuth state nonce for shop=%s", shop)
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid or expired state parameter. Please restart the install flow."},
            )
    finally:
        await redis.aclose()

    if stored_shop != shop:
        logger.warning(
            "OAuth state shop mismatch: nonce shop=%s callback shop=%s",
            stored_shop,
            shop,
        )
        return JSONResponse(
            status_code=400,
            content={"detail": "State/shop mismatch in OAuth callback."},
        )

    # --- Validate HMAC ---
    if not _validate_oauth_callback_hmac(params):
        logger.warning("Shopify OAuth callback HMAC validation failed for shop=%s", shop)
        return JSONResponse(
            status_code=400,
            content={"detail": "HMAC validation failed. Request may have been tampered with."},
        )

    # --- Validate timestamp (within 5 minutes) ---
    try:
        callback_ts = int(timestamp_str)
        now_ts = int(datetime.now(timezone.utc).timestamp())
        if abs(now_ts - callback_ts) > _TIMESTAMP_TOLERANCE:
            logger.warning("Shopify OAuth callback timestamp too old for shop=%s", shop)
            return JSONResponse(
                status_code=400,
                content={"detail": "OAuth callback timestamp is outside the allowed window."},
            )
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid or missing timestamp in OAuth callback."},
        )

    # --- Exchange code for access token ---
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_resp = await client.post(
                f"https://{shop}/admin/oauth/access_token",
                json={
                    "client_id": settings.SHOPIFY_API_KEY,
                    "client_secret": settings.SHOPIFY_API_SECRET,
                    "code": code,
                },
            )
        if token_resp.status_code != 200:
            logger.error(
                "Shopify code exchange failed: shop=%s status=%d body=%s",
                shop,
                token_resp.status_code,
                token_resp.text[:200],
            )
            return JSONResponse(
                status_code=502,
                content={"detail": "Failed to exchange authorization code with Shopify."},
            )
        token_data = token_resp.json()
        access_token = token_data.get("access_token", "")
        if not access_token:
            logger.error("Shopify returned empty access_token for shop=%s", shop)
            return JSONResponse(
                status_code=502,
                content={"detail": "Shopify returned an empty access token."},
            )
    except httpx.RequestError as exc:
        logger.error("Network error during Shopify code exchange for shop=%s: %s", shop, exc)
        return JSONResponse(
            status_code=502,
            content={"detail": "Network error while contacting Shopify for token exchange."},
        )

    # --- Provision merchant (org + env + connector) ---
    connector = await _provision_shopify_merchant(shop, access_token)

    # --- Register webhooks (best-effort) ---
    await _register_shopify_webhooks(shop, access_token, connector.id)

    # --- Redirect merchant to OMS dashboard ---
    dashboard_url = settings.SHOPIFY_APP_HOST or "/"
    logger.info("Shopify install complete for shop=%s connector=%s", shop, connector.id)
    return RedirectResponse(url=dashboard_url)


# ---------------------------------------------------------------------------
# Uninstall webhook
# ---------------------------------------------------------------------------


@router.post("/webhooks/uninstall")
async def shopify_uninstall_webhook(request: Request) -> JSONResponse:
    """
    Handle the app/uninstalled Shopify webhook.

    Marks the matching Connector as INACTIVE and logs the event to MongoDB.
    """
    raw_body = await request.body()
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")

    if not _validate_shopify_hmac(raw_body, hmac_header):
        logger.warning("Shopify uninstall webhook HMAC validation failed — returning 200 to suppress Shopify retries")
        return JSONResponse(status_code=200, content={"status": "ok"})

    try:
        body: dict = json.loads(raw_body)
    except Exception:
        body = {}

    shop_domain: str = body.get("domain", "") or request.headers.get("X-Shopify-Shop-Domain", "")

    # Mark the connector INACTIVE.
    if shop_domain:
        async with async_session_factory() as session:
            result = await session.execute(
                select(Connector).where(
                    Connector.connector_type == ConnectorType.SHOPIFY
                )
            )
            connectors = result.scalars().all()
            for connector in connectors:
                cfg: dict = connector.config or {}
                if cfg.get("shop_url") == shop_domain:
                    connector.status = ConnectorStatus.INACTIVE
                    await session.commit()
                    logger.info(
                        "Shopify uninstall: connector=%s marked INACTIVE for shop=%s",
                        connector.id,
                        shop_domain,
                    )
                    break

    # Log to MongoDB.
    try:
        db = await get_mongo_db()
        await db["shopify_gdpr_requests"].insert_one(
            {
                "request_type": "app_uninstalled",
                "shop_domain": shop_domain,
                "payload": body,
                "received_at": datetime.now(timezone.utc),
            }
        )
    except Exception as exc:
        logger.error("Failed to log Shopify uninstall to MongoDB: %s", exc)

    return JSONResponse(status_code=200, content={"status": "ok"})


# ---------------------------------------------------------------------------
# GDPR mandatory endpoints
# ---------------------------------------------------------------------------


@router.post("/gdpr/customers/data_request")
async def shopify_gdpr_customer_data_request(request: Request) -> JSONResponse:
    """
    GDPR customer data request (mandatory Shopify App Store endpoint).

    Acknowledges the request immediately. The OMS is required to deliver the
    customer data export within 30 days via the merchant's admin dashboard.
    """
    raw_body = await request.body()
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")

    if not _validate_shopify_hmac(raw_body, hmac_header):
        logger.warning("Shopify GDPR data_request HMAC validation failed")
        # Per GDPR endpoint contract, return 200 even on validation failure
        # to avoid Shopify retry storms. Log the anomaly for investigation.
        return JSONResponse(status_code=200, content={"status": "ok"})

    try:
        body: dict = json.loads(raw_body)
    except Exception:
        body = {}

    try:
        db = await get_mongo_db()
        await db["shopify_gdpr_requests"].insert_one(
            {
                "request_type": "customer_data_request",
                "shop_id": body.get("shop_id"),
                "shop_domain": body.get("shop_domain"),
                "customer": body.get("customer"),
                "orders_requested": body.get("orders_requested", []),
                "payload": body,
                "received_at": datetime.now(timezone.utc),
            }
        )
    except Exception as exc:
        logger.error("Failed to log Shopify GDPR customer data_request to MongoDB: %s", exc)

    logger.info(
        "Shopify GDPR customer data_request received for shop=%s customer=%s",
        body.get("shop_domain"),
        body.get("customer", {}).get("email") if isinstance(body.get("customer"), dict) else None,
    )
    return JSONResponse(status_code=200, content={"status": "ok"})


@router.post("/gdpr/customers/redact")
async def shopify_gdpr_customer_redact(request: Request) -> JSONResponse:
    """
    GDPR customer redact (mandatory Shopify App Store endpoint).

    Anonymizes customer PII in the OMS orders table for the listed order IDs.
    """
    raw_body = await request.body()
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")

    if not _validate_shopify_hmac(raw_body, hmac_header):
        logger.warning("Shopify GDPR customer_redact HMAC validation failed")
        return JSONResponse(status_code=200, content={"status": "ok"})

    try:
        body: dict = json.loads(raw_body)
    except Exception:
        body = {}

    shop_domain = body.get("shop_domain", "")
    orders_to_redact: list = body.get("orders_to_redact", [])

    # Anonymize orders in PostgreSQL.
    if orders_to_redact:
        try:
            from app.models.postgres.order_models import Order
            from app.database.env_registry import registry as _env_registry
            from sqlalchemy.ext.asyncio import AsyncSession

            # --- Resolve the tenant-specific DB session ---
            # Connectors live in the control DB (async_session_factory). Look up
            # the Connector matching this shop_domain to find its organization slug,
            # which we can then use to find the matching Environment and its engine.
            tenant_session_factory = None  # will be set below if env resolution succeeds
            try:
                async with async_session_factory() as ctrl_session:
                    ctrl_result = await ctrl_session.execute(
                        select(Connector).where(
                            Connector.connector_type == ConnectorType.SHOPIFY
                        )
                    )
                    shop_connectors = ctrl_result.scalars().all()
                    matched_connector = None
                    for _c in shop_connectors:
                        if (_c.config or {}).get("shop_url") == shop_domain:
                            matched_connector = _c
                            break

                if matched_connector is not None and shop_domain:
                    # Derive the expected org slug from the shop domain — mirrors
                    # the logic in _provision_shopify_merchant().
                    org_slug = re.sub(r"[.\-]", "_", shop_domain)[:80]
                    expected_db_name = f"oms_{org_slug}_prod"

                    # Look up the Environment in the control DB.
                    async with control_session_factory() as ctrl_env_session:
                        env_result = await ctrl_env_session.execute(
                            select(Environment).where(
                                Environment.db_name == expected_db_name,
                                Environment.status == EnvironmentStatus.ACTIVE,
                            )
                        )
                        tenant_env = env_result.scalar_one_or_none()

                    if tenant_env is not None:
                        # Ensure the engine is registered and obtain its session factory.
                        await _env_registry.get_or_create_engine(tenant_env)
                        tenant_session_factory = _env_registry.get_session_factory(
                            str(tenant_env.id)
                        )
                        logger.info(
                            "GDPR redact: using tenant DB %s for shop=%s",
                            expected_db_name,
                            shop_domain,
                        )
                    else:
                        logger.warning(
                            "GDPR redact: no active environment found for db_name=%s (shop=%s); "
                            "falling back to default session",
                            expected_db_name,
                            shop_domain,
                        )
            except Exception as env_exc:
                logger.error(
                    "GDPR redact: env resolution failed for shop=%s (%s); "
                    "falling back to default session",
                    shop_domain,
                    env_exc,
                )

            # Use tenant session if resolved; otherwise fall back to the default DB.
            _session_ctx = tenant_session_factory() if tenant_session_factory is not None else async_session_factory()

            async with _session_ctx as session:
                for external_order_id in orders_to_redact:
                    # orders_to_redact contains Shopify order IDs (integers or strings).
                    # Match against external_order_id which stores the marketplace order ID.
                    external_id_str = str(external_order_id)
                    result = await session.execute(
                        select(Order).where(
                            Order.external_order_id == external_id_str
                        )
                    )
                    order = result.scalar_one_or_none()
                    if order:
                        order.customer_email = "redacted@gdpr.shopify.com"
                        order.customer_name = "REDACTED"
                        order.customer_phone = None
                        logger.info(
                            "GDPR redact: anonymized order %s (external=%s) for shop=%s",
                            order.id,
                            external_id_str,
                            shop_domain,
                        )
                await session.commit()
        except Exception as exc:
            logger.error(
                "Failed to anonymize orders for GDPR customer redact (shop=%s): %s",
                shop_domain,
                exc,
            )

    # Log to MongoDB.
    try:
        db = await get_mongo_db()
        await db["shopify_gdpr_requests"].insert_one(
            {
                "request_type": "customer_redact",
                "shop_id": body.get("shop_id"),
                "shop_domain": shop_domain,
                "customer": body.get("customer"),
                "orders_to_redact": orders_to_redact,
                "payload": body,
                "received_at": datetime.now(timezone.utc),
            }
        )
    except Exception as exc:
        logger.error("Failed to log Shopify GDPR customer_redact to MongoDB: %s", exc)

    logger.info(
        "Shopify GDPR customer_redact processed for shop=%s orders=%d",
        shop_domain,
        len(orders_to_redact),
    )
    return JSONResponse(status_code=200, content={"status": "ok"})


@router.post("/gdpr/shop/redact")
async def shopify_gdpr_shop_redact(request: Request) -> JSONResponse:
    """
    GDPR shop redact (mandatory Shopify App Store endpoint).

    Triggered 48 hours after app uninstall. Marks the matching Connector as
    INACTIVE (preserves audit trail — no hard delete).
    """
    raw_body = await request.body()
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")

    if not _validate_shopify_hmac(raw_body, hmac_header):
        logger.warning("Shopify GDPR shop_redact HMAC validation failed")
        return JSONResponse(status_code=200, content={"status": "ok"})

    try:
        body: dict = json.loads(raw_body)
    except Exception:
        body = {}

    shop_domain = body.get("shop_domain", "")

    # Mark the connector INACTIVE (preserves audit trail).
    if shop_domain:
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
                    if cfg.get("shop_url") == shop_domain:
                        connector.status = ConnectorStatus.INACTIVE
                        await session.commit()
                        logger.info(
                            "Shopify GDPR shop_redact: connector=%s marked INACTIVE for shop=%s",
                            connector.id,
                            shop_domain,
                        )
                        break
        except Exception as exc:
            logger.error(
                "Failed to mark connector INACTIVE during GDPR shop_redact (shop=%s): %s",
                shop_domain,
                exc,
            )

    # Log to MongoDB.
    try:
        db = await get_mongo_db()
        await db["shopify_gdpr_requests"].insert_one(
            {
                "request_type": "shop_redact",
                "shop_id": body.get("shop_id"),
                "shop_domain": shop_domain,
                "payload": body,
                "received_at": datetime.now(timezone.utc),
            }
        )
    except Exception as exc:
        logger.error("Failed to log Shopify GDPR shop_redact to MongoDB: %s", exc)

    logger.info("Shopify GDPR shop_redact processed for shop=%s", shop_domain)
    return JSONResponse(status_code=200, content={"status": "ok"})


# ---------------------------------------------------------------------------
# App Bridge 3.0 — session token exchange
# ---------------------------------------------------------------------------


class _SessionTokenRequest(BaseModel):
    session_token: str
    shop: str


@router.post("/auth/session-token")
async def shopify_session_token_exchange(body: _SessionTokenRequest) -> JSONResponse:
    """
    Exchange a Shopify App Bridge session token for an OMS access token.

    Called by the embedded frontend after App Bridge provides a short-lived
    Shopify-signed JWT. Validates the Shopify JWT (HS256, signed with
    SHOPIFY_API_SECRET), verifies the matching Connector is ACTIVE, then
    issues a 60-minute OMS bearer token that the frontend uses for all
    subsequent API calls.

    This endpoint is exempt from JWT auth — it IS the auth exchange itself.
    """
    from datetime import timedelta
    import uuid as _uuid_mod

    shop = body.shop.strip().lower()
    session_token = body.session_token.strip()

    # --- Validate Shopify App Store configuration ---------------------------
    if not settings.SHOPIFY_API_KEY or not settings.SHOPIFY_API_SECRET:
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "Shopify App Store integration is not configured. "
                    "Set SHOPIFY_API_KEY and SHOPIFY_API_SECRET to enable it."
                )
            },
        )

    # --- Validate shop hostname ---------------------------------------------
    if not _SHOP_HOSTNAME_RE.match(shop):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid shop hostname. Must match *.myshopify.com"},
        )

    # --- Verify the Shopify session token (HS256, signed with API secret) --
    # Shopify session tokens are short-lived JWTs (1 min) signed with the
    # app's SHOPIFY_API_SECRET. The audience is the SHOPIFY_API_KEY.
    try:
        claims = jose_jwt.decode(
            session_token,
            settings.SHOPIFY_API_SECRET,
            algorithms=["HS256"],
            audience=settings.SHOPIFY_API_KEY,
        )
    except JoseJWTError as exc:
        logger.warning(
            "Shopify session token verification failed for shop=%s: %s", shop, exc
        )
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or expired Shopify session token."},
        )

    # --- Validate iss and dest claims ---------------------------------------
    iss: str = claims.get("iss", "")
    dest: str = claims.get("dest", "")

    if not iss.startswith("https://") or shop not in iss:
        logger.warning(
            "Shopify session token iss claim invalid: iss=%s shop=%s", iss, shop
        )
        return JSONResponse(
            status_code=401,
            content={"detail": "Session token issuer does not match shop."},
        )

    expected_dest = f"https://{shop}"
    if dest != expected_dest:
        logger.warning(
            "Shopify session token dest mismatch: dest=%s expected=%s", dest, expected_dest
        )
        return JSONResponse(
            status_code=401,
            content={"detail": "Session token destination does not match shop."},
        )

    # --- Find the matching ACTIVE Connector for this shop ------------------
    connector = None
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(Connector).where(
                    Connector.connector_type == ConnectorType.SHOPIFY
                )
            )
            shopify_connectors = result.scalars().all()
            for _c in shopify_connectors:
                cfg: dict = _c.config or {}
                if cfg.get("shop_url") == shop:
                    connector = _c
                    break
    except Exception as exc:
        logger.error(
            "Database error looking up Shopify connector for shop=%s: %s", shop, exc
        )
        return JSONResponse(
            status_code=503,
            content={"detail": "Service temporarily unavailable. Please try again."},
        )

    if connector is None or connector.status != ConnectorStatus.ACTIVE:
        logger.warning(
            "Shopify session token exchange: no active connector for shop=%s "
            "(connector=%s status=%s)",
            shop,
            connector.id if connector else None,
            connector.status if connector else "not_found",
        )
        return JSONResponse(
            status_code=401,
            content={"detail": "No active Shopify integration found for this shop."},
        )

    # --- Issue a 60-minute OMS bearer token --------------------------------
    # We build the token manually (rather than via create_access_token) so we
    # can set a 60-minute expiry — App Bridge refreshes the session token every
    # minute and calls this endpoint again, so a 1-hour window is appropriate.
    now = datetime.now(timezone.utc)
    token_claims: dict[str, Any] = {
        "sub": f"shopify:{shop}",
        "shop": shop,
        "connector_id": str(connector.id),
        "is_shopify_embedded": True,
        "is_superadmin": False,
        "platform_role": "USER",
        "permissions": [
            "orders:view",
            "inventory:view",
            "analytics:view",
            "sourcing_rules:view",
            "nodes:view",
            "search:use",
            "ai:use",
            "dashboard:view",
        ],
        "exp": now + timedelta(hours=1),
        "iat": now,
        "jti": str(_uuid_mod.uuid4()),
    }

    from app.core.security import ALGORITHM
    oms_token = jose_jwt.encode(token_claims, settings.SECRET_KEY, algorithm=ALGORITHM)

    logger.info(
        "Shopify embedded session token issued for shop=%s connector=%s",
        shop,
        connector.id,
    )

    return JSONResponse(
        status_code=200,
        content={
            "access_token": oms_token,
            "token_type": "bearer",
            "shop": shop,
            "connector_id": str(connector.id),
        },
    )
