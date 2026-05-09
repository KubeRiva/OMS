"""Brand-scope dependency — resolves which brand IDs the current user may access."""
from typing import List, Optional

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.postgres import get_db
from app.dependencies.auth import get_current_user


async def get_accessible_brand_ids(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> Optional[List[str]]:
    """Resolve which brand IDs the current user may access in this environment.

    Return semantics:
      None      — user is superadmin / platform owner; no brand restriction applied
      [id, ...] — user is brand-scoped; caller must filter to this set
      []        — user has no brand assignments; caller should return empty results

    The environment is read from request.state.environment (set by EnvironmentMiddleware).
    On exempt paths where the middleware did not run, env_id will be None and the query
    falls back to matching on NULL environment_id — which will return no rows, correctly
    defaulting to empty-scope for non-superadmin callers.
    """
    # Superadmins and platform owners bypass brand scoping entirely
    if user.get("is_superadmin"):
        return None

    env = getattr(request.state, "environment", None)
    env_id = env.id if env is not None else None

    from app.models.postgres.user_brand_role_models import UserBrandRole
    import uuid as _uuid

    try:
        user_uuid = _uuid.UUID(user["sub"])
    except (KeyError, ValueError):
        return []

    stmt = select(UserBrandRole.brand_id).where(
        UserBrandRole.user_id == user_uuid,
    )
    if env_id is not None:
        stmt = stmt.where(UserBrandRole.environment_id == env_id)
    else:
        # No resolved environment — deny access for non-superadmin callers
        return []

    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [str(bid) for bid in rows]
