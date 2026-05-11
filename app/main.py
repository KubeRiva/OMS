"""OMS FastAPI application entry point."""
import json
import logging
import logging.config
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.core.security import hash_password, verify_token, verify_token_async
from app.database.postgres import init_db, async_session_factory
from app.database.mongodb import connect_to_mongo, close_mongo_connection
from app.database.redis_client import init_redis, close_redis
from app.database.elasticsearch_client import connect_to_elasticsearch, close_elasticsearch


# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------

class _JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line for Grafana/Loki ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "tenant": settings.TENANT_SLUG,
            "env": settings.ENVIRONMENT,
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def _configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, settings.LOG_LEVEL, logging.INFO))
    # Quiet noisy third-party loggers
    for noisy in ("sqlalchemy.engine", "httpx", "motor", "elasticsearch"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


_configure_logging()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Startup helpers
# ---------------------------------------------------------------------------

async def seed_admin_user() -> None:
    """Create a default superadmin if no users exist."""
    import secrets
    from sqlalchemy import select, func
    from app.models.postgres.auth_models import User

    async with async_session_factory() as session:
        count = (await session.execute(select(func.count(User.id)))).scalar_one()
        if count == 0:
            # Use settings-supplied password or generate a one-time random password
            password = settings.BOOTSTRAP_ADMIN_PASSWORD or secrets.token_urlsafe(16)
            admin = User(
                email=settings.BOOTSTRAP_ADMIN_EMAIL,
                full_name="OMS Administrator",
                hashed_password=hash_password(password),
                is_active=True,
                is_superadmin=True,
            )
            session.add(admin)
            await session.commit()
            if settings.BOOTSTRAP_ADMIN_PASSWORD:
                logger.warning(
                    "Default admin created: %s — password set from BOOTSTRAP_ADMIN_PASSWORD env var",
                    settings.BOOTSTRAP_ADMIN_EMAIL,
                )
            else:
                logger.warning(
                    "Default admin created: %s — password auto-generated and stored (check BOOTSTRAP_ADMIN_PASSWORD to set explicitly)",
                    settings.BOOTSTRAP_ADMIN_EMAIL,
                )


async def seed_default_lifecycles() -> None:
    """
    Seed one built-in lifecycle per fulfillment type on first startup.
    Each subsequent startup is a no-op (idempotent via name uniqueness check).
    """
    from sqlalchemy import select, func
    from app.models.postgres.lifecycle_models import Lifecycle, LifecycleStep

    DEFAULTS = [
        {
            "name": "Standard Ship-to-Home",
            "description": "Full forward-logistics flow for home delivery orders",
            "fulfillment_types": ["SHIP_TO_HOME"],
            "channels": [],
            "is_default": True,
            "steps": [
                {"status": "PENDING",           "label": "Pending",            "step_order": 0,  "allowed_next_statuses": ["CONFIRMED", "CANCELLED"],         "action_type": None},
                {"status": "CONFIRMED",         "label": "Confirmed",          "step_order": 1,  "allowed_next_statuses": ["SOURCING", "CANCELLED"],          "action_type": None},
                {"status": "SOURCING",          "label": "Sourcing",           "step_order": 2,  "allowed_next_statuses": ["SOURCED", "BACKORDERED", "FAILED"],"action_type": None},
                {"status": "BACKORDERED",       "label": "Backordered",        "step_order": 3,  "allowed_next_statuses": ["SOURCING", "CANCELLED"],          "action_type": None},
                {"status": "SOURCED",           "label": "Sourced",            "step_order": 4,  "allowed_next_statuses": ["PICKING", "CANCELLED"],           "action_type": None},
                {"status": "PICKING",           "label": "Picking",            "step_order": 5,  "allowed_next_statuses": ["PACKING"],                        "action_type": None},
                {"status": "PACKING",           "label": "Packing",            "step_order": 6,  "allowed_next_statuses": ["READY_TO_SHIP"],                  "action_type": None},
                {"status": "READY_TO_SHIP",     "label": "Ready to Ship",      "step_order": 7,  "allowed_next_statuses": ["SHIPPED", "PARTIALLY_SHIPPED"],   "action_type": "book_shipment"},
                {"status": "SHIPPED",           "label": "Shipped",            "step_order": 8,  "allowed_next_statuses": ["OUT_FOR_DELIVERY"],               "action_type": "simulate_delivery"},
                {"status": "OUT_FOR_DELIVERY",  "label": "Out for Delivery",   "step_order": 9,  "allowed_next_statuses": ["DELIVERED", "PARTIALLY_DELIVERED","FAILED"], "action_type": None},
                {"status": "DELIVERED",         "label": "Delivered",          "step_order": 10, "allowed_next_statuses": ["RETURNED"],                       "action_type": None},
                {"status": "CANCELLED",         "label": "Cancelled",          "step_order": 11, "allowed_next_statuses": [],                                 "action_type": None},
                {"status": "RETURNED",          "label": "Returned",           "step_order": 12, "allowed_next_statuses": ["REFUNDED"],                       "action_type": None},
                {"status": "REFUNDED",          "label": "Refunded",           "step_order": 13, "allowed_next_statuses": [],                                 "action_type": None},
            ],
        },
        {
            "name": "Buy Online Pickup In Store (BOPIS)",
            "description": "BOPIS flow — items picked in-store, customer collects",
            "fulfillment_types": ["STORE_PICKUP"],
            "channels": [],
            "is_default": False,
            "steps": [
                {"status": "PENDING",           "label": "Pending",            "step_order": 0, "allowed_next_statuses": ["CONFIRMED", "CANCELLED"],        "action_type": None},
                {"status": "CONFIRMED",         "label": "Confirmed",          "step_order": 1, "allowed_next_statuses": ["SOURCING", "CANCELLED"],         "action_type": None},
                {"status": "SOURCING",          "label": "Sourcing",           "step_order": 2, "allowed_next_statuses": ["SOURCED", "BACKORDERED", "FAILED"],"action_type": None},
                {"status": "BACKORDERED",       "label": "Backordered",        "step_order": 3, "allowed_next_statuses": ["SOURCING", "CANCELLED"],         "action_type": None},
                {"status": "SOURCED",           "label": "Sourced",            "step_order": 4, "allowed_next_statuses": ["PICKING", "CANCELLED"],          "action_type": None},
                {"status": "PICKING",           "label": "Picking",            "step_order": 5, "allowed_next_statuses": ["PACKING"],                       "action_type": None},
                {"status": "PACKING",           "label": "Packing",            "step_order": 6, "allowed_next_statuses": ["READY_FOR_PICKUP"],              "action_type": None},
                {"status": "READY_FOR_PICKUP",  "label": "Ready for Pickup",   "step_order": 7, "allowed_next_statuses": ["PICKED_UP", "CANCELLED"],        "action_type": "send_pickup_ready"},
                {"status": "PICKED_UP",         "label": "Picked Up",          "step_order": 8, "allowed_next_statuses": ["RETURNED"],                      "action_type": None},
                {"status": "CANCELLED",         "label": "Cancelled",          "step_order": 9, "allowed_next_statuses": [],                                "action_type": None},
                {"status": "RETURNED",          "label": "Returned",           "step_order": 10,"allowed_next_statuses": ["REFUNDED"],                      "action_type": None},
                {"status": "REFUNDED",          "label": "Refunded",           "step_order": 11,"allowed_next_statuses": [],                                "action_type": None},
            ],
        },
        {
            "name": "Curbside Pickup",
            "description": "Customer picks up order at curbside — no carrier booking",
            "fulfillment_types": ["CURBSIDE_PICKUP"],
            "channels": [],
            "is_default": False,
            "steps": [
                {"status": "PENDING",           "label": "Pending",            "step_order": 0, "allowed_next_statuses": ["CONFIRMED", "CANCELLED"],        "action_type": None},
                {"status": "CONFIRMED",         "label": "Confirmed",          "step_order": 1, "allowed_next_statuses": ["SOURCING", "CANCELLED"],         "action_type": None},
                {"status": "SOURCING",          "label": "Sourcing",           "step_order": 2, "allowed_next_statuses": ["SOURCED", "BACKORDERED", "FAILED"],"action_type": None},
                {"status": "BACKORDERED",       "label": "Backordered",        "step_order": 3, "allowed_next_statuses": ["SOURCING", "CANCELLED"],         "action_type": None},
                {"status": "SOURCED",           "label": "Sourced",            "step_order": 4, "allowed_next_statuses": ["PICKING", "CANCELLED"],          "action_type": None},
                {"status": "PICKING",           "label": "Picking",            "step_order": 5, "allowed_next_statuses": ["PACKING"],                       "action_type": None},
                {"status": "PACKING",           "label": "Packing",            "step_order": 6, "allowed_next_statuses": ["READY_FOR_PICKUP"],              "action_type": None},
                {"status": "READY_FOR_PICKUP",  "label": "Ready — Pull Around","step_order": 7, "allowed_next_statuses": ["PICKED_UP", "CANCELLED"],        "action_type": "send_pickup_ready"},
                {"status": "PICKED_UP",         "label": "Picked Up",          "step_order": 8, "allowed_next_statuses": ["RETURNED"],                      "action_type": None},
                {"status": "CANCELLED",         "label": "Cancelled",          "step_order": 9, "allowed_next_statuses": [],                                "action_type": None},
                {"status": "RETURNED",          "label": "Returned",           "step_order": 10,"allowed_next_statuses": ["REFUNDED"],                      "action_type": None},
                {"status": "REFUNDED",          "label": "Refunded",           "step_order": 11,"allowed_next_statuses": [],                                "action_type": None},
            ],
        },
        {
            "name": "Ship from Store",
            "description": "Retail store ships directly to customer — same pipeline as home delivery",
            "fulfillment_types": ["SHIP_FROM_STORE"],
            "channels": [],
            "is_default": False,
            "steps": [
                {"status": "PENDING",           "label": "Pending",            "step_order": 0,  "allowed_next_statuses": ["CONFIRMED", "CANCELLED"],         "action_type": None},
                {"status": "CONFIRMED",         "label": "Confirmed",          "step_order": 1,  "allowed_next_statuses": ["SOURCING", "CANCELLED"],          "action_type": None},
                {"status": "SOURCING",          "label": "Sourcing",           "step_order": 2,  "allowed_next_statuses": ["SOURCED", "BACKORDERED", "FAILED"],"action_type": None},
                {"status": "BACKORDERED",       "label": "Backordered",        "step_order": 3,  "allowed_next_statuses": ["SOURCING", "CANCELLED"],          "action_type": None},
                {"status": "SOURCED",           "label": "Sourced",            "step_order": 4,  "allowed_next_statuses": ["PICKING", "CANCELLED"],           "action_type": None},
                {"status": "PICKING",           "label": "Picking",            "step_order": 5,  "allowed_next_statuses": ["PACKING"],                        "action_type": None},
                {"status": "PACKING",           "label": "Packing",            "step_order": 6,  "allowed_next_statuses": ["READY_TO_SHIP"],                  "action_type": None},
                {"status": "READY_TO_SHIP",     "label": "Ready to Ship",      "step_order": 7,  "allowed_next_statuses": ["SHIPPED", "PARTIALLY_SHIPPED"],   "action_type": "book_shipment"},
                {"status": "SHIPPED",           "label": "Shipped",            "step_order": 8,  "allowed_next_statuses": ["OUT_FOR_DELIVERY"],               "action_type": "simulate_delivery"},
                {"status": "OUT_FOR_DELIVERY",  "label": "Out for Delivery",   "step_order": 9,  "allowed_next_statuses": ["DELIVERED", "FAILED"],            "action_type": None},
                {"status": "DELIVERED",         "label": "Delivered",          "step_order": 10, "allowed_next_statuses": ["RETURNED"],                       "action_type": None},
                {"status": "CANCELLED",         "label": "Cancelled",          "step_order": 11, "allowed_next_statuses": [],                                 "action_type": None},
                {"status": "RETURNED",          "label": "Returned",           "step_order": 12, "allowed_next_statuses": ["REFUNDED"],                       "action_type": None},
                {"status": "REFUNDED",          "label": "Refunded",           "step_order": 13, "allowed_next_statuses": [],                                 "action_type": None},
            ],
        },
        {
            "name": "Same-Day Delivery",
            "description": "Express local delivery — must reach customer same day",
            "fulfillment_types": ["SAME_DAY_DELIVERY"],
            "channels": [],
            "is_default": False,
            "steps": [
                {"status": "PENDING",           "label": "Pending",            "step_order": 0,  "allowed_next_statuses": ["CONFIRMED", "CANCELLED"],         "action_type": None,               "sla_hours": None},
                {"status": "CONFIRMED",         "label": "Confirmed",          "step_order": 1,  "allowed_next_statuses": ["SOURCING", "CANCELLED"],          "action_type": None,               "sla_hours": 0.25},
                {"status": "SOURCING",          "label": "Sourcing",           "step_order": 2,  "allowed_next_statuses": ["SOURCED", "BACKORDERED", "FAILED"],"action_type": None,               "sla_hours": 0.25},
                {"status": "SOURCED",           "label": "Sourced",            "step_order": 3,  "allowed_next_statuses": ["PICKING", "CANCELLED"],           "action_type": None,               "sla_hours": 0.5},
                {"status": "PICKING",           "label": "Picking",            "step_order": 4,  "allowed_next_statuses": ["PACKING"],                        "action_type": None,               "sla_hours": 1.0},
                {"status": "PACKING",           "label": "Packing",            "step_order": 5,  "allowed_next_statuses": ["READY_TO_SHIP"],                  "action_type": None,               "sla_hours": 0.5},
                {"status": "READY_TO_SHIP",     "label": "Ready to Ship",      "step_order": 6,  "allowed_next_statuses": ["SHIPPED"],                        "action_type": "book_shipment",    "sla_hours": 0.5},
                {"status": "SHIPPED",           "label": "Out for Delivery",   "step_order": 7,  "allowed_next_statuses": ["DELIVERED", "FAILED"],            "action_type": "simulate_delivery","sla_hours": 4.0},
                {"status": "DELIVERED",         "label": "Delivered",          "step_order": 8,  "allowed_next_statuses": ["RETURNED"],                       "action_type": None,               "sla_hours": None},
                {"status": "CANCELLED",         "label": "Cancelled",          "step_order": 9,  "allowed_next_statuses": [],                                 "action_type": None,               "sla_hours": None},
                {"status": "RETURNED",          "label": "Returned",           "step_order": 10, "allowed_next_statuses": ["REFUNDED"],                       "action_type": None,               "sla_hours": None},
                {"status": "REFUNDED",          "label": "Refunded",           "step_order": 11, "allowed_next_statuses": [],                                 "action_type": None,               "sla_hours": None},
            ],
        },
    ]

    async with async_session_factory() as session:
        existing = (await session.execute(select(func.count(Lifecycle.id)))).scalar_one()
        if existing > 0:
            return

        for lc_data in DEFAULTS:
            lc = Lifecycle(
                name=lc_data["name"],
                description=lc_data["description"],
                fulfillment_types=lc_data["fulfillment_types"],
                channels=lc_data["channels"],
                is_active=True,
                is_default=lc_data.get("is_default", False),
                created_by="system",
            )
            session.add(lc)
            await session.flush()
            for s in lc_data["steps"]:
                session.add(LifecycleStep(
                    lifecycle_id=lc.id,
                    status=s["status"],
                    label=s["label"],
                    description="",
                    step_order=s["step_order"],
                    allowed_next_statuses=s["allowed_next_statuses"],
                    action_type=s.get("action_type"),
                    sla_hours=s.get("sla_hours"),
                ))

        await session.commit()
        logger.info("Seeded %d default lifecycles", len(DEFAULTS))


async def seed_default_environment() -> None:
    """
    Seed a default Organization + Production environment pointing at this pod's DB.
    Runs once on first startup; subsequent calls are no-ops.
    Also grants ADMIN role to every existing user.
    """
    import re
    from datetime import datetime, timezone
    from sqlalchemy import select, func
    from app.models.postgres.auth_models import User
    from app.models.postgres.org_models import (
        Organization, Environment, UserEnvironmentRole,
        EnvironmentType, EnvironmentStatus, EnvironmentRole,
    )

    async with async_session_factory() as session:
        count = (await session.execute(select(func.count(Organization.id)))).scalar_one()
        if count > 0:
            return

        db_name_match = re.search(r"/([^/]+)$", settings.DATABASE_URL)
        db_name = db_name_match.group(1) if db_name_match else "oms_db"

        org = Organization(
            name="Default Organization",
            slug="default",
            description="Auto-created default organization",
            tenant_mode="HYBRID",  # supports both B2C and B2B out of the box
        )
        session.add(org)
        await session.flush()

        env = Environment(
            organization_id=org.id,
            name="Production",
            slug="prod",
            env_type=EnvironmentType.PROD,
            status=EnvironmentStatus.ACTIVE,
            db_name=db_name,
            mongo_events_db=settings.MONGODB_DB,
            mongo_ai_db=settings.MONGODB_AI_DB,
            es_index_prefix="default_prod",
            base_url=settings.FRONTEND_URL or None,
            is_default=True,
            provisioned_at=datetime.now(timezone.utc),
        )
        session.add(env)
        await session.flush()

        users = (await session.execute(select(User))).scalars().all()
        for user in users:
            session.add(UserEnvironmentRole(
                user_id=user.id,
                environment_id=env.id,
                role=EnvironmentRole.ADMIN,
            ))

        await session.commit()
        logger.info("Seeded default organization + Production environment (db=%s, %d users)", db_name, len(users))


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting OMS API (tenant=%s env=%s plan=%s)", settings.TENANT_SLUG, settings.ENVIRONMENT, settings.PLAN_TIER)

    await init_db()
    logger.info("PostgreSQL tables created/verified")

    await connect_to_mongo()
    logger.info("MongoDB connected")

    await init_redis()
    logger.info("Redis connected")

    await connect_to_elasticsearch()
    logger.info("Elasticsearch connected")

    await seed_admin_user()
    await seed_default_environment()
    await seed_default_lifecycles()

    logger.info("OMS API ready")
    yield

    logger.info("Shutting down OMS API...")
    await close_mongo_connection()
    await close_redis()
    await close_elasticsearch()
    logger.info("OMS API shutdown complete")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="OMS — Omni-Channel Order Management System",
    description=(
        "Production-grade OMS supporting WEB, MOBILE, POS, API, MARKETPLACE channels "
        "with configurable sourcing rules, real-time inventory, and full fulfillment pipeline."
    ),
    version="0.2.0",
    docs_url=None,
    redoc_url=None,
    openapi_url="/openapi.json",
    lifespan=lifespan,
)


