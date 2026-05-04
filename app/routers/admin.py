import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.postgres import get_db
from app.dependencies.auth import require_superadmin, require_platform_owner
from app.models.postgres.auth_models import User, UserGroup
from app.core.security import hash_password
from app.schemas.auth import (
    GroupCreate,
    GroupResponse,
    GroupUpdate,
    UserCreate,
    UserResponse,
    UserUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _user_to_response(user: User) -> UserResponse:
    platform_role = user.effective_platform_role
    is_superadmin = platform_role in ("SUPERADMIN", "PLATFORM_OWNER")

    permissions: list[str] = []
    if is_superadmin:
        permissions = ["*"]
    elif user.group and user.group.permissions:
        permissions = user.group.permissions

    return UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_superadmin=is_superadmin,
        platform_role=platform_role,
        group_id=str(user.group_id) if user.group_id else None,
        group_name=user.group.name if user.group else None,
        permissions=permissions,
        created_at=user.created_at.isoformat(),
    )


def _group_to_response(group: UserGroup, user_count: int = 0) -> GroupResponse:
    return GroupResponse(
        id=str(group.id),
        name=group.name,
        description=group.description,
        permissions=group.permissions or [],
        user_count=user_count,
    )


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    result = await db.execute(
        select(User).options(selectinload(User.group)).order_by(User.created_at.desc())
    )
    users = result.scalars().all()
    return [_user_to_response(u) for u in users]


