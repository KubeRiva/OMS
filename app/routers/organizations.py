"""
Organizations API — multi-tenant org management.
Superadmin: full access to all orgs.
Regular users: can see orgs where they hold a role.
"""
import re
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.environment import get_control_db as get_db
from app.dependencies.auth import get_current_user, require_superadmin, require_platform_owner

router = APIRouter(prefix="/organizations", tags=["Organizations"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,78}[a-z0-9]$")


class OrganizationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(..., min_length=2, max_length=80)
    description: Optional[str] = Field(None, max_length=2000)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError("Slug must be 2-80 lowercase alphanumeric characters or hyphens, start and end with alphanumeric")
        return v


class OrganizationUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    tenant_mode: Optional[str] = Field(None, pattern="^(B2C_ONLY|B2B_ONLY|HYBRID)$")


class OrganizationResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: Optional[str]
    is_active: bool
    tenant_mode: str = "HYBRID"
    environment_count: int = 0

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=list[OrganizationResponse])
async def list_organizations(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    List organizations.
    Superadmins see all; regular users see orgs where they have a role.
    """
    from app.models.postgres.org_models import Organization, Environment, UserEnvironmentRole

    if user.get("is_superadmin") or user.get("platform_role") == "PLATFORM_OWNER":
        result = await db.execute(select(Organization).order_by(Organization.name))
        orgs = result.scalars().all()
    else:
        user_id = uuid.UUID(user["sub"])
        # Orgs where the user has at least one role
        result = await db.execute(
            select(Organization)
            .join(Environment, Environment.organization_id == Organization.id)
            .join(UserEnvironmentRole, UserEnvironmentRole.environment_id == Environment.id)
            .where(UserEnvironmentRole.user_id == user_id)
            .distinct()
            .order_by(Organization.name)
        )
        orgs = result.scalars().all()

    # Attach environment counts
    response = []
    for org in orgs:
        count_result = await db.execute(
            select(func.count(Environment.id)).where(Environment.organization_id == org.id)
        )
        count = count_result.scalar_one()
        response.append(OrganizationResponse(
            id=org.id,
            name=org.name,
            slug=org.slug,
            description=org.description,
            is_active=org.is_active,
            tenant_mode=getattr(org, "tenant_mode", "HYBRID"),
            environment_count=count,
        ))
    return response


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    body: OrganizationCreate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_platform_owner),
):
    """Create a new organization (Platform Owner only)."""
    from app.models.postgres.org_models import Organization

    # Check slug uniqueness
    existing = await db.execute(select(Organization).where(Organization.slug == body.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Organization slug '{body.slug}' already exists")

    org = Organization(name=body.name, slug=body.slug, description=body.description)
    db.add(org)
    await db.flush()

    return OrganizationResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        description=org.description,
        is_active=org.is_active,
        tenant_mode=getattr(org, "tenant_mode", "HYBRID"),
        environment_count=0,
    )


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    from app.models.postgres.org_models import Organization, Environment, UserEnvironmentRole

    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    if not user.get("is_superadmin"):
        # Verify user has a role in this org
        user_id = uuid.UUID(user["sub"])
        role_check = await db.execute(
            select(UserEnvironmentRole)
            .join(Environment, Environment.id == UserEnvironmentRole.environment_id)
            .where(Environment.organization_id == org_id)
            .where(UserEnvironmentRole.user_id == user_id)
            .limit(1)
        )
        if not role_check.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="Access denied")

    count_result = await db.execute(
        select(func.count(Environment.id)).where(Environment.organization_id == org_id)
    )
    count = count_result.scalar_one()

    return OrganizationResponse(
        id=org.id, name=org.name, slug=org.slug,
        description=org.description, is_active=org.is_active,
        tenant_mode=getattr(org, "tenant_mode", "HYBRID"),
        environment_count=count,
    )


@router.patch("/{org_id}", response_model=OrganizationResponse)
async def update_organization(
    org_id: uuid.UUID,
    body: OrganizationUpdate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_platform_owner),
):
    from app.models.postgres.org_models import Organization, Environment

    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    if body.name is not None:
        org.name = body.name
    if body.description is not None:
        org.description = body.description
    if body.is_active is not None:
        org.is_active = body.is_active
    if body.tenant_mode is not None:
        org.tenant_mode = body.tenant_mode

    await db.flush()

    # Invalidate Redis env cache for every environment in this org so the new
    # tenant_mode is picked up within the next request (not after 60s TTL).
    if body.tenant_mode is not None:
        try:
            from app.database.redis_client import get_redis_client
            from sqlalchemy import select as _select
            redis = get_redis_client()
            if redis:
                env_result = await db.execute(
                    _select(Environment.id).where(Environment.organization_id == org_id)
                )
                for (env_id_val,) in env_result.all():
                    await redis.delete(f"env:{env_id_val}")
                await redis.aclose()
        except Exception:
            pass  # cache invalidation failure is non-fatal

    count_result = await db.execute(
        select(func.count(Environment.id)).where(Environment.organization_id == org_id)
    )
    count = count_result.scalar_one()

    return OrganizationResponse(
        id=org.id, name=org.name, slug=org.slug,
        description=org.description, is_active=org.is_active,
        tenant_mode=getattr(org, "tenant_mode", "HYBRID"),
        environment_count=count,
    )


# ---------------------------------------------------------------------------
# Org member management
# ---------------------------------------------------------------------------

class OrgMemberGrant(BaseModel):
    user_id: uuid.UUID
    role: str = Field(..., pattern="^(ORG_OWNER|ORG_ADMIN|ORG_MEMBER)$")


class OrgMemberResponse(BaseModel):
    user_id: str
    user_email: str
    user_name: Optional[str] = None
    role: str
    granted_at: str


@router.get("/{org_id}/members", response_model=list[OrgMemberResponse])
async def list_org_members(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    from app.models.postgres.org_models import Organization, UserOrganizationRole
    from app.models.postgres.auth_models import User

    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    if not (user.get("is_superadmin") or user.get("platform_role") == "PLATFORM_OWNER"):
        # Only members of the org may list members
        user_id = uuid.UUID(user["sub"])
        check = await db.execute(
            select(UserOrganizationRole)
            .where(UserOrganizationRole.organization_id == org_id)
            .where(UserOrganizationRole.user_id == user_id)
        )
        if not check.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="Access denied")

    result = await db.execute(
        select(UserOrganizationRole).where(UserOrganizationRole.organization_id == org_id)
    )
    rows = result.scalars().all()
    out = []
    for r in rows:
        u = await db.get(User, r.user_id)
        if u:
            out.append(OrgMemberResponse(
                user_id=str(u.id),
                user_email=u.email,
                user_name=u.full_name,
                role=r.role.value,
                granted_at=r.created_at.isoformat(),
            ))
    return out


@router.post("/{org_id}/members", response_model=OrgMemberResponse, status_code=200)
async def grant_org_member(
    org_id: uuid.UUID,
    body: OrgMemberGrant,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_superadmin),
):
    from app.models.postgres.org_models import Organization, UserOrganizationRole, OrgRole
    from app.models.postgres.auth_models import User

    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    u = await db.get(User, body.user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    existing = await db.execute(
        select(UserOrganizationRole)
        .where(UserOrganizationRole.organization_id == org_id)
        .where(UserOrganizationRole.user_id == body.user_id)
    )
    row = existing.scalar_one_or_none()
    if row:
        row.role = OrgRole(body.role)
    else:
        row = UserOrganizationRole(
            user_id=body.user_id,
            organization_id=org_id,
            role=OrgRole(body.role),
            granted_by=uuid.UUID(current_user["sub"]),
        )
        db.add(row)
    await db.flush()
    await db.refresh(row)
    return OrgMemberResponse(
        user_id=str(u.id),
        user_email=u.email,
        user_name=u.full_name,
        role=row.role.value,
        granted_at=row.created_at.isoformat(),
    )


@router.delete("/{org_id}/members/{user_id}", status_code=204)
async def revoke_org_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    from app.models.postgres.org_models import UserOrganizationRole

    result = await db.execute(
        select(UserOrganizationRole)
        .where(UserOrganizationRole.organization_id == org_id)
        .where(UserOrganizationRole.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row:
        await db.delete(row)