@app.get("/docs", include_in_schema=False, response_class=HTMLResponse)
async def swagger_ui():
    return get_swagger_ui_html(openapi_url="/openapi.json", title="OMS API Documentation")


@app.get("/redoc", include_in_schema=False, response_class=HTMLResponse)
async def redoc_ui():
    return get_redoc_html(openapi_url="/openapi.json", title="OMS API Documentation")


# Rate limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Too many requests. Please try again later."})


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    expose_headers=["Content-Type"],
    max_age=3600,
)

# Plan tier enforcement (checks order/warehouse/user limits per PLAN_TIER)
from app.middleware.plan_tier import PlanTierMiddleware
app.add_middleware(PlanTierMiddleware)

# Environment resolution — reads X-OMS-Environment header, resolves to Environment
# record, stores in request.state.environment for env-aware get_db()
from app.middleware.environment import EnvironmentMiddleware
app.add_middleware(EnvironmentMiddleware)

_EXEMPT_PREFIXES = (
    "/docs", "/redoc", "/openapi.json", "/health", "/auth/login",
    "/shopify/install", "/shopify/callback", "/shopify/gdpr/", "/shopify/webhooks/",
    "/shopify/billing/plans", "/shopify/billing/confirm",
    "/shopify/auth/session-token",
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    if settings.ENVIRONMENT == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=(), payment=()"
    if request.url.path.startswith(("/docs", "/redoc")):
        # Swagger UI / ReDoc load assets from CDN — allow those origins
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https://fastapi.tiangolo.com; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )
    else:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )
    return response


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get("x-correlation-id") or str(uuid.uuid4())
    request.state.correlation_id = correlation_id
    response = await call_next(request)
    response.headers["x-correlation-id"] = correlation_id
    return response


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    import re
    path = request.url.path

    if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
        return await call_next(request)

    if re.match(r"^/connectors/[^/]+/webhook$", path):
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""

    # Fall back to the httpOnly cookie when no Authorization header is present
    if not token:
        token = request.cookies.get("access_token", "")

    if not token:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Not authenticated"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = await verify_token_async(token)
        request.state.user = payload
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Invalid or expired token"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await call_next(request)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception: %s", exc)
    try:
        from app.services.monitoring import capture_error, SOURCE_API
        await capture_error(
            exc=exc, source_service=SOURCE_API, level="ERROR",
            request_context={
                "method": request.method,
                "path": request.url.path,
                "status_code": 500,
                "correlation_id": getattr(request.state, "correlation_id", None),
            },
            tags=["unhandled"],
        )
    except Exception:
        pass
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
            "request_id": getattr(request.state, "correlation_id", None),
        },
    )