@router.post("/users", response_model=UserResponse, status_code=201)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    # Check email uniqueness
    existing = await db.execute(select(User).where(User.email == payload.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already in use")

    # Validate group exists if provided
    group_uuid: Optional[UUID] = None
    if payload.group_id:
        try:
            group_uuid = UUID(payload.group_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid group_id format")
        grp = await db.get(UserGroup, group_uuid)
        if not grp:
            raise HTTPException(status_code=404, detail="Group not found")

    user = User(
        email=payload.email.lower(),
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        is_superadmin=payload.is_superadmin,
        platform_role="SUPERADMIN" if payload.is_superadmin else "USER",
        group_id=group_uuid,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    result = await db.execute(
        select(User).options(selectinload(User.group)).where(User.id == user.id)
    )
    user = result.scalar_one()
    logger.info(f"Admin created user {user.email}")
    return _user_to_response(user)


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    result = await db.execute(
        select(User).options(selectinload(User.group)).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.is_active is not None:
        if payload.is_active is False and user.is_active:
            # Write a user-level blocklist marker so existing tokens are rejected
            # immediately (TTL = max token lifetime so it self-cleans)
            try:
                from app.database.redis_client import get_redis_client
                from app.config import settings as _s
                redis = get_redis_client()
                if redis:
                    ttl = _s.ACCESS_TOKEN_EXPIRE_MINUTES * 60
                    await redis.setex(f"user:disabled:{user.id}", ttl, "1")
                    await redis.aclose()
            except Exception:
                pass
        user.is_active = payload.is_active
    if payload.is_superadmin is not None:
        user.is_superadmin = payload.is_superadmin
    if payload.password is not None:
        if len(payload.password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
        user.hashed_password = hash_password(payload.password)
    if payload.group_id is not None:
        if payload.group_id == "":
            user.group_id = None
        else:
            try:
                group_uuid = UUID(payload.group_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid group_id format")
            grp = await db.get(UserGroup, group_uuid)
            if not grp:
                raise HTTPException(status_code=404, detail="Group not found")
            user.group_id = group_uuid

    await db.flush()
    # Reload with group
    result = await db.execute(
        select(User).options(selectinload(User.group)).where(User.id == user_id)
    )
    user = result.scalar_one()
    return _user_to_response(user)


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_superadmin),
):
    if str(user_id) == current_user.get("sub"):
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await db.delete(user)
    logger.info(f"Admin deleted user {user.email}")


class PlatformRoleUpdate(BaseModel):
    platform_role: str

    @field_validator("platform_role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("PLATFORM_OWNER", "SUPERADMIN", "USER"):
            raise ValueError("platform_role must be PLATFORM_OWNER, SUPERADMIN, or USER")
        return v


@router.patch("/users/{user_id}/platform-role", response_model=UserResponse)
async def set_platform_role(
    user_id: UUID,
    payload: PlatformRoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_platform_owner),
):
    """Set a user's platform role. Only Platform Owners can do this."""
    result = await db.execute(
        select(User).options(selectinload(User.group)).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if str(user_id) == current_user.get("sub"):
        raise HTTPException(status_code=400, detail="Cannot change your own platform role")

    user.platform_role = payload.platform_role
    # Sync the legacy is_superadmin column
    user.is_superadmin = payload.platform_role in ("SUPERADMIN", "PLATFORM_OWNER")
    await db.flush()

    result = await db.execute(
        select(User).options(selectinload(User.group)).where(User.id == user_id)
    )
    user = result.scalar_one()
    logger.info(f"Platform Owner set {user.email} platform_role={payload.platform_role}")
    return _user_to_response(user)


# ── Groups ────────────────────────────────────────────────────────────────────

@router.get("/groups", response_model=list[GroupResponse])
async def list_groups(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    result = await db.execute(select(UserGroup).order_by(UserGroup.name))
    groups = result.scalars().all()

    # Count users per group
    count_result = await db.execute(
        select(User.group_id, func.count(User.id)).group_by(User.group_id)
    )
    counts = {str(row[0]): row[1] for row in count_result if row[0] is not None}

    return [_group_to_response(g, counts.get(str(g.id), 0)) for g in groups]


@router.post("/groups", response_model=GroupResponse, status_code=201)
async def create_group(
    payload: GroupCreate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    existing = await db.execute(select(UserGroup).where(UserGroup.name == payload.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Group name already in use")

    group = UserGroup(
        name=payload.name,
        description=payload.description,
        permissions=payload.permissions,
    )
    db.add(group)
    await db.flush()
    await db.refresh(group)
    logger.info(f"Admin created group {group.name}")
    return _group_to_response(group, 0)


@router.patch("/groups/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: UUID,
    payload: GroupUpdate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    group = await db.get(UserGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    if payload.name is not None:
        # Check uniqueness
        existing = await db.execute(
            select(UserGroup).where(UserGroup.name == payload.name, UserGroup.id != group_id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Group name already in use")
        group.name = payload.name
    if payload.description is not None:
        group.description = payload.description
    if payload.permissions is not None:
        group.permissions = payload.permissions

    await db.flush()

    # Count users
    count_result = await db.execute(
        select(func.count(User.id)).where(User.group_id == group_id)
    )
    user_count = count_result.scalar_one()
    return _group_to_response(group, user_count)


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(
    group_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    group = await db.get(UserGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # Prevent deletion if users are assigned
    count_result = await db.execute(
        select(func.count(User.id)).where(User.group_id == group_id)
    )
    user_count = count_result.scalar_one()
    if user_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete group with {user_count} assigned user(s). Reassign users first.",
        )

    await db.delete(group)
    logger.info(f"Admin deleted group {group.name}")


# ── User Access Management (org + env roles) ──────────────────────────────────

from app.schemas.auth import UserAccessResponse, OrgRoleEntry, EnvRoleEntry  # noqa: E402


async def _build_user_access(user_id: UUID, db: AsyncSession) -> UserAccessResponse:
    from app.models.postgres.org_models import (
        UserOrganizationRole, UserEnvironmentRole, Organization, Environment,
    )
    from sqlalchemy.orm import selectinload

    user = await db.execute(
        select(User).options(selectinload(User.group)).where(User.id == user_id)
    )
    user = user.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Org roles
    org_roles_res = await db.execute(
        select(UserOrganizationRole).where(UserOrganizationRole.user_id == user_id)
    )
    org_role_rows = org_roles_res.scalars().all()
    org_entries = []
    for r in org_role_rows:
        org = await db.get(Organization, r.organization_id)
        if org:
            org_entries.append(OrgRoleEntry(
                org_id=str(r.organization_id),
                org_name=org.name,
                org_slug=org.slug,
                role=r.role.value,
                granted_at=r.created_at.isoformat(),
            ))

    # Env roles
    env_roles_res = await db.execute(
        select(UserEnvironmentRole).where(UserEnvironmentRole.user_id == user_id)
    )
    env_role_rows = env_roles_res.scalars().all()
    env_entries = []
    for r in env_role_rows:
        env = await db.get(Environment, r.environment_id)
        if env:
            org = await db.get(Organization, env.organization_id)
            env_entries.append(EnvRoleEntry(
                env_id=str(r.environment_id),
                env_name=env.name,
                env_type=env.env_type.value,
                env_status=env.status.value,
                org_id=str(env.organization_id),
                org_name=org.name if org else "",
                role=r.role.value,
                granted_at=r.created_at.isoformat(),
            ))

    platform_role = user.effective_platform_role
    return UserAccessResponse(
        user_id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        platform_role=platform_role,
        group_id=str(user.group_id) if user.group_id else None,
        group_name=user.group.name if user.group else None,
        org_roles=org_entries,
        env_roles=env_entries,
    )


@router.get("/users/{user_id}/access", response_model=UserAccessResponse)
async def get_user_access(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    """Return the full org + environment role assignment for a user."""
    return await _build_user_access(user_id, db)


class OrgRoleGrant(BaseModel):
    org_id: UUID
    role: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("ORG_OWNER", "ORG_ADMIN", "ORG_MEMBER"):
            raise ValueError("role must be ORG_OWNER, ORG_ADMIN, or ORG_MEMBER")
        return v


@router.post("/users/{user_id}/org-roles", response_model=UserAccessResponse, status_code=200)
async def grant_org_role(
    user_id: UUID,
    payload: OrgRoleGrant,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_superadmin),
):
    """Grant (or update) an org-level role for a user."""
    from app.models.postgres.org_models import UserOrganizationRole, OrgRole, Organization

    if not await db.get(User, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    if not await db.get(Organization, payload.org_id):
        raise HTTPException(status_code=404, detail="Organization not found")

    existing = await db.execute(
        select(UserOrganizationRole)
        .where(UserOrganizationRole.user_id == user_id)
        .where(UserOrganizationRole.organization_id == payload.org_id)
    )
    row = existing.scalar_one_or_none()
    if row:
        row.role = OrgRole(payload.role)
    else:
        row = UserOrganizationRole(
            user_id=user_id,
            organization_id=payload.org_id,
            role=OrgRole(payload.role),
            granted_by=UUID(current_user["sub"]),
        )
        db.add(row)
    await db.flush()
    logger.info("Granted org role %s to user %s on org %s", payload.role, user_id, payload.org_id)
    return await _build_user_access(user_id, db)


@router.delete("/users/{user_id}/org-roles/{org_id}", response_model=UserAccessResponse)
async def revoke_org_role(
    user_id: UUID,
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    """Revoke an org-level role from a user."""
    from app.models.postgres.org_models import UserOrganizationRole

    result = await db.execute(
        select(UserOrganizationRole)
        .where(UserOrganizationRole.user_id == user_id)
        .where(UserOrganizationRole.organization_id == org_id)
    )
    row = result.scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.flush()
    return await _build_user_access(user_id, db)


class EnvRoleGrant(BaseModel):
    env_id: UUID
    role: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("OWNER", "ADMIN", "MEMBER", "VIEWER"):
            raise ValueError("role must be OWNER, ADMIN, MEMBER, or VIEWER")
        return v


@router.post("/users/{user_id}/env-roles", response_model=UserAccessResponse, status_code=200)
async def grant_env_role(
    user_id: UUID,
    payload: EnvRoleGrant,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_superadmin),
):
    """Grant (or update) an environment-level role for a user."""
    from app.models.postgres.org_models import UserEnvironmentRole, EnvironmentRole, Environment

    if not await db.get(User, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    if not await db.get(Environment, payload.env_id):
        raise HTTPException(status_code=404, detail="Environment not found")

    existing = await db.execute(
        select(UserEnvironmentRole)
        .where(UserEnvironmentRole.user_id == user_id)
        .where(UserEnvironmentRole.environment_id == payload.env_id)
    )
    row = existing.scalar_one_or_none()
    if row:
        row.role = EnvironmentRole(payload.role)
    else:
        row = UserEnvironmentRole(
            user_id=user_id,
            environment_id=payload.env_id,
            role=EnvironmentRole(payload.role),
            granted_by=UUID(current_user["sub"]),
        )
        db.add(row)
    await db.flush()
    logger.info("Granted env role %s to user %s on env %s", payload.role, user_id, payload.env_id)
    return await _build_user_access(user_id, db)


@router.delete("/users/{user_id}/env-roles/{env_id}", response_model=UserAccessResponse)
async def revoke_env_role(
    user_id: UUID,
    env_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    """Revoke an environment-level role from a user."""
    from app.models.postgres.org_models import UserEnvironmentRole

    result = await db.execute(
        select(UserEnvironmentRole)
        .where(UserEnvironmentRole.user_id == user_id)
        .where(UserEnvironmentRole.environment_id == env_id)
    )
    row = result.scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.flush()
    return await _build_user_access(user_id, db)
