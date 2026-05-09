"""
EnvironmentMiddleware — resolves the active environment for every request.

Resolution order:
  1. X-OMS-Environment header (UUID string)
  2. Redis cache (60s TTL) keyed by "env:{env_id}"
  3. Control DB lookup
  4. Fall back to the organization's is_default=True environment
  5. Fall back to the system-wide default (is_default=True across all orgs)

Exempt paths bypass resolution (no request.state.environment set):
  /health, /docs, /redoc, /openapi.json, /auth/*, /connectors/*/webhook
"""
import json
import logging
import re
from typing import Optional

from fastapi import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Paths that do not need environment resolution
_EXEMPT_PREFIXES = ("/health", "/docs", "/redoc", "/openapi.json", "/auth/")
_WEBHOOK_RE = re.compile(r"^/connectors/[^/]+/webhook$")

_ENV_CACHE_TTL = 60  # seconds


async def _attach_tenant_mode(session, env) -> None:
    """Fetch the org's tenant_mode and attach it directly on the env object."""
    try:
        from app.models.postgres.org_models import Organization
        org = await session.get(Organization, env.organization_id)
        env.tenant_mode = org.tenant_mode if org else "HYBRID"
    except Exception:
        env.tenant_mode = "HYBRID"


class EnvironmentMiddleware:
    """Resolve the active environment and store it in request.state.environment.

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
        path = request.url.path

        # Skip exempt paths
        if any(path.startswith(p) for p in _EXEMPT_PREFIXES) or _WEBHOOK_RE.match(path):
            await self.app(scope, receive, send)
            return

        try:
            env = await self._resolve(request)
        except Exception as exc:
            logger.error("EnvironmentMiddleware: resolution error: %s", exc, exc_info=True)
            await self.app(scope, receive, send)
            return

        if env is not None:
            from app.models.postgres.org_models import EnvironmentStatus
            if env.status not in (EnvironmentStatus.ACTIVE,):
                response = JSONResponse(
                    {"detail": f"Environment '{env.name}' is {env.status.value.lower()} and not available."},
                    status_code=503,
                )
                await response(scope, receive, send)
                return
            tenant_mode = getattr(env, "tenant_mode", "HYBRID")
            scope["state"] = scope.get("state") or {}
            scope["state"]["environment"] = env
            scope["state"]["environment_id"] = str(env.id)
            scope["state"]["tenant_mode"] = tenant_mode
            # Also set on request.state for compatibility
            request.state.environment = env
            request.state.environment_id = str(env.id)
            request.state.tenant_mode = tenant_mode

        await self.app(scope, receive, send)

    async def _resolve(self, request: Request):
        """Return an Environment ORM object or None."""
        env_id_header = request.headers.get("X-OMS-Environment")

        # Try cache first
        if env_id_header:
            cached = await self._get_cached(env_id_header)
            if cached is not None:
                return cached

        # Lookup from DB
        env = await self._lookup_db(env_id_header)
        if env is not None and env_id_header:
            await self._set_cached(env_id_header, env)

        return env

    async def _lookup_db(self, env_id: Optional[str]):
        """Query control DB for the environment."""
        try:
            from sqlalchemy import select
            from app.database.postgres import async_session_factory
            from app.models.postgres.org_models import Environment, EnvironmentStatus

            async with async_session_factory() as session:
                if env_id:
                    import uuid as _uuid
                    try:
                        uid = _uuid.UUID(env_id)
                    except ValueError:
                        return None
                    result = await session.execute(
                        select(Environment).where(Environment.id == uid)
                    )
                    env = result.scalar_one_or_none()
                    if env:
                        await _attach_tenant_mode(session, env)
                        return env

                # Fall back to system-wide default
                result = await session.execute(
                    select(Environment)
                    .where(Environment.is_default == True)  # noqa: E712
                    .where(Environment.status == EnvironmentStatus.ACTIVE)
                    .limit(1)
                )
                env = result.scalar_one_or_none()
                if env:
                    await _attach_tenant_mode(session, env)
                return env

        except Exception as exc:
            logger.warning("EnvironmentMiddleware: DB lookup failed: %s", exc)
            return None

    async def _get_cached(self, env_id: str):
        """Try to get the environment from Redis cache."""
        try:
            from app.database.redis_client import get_redis_client
            redis = get_redis_client()
            if redis is None:
                return None
            data = await redis.get(f"env:{env_id}")
            await redis.aclose()
            if data is None:
                return None
            return await self._deserialize_env(json.loads(data))
        except Exception:
            return None

    async def _set_cached(self, env_id: str, env) -> None:
        """Store the environment in Redis cache."""
        try:
            from app.database.redis_client import get_redis_client
            redis = get_redis_client()
            if redis is None:
                return
            # NOTE: pg_user and pg_password are intentionally excluded from the
            # cache payload.  Credentials must never be stored in Redis in
            # plaintext.  The env-specific DB engine is built from the control
            # DB record on cache miss; these fields are only needed at that point.
            payload = {
                "id": str(env.id),
                "organization_id": str(env.organization_id),
                "name": env.name,
                "slug": env.slug,
                "env_type": env.env_type.value,
                "status": env.status.value,
                "db_name": env.db_name,
                "mongo_events_db": env.mongo_events_db,
                "mongo_ai_db": env.mongo_ai_db,
                "es_index_prefix": env.es_index_prefix,
                "pg_host": env.pg_host,
                "pg_port": env.pg_port,
                "is_default": env.is_default,
                "tenant_mode": getattr(env, "tenant_mode", "HYBRID"),
            }
            await redis.setex(f"env:{env_id}", _ENV_CACHE_TTL, json.dumps(payload))
            await redis.aclose()
        except Exception:
            pass  # Cache failure is non-fatal

    async def _deserialize_env(self, data: dict):
        """Reconstruct a lightweight Environment-like object from cache."""
        from app.models.postgres.org_models import Environment, EnvironmentType, EnvironmentStatus
        import uuid as _uuid

        env = Environment.__new__(Environment)
        env.id = _uuid.UUID(data["id"])
        env.organization_id = _uuid.UUID(data["organization_id"])
        env.name = data["name"]
        env.slug = data["slug"]
        env.env_type = EnvironmentType(data["env_type"])
        env.status = EnvironmentStatus(data["status"])
        env.db_name = data["db_name"]
        env.mongo_events_db = data["mongo_events_db"]
        env.mongo_ai_db = data["mongo_ai_db"]
        env.es_index_prefix = data["es_index_prefix"]
        env.pg_host = data.get("pg_host")
        env.pg_port = data.get("pg_port")
        env.pg_user = None   # credentials not cached in Redis
        env.pg_password = None  # credentials not cached in Redis
        env.is_default = data.get("is_default", False)
        env.tenant_mode = data.get("tenant_mode", "HYBRID")
        return env