# ---------------------------------------------------------------------------
# Health check (K8s liveness + readiness probe)
# ---------------------------------------------------------------------------

@app.get("/health", tags=["Health"])
async def health_check():
    """
    Verifies DB and Redis connectivity.
    Returns 503 if any dependency is unreachable — K8s will restart the pod.
    """
    checks: dict = {}
    overall = "healthy"

    # PostgreSQL
    try:
        from sqlalchemy import text
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"error: {exc}"
        overall = "degraded"

    # Redis
    try:
        from app.database.redis_client import get_redis_client
        redis = get_redis_client()
        if redis:
            await redis.ping()
            await redis.aclose()
            checks["redis"] = "ok"
        else:
            checks["redis"] = "not configured"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"
        overall = "degraded"

    response_body = {
        "status": overall,
        "version": "1.0.0",
    }

    return JSONResponse(
        content=response_body,
        status_code=200 if overall == "healthy" else 503,
    )


@app.get("/", tags=["Root"])
async def root():
    return {"name": "OMS — Omni-Channel Order Management System", "docs": "/docs", "health": "/health"}


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

from app.routers import orders, inventory, sourcing_rules, nodes, search, analytics, webhooks, ai, connectors
from app.routers import auth, admin, monitoring, performance, testing, architect, ops
from app.routers import organizations, environments, lifecycles
from app.routers import api_keys as api_keys_module
from app.routers import customers
from app.routers import brands
from app.routers import invoices
from app.routers.invoices import credit_memo_router
from app.routers import returns as returns_module
from app.routers.returns import order_refunds_router
from app.routers.customer_profiles import router as customer_profiles_router
from app.routers import distribution_groups
from app.routers import brand_access
from app.models.postgres import user_brand_role_models  # noqa: F401 — ensure DDL is registered

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(brands.router)
app.include_router(customers.router)
app.include_router(invoices.router)
app.include_router(credit_memo_router)
app.include_router(orders.router)
app.include_router(inventory.router)
app.include_router(sourcing_rules.router)
app.include_router(nodes.router)
app.include_router(search.router)
app.include_router(analytics.router)
app.include_router(webhooks.router)
app.include_router(ai.router)
app.include_router(connectors.router)
app.include_router(monitoring.router)
app.include_router(ops.router)
app.include_router(performance.router)
app.include_router(architect.router)
app.include_router(organizations.router)
app.include_router(environments.router)
app.include_router(lifecycles.router)
app.include_router(distribution_groups.router)
app.include_router(brand_access.router)
app.include_router(api_keys_module.router)
app.include_router(returns_module.router)
app.include_router(order_refunds_router)
app.include_router(customer_profiles_router)

if settings.ENVIRONMENT == "development":
    logger.info("Testing endpoints enabled (development mode only)")
    app.include_router(testing.router)
else:
    logger.warning("Testing endpoints disabled (production mode)")
