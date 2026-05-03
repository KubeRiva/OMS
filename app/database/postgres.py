from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from typing import AsyncGenerator

from fastapi import Request
from app.config import settings


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=40,
    pool_recycle=3600,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

# Control-plane engine: always points at the shared oms_db.
# For the main pod CONTROL_DATABASE_URL is blank → reuse the same engine.
# For tenant pods CONTROL_DATABASE_URL points back at oms_db.
_control_db_url = settings.CONTROL_DATABASE_URL or settings.DATABASE_URL
control_engine = create_async_engine(
    _control_db_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_recycle=3600,
)

control_session_factory = async_sessionmaker(
    control_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Return a session for the active environment's database.

    If the EnvironmentMiddleware has resolved an environment (request.state.environment),
    route to its engine via the EnvironmentEngineRegistry. Otherwise use the default engine.
    """
    env = getattr(request.state, "environment", None)
    factory = async_session_factory  # default

    if env is not None:
        try:
            from app.database.env_registry import registry
            env_engine = await registry.get_or_create_engine(env)
            factory = async_sessionmaker(
                env_engine, class_=AsyncSession, expire_on_commit=False,
                autoflush=False, autocommit=False,
            )
        except Exception:
            pass  # Fall through to default factory

    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_control_db() -> AsyncGenerator[AsyncSession, None]:
    """Return a session for the shared control-plane database (oms_db).

    On the main pod this is the same as get_db().
    On tenant pods CONTROL_DATABASE_URL redirects this to oms_db so that
    organizations, environments and users are always visible.
    """
    async with control_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Create all tables and apply additive schema migrations."""
    # Enum value additions must run outside a transaction block (PostgreSQL restriction).
    sa = __import__("sqlalchemy")
    async with engine.connect() as conn:
        for val in ["AI_ADAPTIVE", "AI_HYBRID"]:
            try:
                await conn.execute(sa.text(f"ALTER TYPE sourcingstrategy ADD VALUE IF NOT EXISTS '{val}'"))
            except Exception:
                pass
        await conn.commit()

    async with engine.begin() as conn:
        from app.models.postgres import connector_models, order_models, inventory_models, node_models, sourcing_rule_models, auth_models, ai_models, org_models, lifecycle_models  # noqa
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)
        # Additive migrations
        for ddl in [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS platform_role VARCHAR(20)",
            "ALTER TABLE environments ADD COLUMN IF NOT EXISTS base_url VARCHAR(500)",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS lifecycle_id UUID REFERENCES lifecycles(id)",
        ]:
            await conn.execute(sa.text(ddl))
        # Backfill: existing superadmins get SUPERADMIN role
        await conn.execute(
            sa.text(
                "UPDATE users SET platform_role = 'SUPERADMIN' "
                "WHERE is_superadmin = TRUE AND platform_role IS NULL"
            )
        )


async def drop_db():
    """Drop all tables (for testing/reset only)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
