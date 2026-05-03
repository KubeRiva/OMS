"""
Environments API — create and manage environments per organization.

Create flow:
  1. POST /environments  → inserts record (PROVISIONING), kicks off background DB creation
  2. Background: CREATE DATABASE + schema migration + MongoDB indexes → status → ACTIVE
  3. GET /environments/{id}/deployment-config  → returns docker-compose YAML to download
  4. User runs: docker-compose -f docker-compose.<slug>.yml up -d
  5. New pod starts, registers its base_url via PATCH /environments/{id}
  6. Switcher redirect works automatically
"""
import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.environment import get_control_db as get_db
from app.dependencies.auth import get_current_user, require_superadmin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/environments", tags=["Environments"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class EnvironmentCreate(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(..., min_length=1, max_length=80)
    env_type: str = Field(..., pattern="^(DEV|QA|STAGING|PROD)$")
    base_url: Optional[str] = Field(None, max_length=500)
    is_default: bool = False

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$", v):
            raise ValueError("Slug must be lowercase alphanumeric with optional hyphens")
        return v


class EnvironmentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    base_url: Optional[str] = Field(None, max_length=500)
    is_default: Optional[bool] = None


class MemberGrant(BaseModel):
    user_id: uuid.UUID
    role: str = Field(..., pattern="^(OWNER|ADMIN|MEMBER|VIEWER)$")


class EnvironmentResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str = ""
    name: str
    slug: str
    env_type: str
    status: str
    db_name: str
    mongo_events_db: str
    mongo_ai_db: str
    es_index_prefix: str
    base_url: Optional[str] = None
    is_default: bool
    provisioned_at: Optional[datetime]
    created_at: datetime
    member_count: int = 0

    model_config = {"from_attributes": True}


class MemberResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_email: str = ""
    user_name: str = ""
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_db_name(org_slug: str, env_slug: str) -> str:
    return f"oms_{org_slug}_{env_slug}"

def _build_mongo_events_db(org_slug: str, env_slug: str) -> str:
    return f"oms_events_{org_slug}_{env_slug}"

def _build_mongo_ai_db(org_slug: str, env_slug: str) -> str:
    return f"oms_ai_{org_slug}_{env_slug}"

def _build_es_prefix(org_slug: str, env_slug: str) -> str:
    return f"{org_slug}_{env_slug}"

def _derive_ports(db_name: str) -> tuple[int, int]:
    """Deterministic, collision-resistant port pair for a tenant environment."""
    h = int(hashlib.sha256(db_name.encode()).hexdigest()[:8], 16)
    api_port = 8002 + (h % 897)       # 8002 – 8898  (avoids 8001 = main API)
    frontend_port = 3002 + (h % 897)  # 3002 – 3898  (avoids 3001 = main frontend)
    return api_port, frontend_port


async def _assert_env_access(env, user: dict, db: AsyncSession, min_role: str = "VIEWER") -> None:
    if user.get("is_superadmin") or user.get("platform_role") == "PLATFORM_OWNER":
        return
    from app.models.postgres.org_models import UserEnvironmentRole
    user_id = uuid.UUID(user["sub"])
    result = await db.execute(
        select(UserEnvironmentRole)
        .where(UserEnvironmentRole.user_id == user_id)
        .where(UserEnvironmentRole.environment_id == env.id)
    )
    role_obj = result.scalar_one_or_none()
    if not role_obj:
        raise HTTPException(status_code=403, detail="Access denied")
    role_order = ["VIEWER", "MEMBER", "ADMIN", "OWNER"]
    if role_order.index(role_obj.role.value) < role_order.index(min_role):
        raise HTTPException(status_code=403, detail=f"Requires {min_role} role or above")


async def _env_response(env, db: AsyncSession) -> EnvironmentResponse:
    from app.models.postgres.org_models import Organization, UserEnvironmentRole
    org = await db.get(Organization, env.organization_id)
    count_result = await db.execute(
        select(func.count(UserEnvironmentRole.id)).where(UserEnvironmentRole.environment_id == env.id)
    )
    return EnvironmentResponse(
        id=env.id,
        organization_id=env.organization_id,
        organization_name=org.name if org else "",
        name=env.name,
        slug=env.slug,
        env_type=env.env_type.value,
        status=env.status.value,
        db_name=env.db_name,
        mongo_events_db=env.mongo_events_db,
        mongo_ai_db=env.mongo_ai_db,
        es_index_prefix=env.es_index_prefix,
        base_url=env.base_url,
        is_default=env.is_default,
        provisioned_at=env.provisioned_at,
        created_at=env.created_at,
        member_count=count_result.scalar_one(),
    )


