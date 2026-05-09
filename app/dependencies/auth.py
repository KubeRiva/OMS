import asyncio
import hashlib
import re
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select


async def get_current_user(request: Request) -> dict:
    """Extract the authenticated user from request state (set by auth middleware)."""
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user


async def get_current_user_or_api_key(request: Request) -> dict:
    """Authenticate via JWT session (set by middleware) or X-API-Key header.

    Resolution order:
    1. JWT path — request.state.user populated by auth_middleware; returned as-is.
    2. API key path — X-API-Key header hashed and looked up in api_keys table.
    3. Neither present → HTTP 401.
    """
    # 1. JWT path (already validated by auth_middleware)
    user = getattr(request.state, "user", None)
    if user is not None:
        return user

    # 2. API key path
    raw_key = request.headers.get("X-API-Key", "").strip()
    if raw_key:
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        from app.database.postgres import async_session_factory
        from app.models.postgres.api_key_models import ApiKey

        async with async_session_factory() as session:
            now = datetime.now(timezone.utc)
            result = await session.execute(
                select(ApiKey).where(
                    ApiKey.key_hash == key_hash,
                    ApiKey.is_active.is_(True),
                    (ApiKey.expires_at.is_(None)) | (ApiKey.expires_at > now),
                )
            )
            api_key = result.scalar_one_or_none()

        if api_key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired API key",
            )

        # Finding 1: Keys must have an attributable owner
        if api_key.owner_user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key has no associated owner — contact an administrator",
            )

        # Fire-and-forget: update last_used_at without blocking the request
        async def _touch_last_used(key_id) -> None:
            try:
                from app.database.postgres import async_session_factory as _factory
                from app.models.postgres.api_key_models import ApiKey as _ApiKey
                from sqlalchemy import update
                async with _factory() as _session:
                    await _session.execute(
                        update(_ApiKey)
                        .where(_ApiKey.id == key_id)
                        .values(last_used_at=datetime.now(timezone.utc))
                    )
                    await _session.commit()
            except Exception:
                pass  # best-effort; never block the request path

        # Finding 6: guard against no running event loop (test contexts)
        try:
            asyncio.create_task(_touch_last_used(api_key.id))
        except RuntimeError:
            pass

        # Finding 1: include "sub" for structural parity with JWT user dicts
        return {
            "sub": str(api_key.owner_user_id),
            "id": str(api_key.owner_user_id),
            "api_key_id": str(api_key.id),
            "scopes": api_key.scopes or [],
            "is_superadmin": False,
            "platform_role": None,
        }

    # 3. No credentials supplied
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
    )


def require_scope(required_scope: str):
    """Dependency factory that enforces an API key scope.

    JWT (session) users are not scope-limited — they have full access.
    API key users must have the specified scope or receive HTTP 403.

    Usage::

        @router.post("/orders/")
        async def create_order(
            user: dict = Depends(require_scope("orders:write")),
        ):
    """
    async def _check(user: dict = Depends(get_current_user_or_api_key)) -> dict:
        # JWT users bypass scope enforcement
        if "api_key_id" not in user:
            return user
        scopes = user.get("scopes") or []
        if required_scope not in scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API key missing required scope: {required_scope}",
            )
        return user
    return _check


async def require_superadmin(user: dict = Depends(get_current_user)) -> dict:
    """Require the current user to be a superadmin (SUPERADMIN or PLATFORM_OWNER)."""
    if not user.get("is_superadmin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


async def require_platform_owner(user: dict = Depends(get_current_user)) -> dict:
    """Require the current user to be a Platform Owner (exclusive top-tier role)."""
    if user.get("platform_role") != "PLATFORM_OWNER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform Owner access required",
        )
    return user
