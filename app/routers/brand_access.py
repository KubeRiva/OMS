"""Brand access management — assign/remove brand-scoped roles for users."""
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.postgres import get_db
from app.dependencies.auth import require_superadmin

router = APIRouter(
    prefix="/brand-access",
    tags=["Brand Access"],
    dependencies=[Depends(require_superadmin)],
)

_VALID_ROLES = {"VIEWER", "OPERATOR", "ADMIN"}


# ---------------------------------------------------------------------------
# Inline Pydantic schemas
# ---------------------------------------------------------------------------

class UserBrandRoleCreate(BaseModel):
    user_id: uuid.UUID
    brand_id: uuid.UUID
    environment_id: uuid.UUID
    role: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        upper = v.upper()
        if upper not in _VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(_VALID_ROLES)}")
        return upper


class UserBrandRoleResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    brand_id: uuid.UUID
    environment_id: uuid.UUID
    role: str
    created_by_id: Optional[uuid.UUID] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/", response_model=List[UserBrandRoleResponse])
async def list_brand_access(
    user_id: Optional[uuid.UUID] = Query(default=None),
    brand_id: Optional[uuid.UUID] = Query(default=None),
    environment_id: Optional[uuid.UUID] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    List brand role assignments.

    All three query parameters are optional and can be combined.  When multiple
    filters are provided they are ANDed together — for example, passing both
    ``user_id`` and ``brand_id`` returns only the assignment for that specific
    user/brand pair in any environment.

    Roles:
    - ``VIEWER`` — read-only access to the brand's orders and inventory
    - ``OPERATOR`` — read access plus fulfillment actions (status updates, adjustments)
    - ``ADMIN`` — full brand-scoped access including brand configuration

    Superadmin users bypass brand filtering entirely regardless of any assignment.

    Requires superadmin authentication.
    """
    from app.models.postgres.user_brand_role_models import UserBrandRole

    stmt = select(UserBrandRole)
    if user_id is not None:
        stmt = stmt.where(UserBrandRole.user_id == user_id)
    if brand_id is not None:
        stmt = stmt.where(UserBrandRole.brand_id == brand_id)
    if environment_id is not None:
        stmt = stmt.where(UserBrandRole.environment_id == environment_id)

    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/", response_model=UserBrandRoleResponse, status_code=201)
async def assign_brand_access(
    payload: UserBrandRoleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_superadmin),
):
    """
    Assign a user to a brand within an environment.

    The ``(user_id, brand_id, environment_id)`` triplet must be unique — a user
    can hold only one role per brand per environment.  Returns HTTP 409 if the
    combination already exists.  To change a user's role, delete the existing
    assignment first and then create a new one.

    Referenced entities (user, brand, environment) are validated to exist before
    the assignment is written.

    The ``created_by_id`` field is populated automatically from the authenticated
    superadmin's JWT subject claim.

    Requires superadmin authentication.
    """
    from app.models.postgres.user_brand_role_models import UserBrandRole
    from app.models.postgres.auth_models import User
    from app.models.postgres.brand_models import Brand
    from app.models.postgres.org_models import Environment

    # Validate referenced entities exist
    if not await db.get(User, payload.user_id):
        raise HTTPException(status_code=404, detail="User not found")
    if not await db.get(Brand, payload.brand_id):
        raise HTTPException(status_code=404, detail="Brand not found")
    if not await db.get(Environment, payload.environment_id):
        raise HTTPException(status_code=404, detail="Environment not found")

    # Check for existing assignment
    existing = await db.execute(
        select(UserBrandRole).where(
            UserBrandRole.user_id == payload.user_id,
            UserBrandRole.brand_id == payload.brand_id,
            UserBrandRole.environment_id == payload.environment_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="User already has a brand role in this environment. "
                   "Delete the existing assignment first to change the role.",
        )

    import uuid as _uuid
    try:
        created_by_uuid = _uuid.UUID(current_user["sub"])
    except (KeyError, ValueError):
        created_by_uuid = None

    assignment = UserBrandRole(
        user_id=payload.user_id,
        brand_id=payload.brand_id,
        environment_id=payload.environment_id,
        role=payload.role,
        created_by_id=created_by_uuid,
    )
    db.add(assignment)
    await db.flush()
    await db.refresh(assignment)
    return assignment


@router.delete("/{assignment_id}", status_code=204)
async def remove_brand_access(
    assignment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_superadmin),
):
    """
    Remove a brand role assignment.

    The user immediately loses brand-scoped access for the affected brand and
    environment on the next request (no session cache to invalidate).  Returns
    HTTP 404 if the assignment ID does not exist.

    Requires superadmin authentication.
    """
    import logging as _logging
    _logger = _logging.getLogger(__name__)
    from app.models.postgres.user_brand_role_models import UserBrandRole

    assignment = await db.get(UserBrandRole, assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Brand access assignment not found")

    _logger.info(
        "brand_access: removed assignment %s (user=%s brand=%s env=%s) by %s",
        assignment_id,
        assignment.user_id,
        assignment.brand_id,
        assignment.environment_id,
        current_user.get("sub") or current_user.get("id"),
    )
    await db.delete(assignment)
    await db.flush()