# ---------------------------------------------------------------------------
# Database provisioning (background)
# ---------------------------------------------------------------------------

async def _provision_db(env_id: uuid.UUID) -> None:
    """
    Background task: create the Postgres database, run schema migrations,
    create MongoDB indexes, then mark the environment ACTIVE.
    """
    from app.database.postgres import async_session_factory, Base
    from app.models.postgres.org_models import Environment, EnvironmentStatus
    from app.config import settings

    async with async_session_factory() as session:
        env = await session.get(Environment, env_id)
        if env is None:
            return

        try:
            # 1. Create the Postgres database
            await _create_postgres_db(env.db_name, settings.DATABASE_URL)

            # 2. Run data-plane schema migrations
            await _create_schema(env.db_name, settings.DATABASE_URL, Base)

            # 3. MongoDB indexes (non-fatal)
            await _create_mongo_indexes(env.mongo_events_db, env.mongo_ai_db, settings.MONGODB_URL)

            # 4. Mark ACTIVE
            env.status = EnvironmentStatus.ACTIVE
            env.provisioned_at = datetime.now(timezone.utc)
            await session.commit()
            logger.info("Environment %s (%s) provisioned successfully", env.id, env.db_name)

        except Exception as exc:
            logger.error("Provisioning failed for env %s: %s", env_id, exc, exc_info=True)
            # Leave as PROVISIONING so the user can see it failed and retry


async def _create_postgres_db(db_name: str, database_url: str) -> None:
    import asyncpg  # type: ignore
    # Connect to the maintenance 'postgres' DB to issue CREATE DATABASE
    maint_url = re.sub(r"/[^/?]+(\?.*)?$", "/postgres", database_url.replace("postgresql+asyncpg://", "postgresql://"))
    conn = await asyncpg.connect(maint_url)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name)
        if not exists:
            safe = db_name.replace('"', "")
            await conn.execute(f'CREATE DATABASE "{safe}"')
            logger.info("Created Postgres database: %s", db_name)
        else:
            logger.info("Postgres database already exists: %s", db_name)
    finally:
        await conn.close()


async def _create_schema(db_name: str, database_url: str, Base) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.models.postgres import order_models, inventory_models, node_models  # noqa
    from app.models.postgres import sourcing_rule_models, connector_models, ai_models  # noqa

    _CONTROL_TABLES = frozenset(["users", "user_groups", "organizations", "environments", "user_environment_roles"])
    data_tables = [t for name, t in Base.metadata.tables.items() if name not in _CONTROL_TABLES]

    env_url = re.sub(r"/[^/?]+(\?.*)?$", f"/{db_name}", database_url)
    engine = create_async_engine(env_url, pool_size=2, max_overflow=3, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: Base.metadata.create_all(c, tables=data_tables, checkfirst=True)
            )
        logger.info("Schema migrated for database: %s (%d tables)", db_name, len(data_tables))
    finally:
        await engine.dispose()


async def _create_mongo_indexes(events_db: str, ai_db: str, mongo_url: str) -> None:
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=5000)
        edb = client[events_db]
        adb = client[ai_db]
        await edb.order_events.create_index([("order_id", 1)])
        await edb.order_events.create_index([("timestamp", -1)])
        await edb.order_events.create_index([("timestamp", 1)], expireAfterSeconds=30 * 86400, name="ttl")
        await adb.sourcing_outcomes.create_index([("node_id", 1), ("sourced_at", -1)])
        await adb.sourcing_patterns.create_index([("cluster_key", 1)], unique=True)
        await adb.node_performance_metrics.create_index([("node_id", 1), ("period_days", 1)], unique=True)
        client.close()
        logger.info("MongoDB indexes created for %s / %s", events_db, ai_db)
    except Exception as exc:
        logger.warning("MongoDB index creation skipped: %s", exc)


# ---------------------------------------------------------------------------
# Deployment config generator
# ---------------------------------------------------------------------------

