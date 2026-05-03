"""
Plan tier enforcement middleware.

Intercepts write operations and checks resource counts against the plan limits
for this pod's PLAN_TIER. Returns HTTP 429 when a limit would be exceeded.

Limits per tier:
  STARTER   — 500 orders/month,  1 warehouse,  2 users
  GROWTH    — 5 000 orders/month, 5 warehouses, 10 users
  PRO       — 50 000 orders/month, 20 warehouses, 50 users
  ENTERPRISE — unlimited
"""
import logging

from fastapi import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings

logger = logging.getLogger(__name__)

# (orders_per_month, warehouses, users)  — None = unlimited
_LIMITS: dict[str, dict[str, int | None]] = {
    "STARTER":    {"orders": 500,    "nodes": 1,  "users": 2},
    "GROWTH":     {"orders": 5_000,  "nodes": 5,  "users": 10},
    "PRO":        {"orders": 50_000, "nodes": 20, "users": 50},
    "ENTERPRISE": {"orders": None,   "nodes": None, "users": None},
}

# Routes and the resource type they create
_GUARDED_ROUTES: dict[tuple[str, str], str] = {
    ("POST", "/orders"):         "orders",
    ("POST", "/nodes"):          "nodes",
    ("POST", "/admin/users"):    "users",
}


def _get_limits() -> dict[str, int | None]:
    tier = settings.PLAN_TIER.upper()
    return _LIMITS.get(tier, _LIMITS["STARTER"])


class PlanTierMiddleware:
    """Check plan limits before allowing resource creation.

    Pure ASGI middleware (no BaseHTTPMiddleware) to avoid ExceptionGroup issues
    with Starlette 0.37+ / anyio task groups.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive, send)
        method = request.method
        path = request.url.path

        resource = _GUARDED_ROUTES.get((method, path))
        if resource is None:
            await self.app(scope, receive, send)
            return

        limits = _get_limits()
        limit = limits.get(resource)
        if limit is None:
            await self.app(scope, receive, send)
            return

        try:
            current = await self._count(resource)
        except Exception as exc:
            logger.warning("PlanTierMiddleware: count query failed for %s: %s", resource, exc)
            await self.app(scope, receive, send)
            return

        if current >= limit:
            tier = settings.PLAN_TIER
            response = JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        f"Plan limit reached: your {tier} plan allows {limit} {resource}. "
                        "Upgrade your plan to create more."
                    ),
                    "plan_tier": tier,
                    "resource": resource,
                    "limit": limit,
                    "current": current,
                },
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

    async def _count(self, resource: str) -> int:
        from sqlalchemy import select, func, text
        from app.database.postgres import async_session_factory

        async with async_session_factory() as session:
            if resource == "orders":
                # Count orders created in the current calendar month
                result = await session.execute(
                    text(
                        "SELECT COUNT(*) FROM orders "
                        "WHERE created_at >= date_trunc('month', now())"
                    )
                )
                return result.scalar_one()

            if resource == "nodes":
                from app.models.postgres.node_models import FulfillmentNode
                result = await session.execute(select(func.count(FulfillmentNode.id)))
                return result.scalar_one()

            if resource == "users":
                from app.models.postgres.auth_models import User
                result = await session.execute(select(func.count(User.id)))
                return result.scalar_one()

        return 0