def _generate_compose(env, org_slug: str) -> str:
    """Generate a docker-compose YAML for the tenant environment pod.

    Credentials are expressed as ${VAR} placeholders — operators must supply
    a .env file or inject them via their own secrets manager.  Live values are
    NEVER embedded in the generated YAML.
    """
    api_port, frontend_port = _derive_ports(env.db_name)
    frontend_url = f"http://localhost:{frontend_port}"
    safe_slug = re.sub(r"[^a-z0-9_]", "_", f"{org_slug}_{env.slug}")

    return f"""# Auto-generated deployment config for: {env.name} ({env.env_type.value})
# Organization: {org_slug}  |  Database: {env.db_name}
#
# IMPORTANT: Create a .env.{safe_slug} file with the following variables before
# running this compose file.  Do NOT commit that file to source control.
#
#   DATABASE_URL=postgresql+asyncpg://<user>:<password>@<host>:5432/{env.db_name}
#   SYNC_DATABASE_URL=postgresql+psycopg2://<user>:<password>@<host>:5432/{env.db_name}
#   CONTROL_DATABASE_URL=<control-plane DB URL>
#   MONGODB_URL=mongodb://<user>:<password>@<host>:27017/<db>?authSource=admin
#   REDIS_URL=redis://:<password>@<host>:6379/0
#   ELASTICSEARCH_URL=http://<host>:9200
#   SECRET_KEY=<random 64-char secret>
#
# Run from the OMS root directory:
#   docker-compose --env-file .env.{safe_slug} -f docker-compose.{safe_slug}.yml up -d --build
#
# Ports: API={api_port}  Frontend={frontend_port}
# ─────────────────────────────────────────────────────────────────────────────

version: "3.9"

services:
  api_{safe_slug}:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: oms_api_{safe_slug}
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
    environment:
      - TENANT_SLUG={org_slug}
      - ENVIRONMENT={env.env_type.value.lower()}
      - PLAN_TIER=STARTER
      - DATABASE_URL=${{DATABASE_URL}}
      - SYNC_DATABASE_URL=${{SYNC_DATABASE_URL}}
      - CONTROL_DATABASE_URL=${{CONTROL_DATABASE_URL}}
      - MONGODB_URL=${{MONGODB_URL}}
      - MONGODB_DB={env.mongo_events_db}
      - MONGODB_AI_DB={env.mongo_ai_db}
      - REDIS_URL=${{REDIS_URL}}
      - ELASTICSEARCH_URL=${{ELASTICSEARCH_URL}}
      - SECRET_KEY=${{SECRET_KEY}}
      - FRONTEND_URL={frontend_url}
      - ALLOWED_ORIGINS={frontend_url},http://localhost:{frontend_port}
    ports:
      - "{api_port}:8000"
    networks:
      - oms_default
    restart: unless-stopped

  frontend_{safe_slug}:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: oms_frontend_{safe_slug}
    environment:
      - API_HOST=oms_api_{safe_slug}
    ports:
      - "{frontend_port}:80"
    networks:
      - oms_default
    depends_on:
      - api_{safe_slug}
    restart: unless-stopped

networks:
  oms_default:
    external: true
    name: oms_default
"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=list[EnvironmentResponse])
async def list_environments(
    organization_id: Optional[uuid.UUID] = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    from app.models.postgres.org_models import Environment, UserEnvironmentRole

    if user.get("is_superadmin") or user.get("platform_role") == "PLATFORM_OWNER":
        q = select(Environment)
        if organization_id:
            q = q.where(Environment.organization_id == organization_id)
        result = await db.execute(q.order_by(Environment.created_at))
        envs = result.scalars().all()
    else:
        user_id = uuid.UUID(user["sub"])
        q = (
            select(Environment)
            .join(UserEnvironmentRole, UserEnvironmentRole.environment_id == Environment.id)
            .where(UserEnvironmentRole.user_id == user_id)
        )
        if organization_id:
            q = q.where(Environment.organization_id == organization_id)
        result = await db.execute(q.order_by(Environment.created_at))
        envs = result.scalars().all()

    return [await _env_response(e, db) for e in envs]


@router.post("", response_model=EnvironmentResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_environment(
    body: EnvironmentCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Register + provision a new environment.
    Returns 202 immediately; database creation runs in the background.
    Poll GET /environments/{id} until status=ACTIVE, then download the deployment config.
    """
    from app.models.postgres.org_models import (
        Organization, Environment, UserEnvironmentRole,
        EnvironmentType, EnvironmentStatus, EnvironmentRole,
    )

    org = await db.get(Organization, body.organization_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    if not (user.get("is_superadmin") or user.get("platform_role") == "PLATFORM_OWNER"):
        user_id = uuid.UUID(user["sub"])
        result = await db.execute(
            select(UserEnvironmentRole)
            .where(UserEnvironmentRole.user_id == user_id)
            .join(Environment, Environment.id == UserEnvironmentRole.environment_id)
            .where(Environment.organization_id == org.id)
        )
        existing_role = result.scalar_one_or_none()
        if not existing_role or existing_role.role.value not in ("OWNER", "ADMIN"):
            raise HTTPException(status_code=403, detail="OWNER or ADMIN role required")

    existing = await db.execute(
        select(Environment)
        .where(Environment.organization_id == org.id)
        .where(Environment.slug == body.slug)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Slug '{body.slug}' already exists in this organization")

    if body.is_default:
        await _clear_default(org.id, db)

    db_name = _build_db_name(org.slug, body.slug)
    dup = await db.execute(select(Environment).where(Environment.db_name == db_name))
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Database name '{db_name}' is already in use")

    env = Environment(
        organization_id=org.id,
        name=body.name,
        slug=body.slug,
        env_type=EnvironmentType(body.env_type),
        status=EnvironmentStatus.PROVISIONING,
        db_name=db_name,
        mongo_events_db=_build_mongo_events_db(org.slug, body.slug),
        mongo_ai_db=_build_mongo_ai_db(org.slug, body.slug),
        es_index_prefix=_build_es_prefix(org.slug, body.slug),
        base_url=body.base_url,
        is_default=body.is_default,
    )
    db.add(env)
    await db.flush()

    creator_id = uuid.UUID(user["sub"])
    db.add(UserEnvironmentRole(
        user_id=creator_id,
        environment_id=env.id,
        role=EnvironmentRole.OWNER,
        granted_by=creator_id,
    ))
    await db.flush()

    # Kick off DB creation in the background
    background_tasks.add_task(_provision_db, env.id)

    return await _env_response(env, db)


@router.get("/{env_id}/deployment-config")
async def get_deployment_config(
    env_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_superadmin),
):
    """
    Download a docker-compose YAML file to deploy this environment's pod locally.
    For Kubernetes, use the Helm values endpoint instead (future).
    """
    from app.models.postgres.org_models import Environment, Organization, EnvironmentStatus

    env = await db.get(Environment, env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")
    await _assert_env_access(env, user, db)

    if env.status == EnvironmentStatus.PROVISIONING:
        raise HTTPException(status_code=409, detail="Environment is still provisioning. Wait until status=ACTIVE.")

    org = await db.get(Organization, env.organization_id)
    compose_yaml = _generate_compose(env, org.slug if org else "default")
    api_port, frontend_port = _derive_ports(env.db_name)
    safe_slug = re.sub(r"[^a-z0-9_]", "_", f"{org.slug if org else 'default'}_{env.slug}")

    return Response(
        content=compose_yaml,
        media_type="application/x-yaml",
        headers={
            "Content-Disposition": f'attachment; filename="docker-compose.{safe_slug}.yml"',
            "X-Api-Port": str(api_port),
            "X-Frontend-Port": str(frontend_port),
        },
    )


async def _clear_default(org_id: uuid.UUID, db: AsyncSession) -> None:
    from app.models.postgres.org_models import Environment
    result = await db.execute(
        select(Environment)
        .where(Environment.organization_id == org_id)
        .where(Environment.is_default == True)  # noqa: E712
    )
    for env in result.scalars().all():
        env.is_default = False


@router.get("/{env_id}", response_model=EnvironmentResponse)
async def get_environment(
    env_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    from app.models.postgres.org_models import Environment
    env = await db.get(Environment, env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")
    await _assert_env_access(env, user, db)
    return await _env_response(env, db)


@router.delete("/{env_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_environment(
    env_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Remove an environment record from the control plane.
    Does NOT drop the database — stop the compose stack first, then delete here.
    The default production environment cannot be deleted.
    """
    from app.models.postgres.org_models import Environment, UserEnvironmentRole

    env = await db.get(Environment, env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    if env.is_default:
        raise HTTPException(status_code=400, detail="Cannot delete the default environment. Reassign the default first.")

    await _assert_env_access(env, user, db, min_role="OWNER")

    # Cascade: member roles are deleted by FK CASCADE, but clean up explicitly for clarity
    result = await db.execute(
        select(UserEnvironmentRole).where(UserEnvironmentRole.environment_id == env_id)
    )
    for role in result.scalars().all():
        await db.delete(role)

    await db.delete(env)


@router.patch("/{env_id}", response_model=EnvironmentResponse)
async def update_environment(
    env_id: uuid.UUID,
    body: EnvironmentUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    from app.models.postgres.org_models import Environment
    env = await db.get(Environment, env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")
    await _assert_env_access(env, user, db, min_role="ADMIN")

    if body.name is not None:
        env.name = body.name
    if body.base_url is not None:
        env.base_url = body.base_url
    if body.is_default is not None:
        if body.is_default:
            await _clear_default(env.organization_id, db)
        env.is_default = body.is_default

    await db.flush()
    return await _env_response(env, db)


# ---------------------------------------------------------------------------
# Member management
# ---------------------------------------------------------------------------

@router.get("/{env_id}/members", response_model=list[MemberResponse])
async def list_members(
    env_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    from app.models.postgres.org_models import Environment, UserEnvironmentRole
    from app.models.postgres.auth_models import User

    env = await db.get(Environment, env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")
    await _assert_env_access(env, user, db)

    result = await db.execute(
        select(UserEnvironmentRole, User)
        .join(User, User.id == UserEnvironmentRole.user_id)
        .where(UserEnvironmentRole.environment_id == env_id)
        .order_by(User.email)
    )
    return [
        MemberResponse(
            id=r.UserEnvironmentRole.id,
            user_id=r.UserEnvironmentRole.user_id,
            user_email=r.User.email,
            user_name=r.User.full_name or "",
            role=r.UserEnvironmentRole.role.value,
            created_at=r.UserEnvironmentRole.created_at,
        )
        for r in result.all()
    ]


@router.post("/{env_id}/members", response_model=MemberResponse, status_code=status.HTTP_201_CREATED)
async def grant_member(
    env_id: uuid.UUID,
    body: MemberGrant,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    from app.models.postgres.org_models import Environment, UserEnvironmentRole, EnvironmentRole
    from app.models.postgres.auth_models import User

    env = await db.get(Environment, env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")
    await _assert_env_access(env, user, db, min_role="ADMIN")

    target_user = await db.get(User, body.user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    result = await db.execute(
        select(UserEnvironmentRole)
        .where(UserEnvironmentRole.user_id == body.user_id)
        .where(UserEnvironmentRole.environment_id == env_id)
    )
    role_obj = result.scalar_one_or_none()
    granter_id = uuid.UUID(user["sub"])

    if role_obj:
        role_obj.role = EnvironmentRole(body.role)
    else:
        role_obj = UserEnvironmentRole(
            user_id=body.user_id,
            environment_id=env_id,
            role=EnvironmentRole(body.role),
            granted_by=granter_id,
        )
        db.add(role_obj)

    await db.flush()
    return MemberResponse(
        id=role_obj.id,
        user_id=role_obj.user_id,
        user_email=target_user.email,
        user_name=target_user.full_name or "",
        role=role_obj.role.value,
        created_at=role_obj.created_at,
    )


@router.delete("/{env_id}/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_member(
    env_id: uuid.UUID,
    member_user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    from app.models.postgres.org_models import Environment, UserEnvironmentRole

    env = await db.get(Environment, env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")
    await _assert_env_access(env, user, db, min_role="ADMIN")

    result = await db.execute(
        select(UserEnvironmentRole)
        .where(UserEnvironmentRole.user_id == member_user_id)
        .where(UserEnvironmentRole.environment_id == env_id)
    )
    role_obj = result.scalar_one_or_none()
    if not role_obj:
        raise HTTPException(status_code=404, detail="Member not found")

    await db.delete(role_obj)
