"""
EnvironmentEngineRegistry — process-singleton that manages one AsyncEngine
per environment. Hot path is lock-free; engine creation uses double-checked
locking to avoid duplicate connections.

Also handles environment provisioning: creates a new PostgreSQL database,
runs create_all for data-plane tables, and initialises MongoDB indexes.
"""
import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

if TYPE_CHECKING:
    from app.models.postgres.org_models import Environment

logger = logging.getLogger(__name__)

# Tables that belong to the control plane (live in oms_db only, NOT provisioned
# into per-environment databases).
CONTROL_PLANE_TABLES = frozenset(
    ["users", "user_groups", "organizations", "environments", "user_environment_roles"]
)


class EnvironmentEngineRegistry:
    """
    Singleton registry: env_id (str) → AsyncEngine.
    All public coroutines are safe to call concurrently.
    """

    _instance: Optional["EnvironmentEngineRegistry"] = None

    def __init__(self) -> None:
        self._engines: Dict[str, AsyncEngine] = {}
        self._session_factories: Dict[str, async_sessionmaker] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Singleton accessor
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> "EnvironmentEngineRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Engine management
    # ------------------------------------------------------------------

    def get_engine(self, env_id: str) -> Optional[AsyncEngine]:
        """Lock-free hot path — returns None if engine not yet created."""
        return self._engines.get(env_id)

    def get_session_factory(self, env_id: str) -> Optional[async_sessionmaker]:
        return self._session_factories.get(env_id)

    async def get_or_create_engine(self, env: "Environment") -> AsyncEngine:
        """Return cached engine or create a new one (double-checked locking)."""
        env_id = str(env.id)
        if env_id in self._engines:
            return self._engines[env_id]

        async with self._lock:
            if env_id not in self._engines:
                url = self._build_db_url(env)
                engine = create_async_engine(
                    url,
                    pool_size=5,
                    max_overflow=10,
                    pool_pre_ping=True,
                    pool_recycle=3600,
                    echo=False,
                )
                self._engines[env_id] = engine
                self._session_factories[env_id] = async_sessionmaker(
                    engine,
                    class_=AsyncSession,
                    expire_on_commit=False,
                    autoflush=False,
                    autocommit=False,
                )
                logger.info("EnvironmentEngineRegistry: created engine for env %s (%s)", env_id, env.db_name)

        return self._engines[env_id]

    async def evict(self, env_id: str) -> None:
        """Dispose engine and remove from registry (called on ARCHIVED/SUSPENDED)."""
        async with self._lock:
            engine = self._engines.pop(env_id, None)
            self._session_factories.pop(env_id, None)
        if engine:
            await engine.dispose()
            logger.info("EnvironmentEngineRegistry: evicted engine for env %s", env_id)

    async def dispose_all(self) -> None:
        """Shutdown hook — dispose all managed engines."""
        async with self._lock:
            engines = list(self._engines.values())
            self._engines.clear()
            self._session_factories.clear()
        for engine in engines:
            await engine.dispose()

    # ------------------------------------------------------------------
    # Provisioning
    # ------------------------------------------------------------------

    async def provision_environment(
        self,
        env: "Environment",
        control_session: AsyncSession,
    ) -> None:
        """
        Provision a brand-new environment:
          1. CREATE DATABASE <db_name> via asyncpg raw connection
          2. Create a temporary engine for the new DB
          3. Run create_all for data-plane tables only
          4. Create MongoDB indexes
          5. Mark env ACTIVE in control DB

        Idempotent: repeated calls are safe.
        """
        from app.models.postgres.org_models import EnvironmentStatus

        logger.info("Provisioning environment %s (db=%s) …", env.id, env.db_name)

        try:
            # 1. Create the PostgreSQL database
            await self._create_postgres_database(env)

            # 2. Run schema migrations on the new DB
            await self._create_data_plane_schema(env)

            # 3. Create MongoDB indexes for both databases
            await self._create_mongo_indexes(env)

            # 4. Mark ACTIVE
            env.status = EnvironmentStatus.ACTIVE
            env.provisioned_at = datetime.now(timezone.utc)
            await control_session.flush()

            logger.info("Environment %s provisioned successfully.", env.id)

        except Exception as exc:
            logger.error("Failed to provision environment %s: %s", env.id, exc, exc_info=True)
            raise

    async def _create_postgres_database(self, env: "Environment") -> None:
        """Create the PostgreSQL database using a raw asyncpg connection."""
        import asyncpg  # type: ignore

        # Connect to the default 'postgres' maintenance DB to run CREATE DATABASE
        base_url = self._build_base_url(env)
        conn = await asyncpg.connect(base_url)
        try:
            # Check if already exists
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", env.db_name
            )
            if not exists:
                # asyncpg does not support $1 placeholders in DDL; use identifier quoting
                safe_name = env.db_name.replace('"', "")  # strip any quotes
                await conn.execute(f'CREATE DATABASE "{safe_name}"')
                logger.info("Created PostgreSQL database: %s", env.db_name)
            else:
                logger.info("PostgreSQL database already exists: %s", env.db_name)
        finally:
            await conn.close()

    async def _create_data_plane_schema(self, env: "Environment") -> None:
        """Create all data-plane tables in the new DB (skips control-plane tables)."""
        from app.database.postgres import Base
        from app.models.postgres import (  # noqa – ensure metadata is populated
            order_models,
            inventory_models,
            node_models,
            sourcing_rule_models,
            connector_models,
            ai_models,
            lifecycle_models,
        )

        # Collect only data-plane tables from Base.metadata
        data_plane_tables = [
            t for name, t in Base.metadata.tables.items()
            if name not in CONTROL_PLANE_TABLES
        ]

        engine = await self.get_or_create_engine(env)
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.create_all(
                    sync_conn,
                    tables=data_plane_tables,
                    checkfirst=True,
                )
            )
            # Additive migrations for tables that pre-date lifecycle support
            import sqlalchemy as sa
            await conn.execute(sa.text(
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS lifecycle_id UUID REFERENCES lifecycles(id)"
            ))
        logger.info(
            "Data-plane schema created for %s (%d tables)", env.db_name, len(data_plane_tables)
        )

    async def _create_mongo_indexes(self, env: "Environment") -> None:
        """Create MongoDB indexes for both the events and AI databases."""
        try:
            from motor.motor_asyncio import AsyncIOMotorClient

            client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=5000)
            try:
                events_db = client[env.mongo_events_db]
                ai_db = client[env.mongo_ai_db]

                # Events DB indexes
                await events_db.order_events.create_index([("order_id", 1)])
                await events_db.order_events.create_index([("timestamp", -1)])
                await events_db.order_events.create_index(
                    [("timestamp", 1)],
                    expireAfterSeconds=30 * 24 * 3600,
                    name="order_events_ttl",
                )

                # AI DB indexes
                await ai_db.sourcing_outcomes.create_index([("node_id", 1), ("sourced_at", -1)])
                await ai_db.sourcing_outcomes.create_index([("experiment_id", 1), ("strategy_used", 1)])
                await ai_db.sourcing_outcomes.create_index(
                    [("sourced_at", 1)],
                    expireAfterSeconds=90 * 24 * 3600,
                    name="sourcing_outcomes_ttl",
                )
                await ai_db.sourcing_patterns.create_index([("cluster_key", 1)], unique=True)
                await ai_db.sourcing_patterns.create_index(
                    [("computed_at", 1)],
                    expireAfterSeconds=180 * 24 * 3600,
                    name="sourcing_patterns_ttl",
                )
                await ai_db.node_performance_metrics.create_index(
                    [("node_id", 1), ("period_days", 1)], unique=True
                )

                logger.info("MongoDB indexes created for env %s", env.id)
            finally:
                client.close()
        except Exception as exc:
            logger.warning("Failed to create MongoDB indexes for env %s: %s", env.id, exc)
            # Non-fatal: indexes can be created later; don't fail the whole provisioning

    # ------------------------------------------------------------------
    # URL builders
    # ------------------------------------------------------------------

    def _build_db_url(self, env: "Environment") -> str:
        """Build the async database URL for an environment's data-plane DB."""
        if env.pg_host:
            # Per-environment cluster
            host = env.pg_host
            port = env.pg_port or "5432"
            user = env.pg_user or "postgres"
            password = env.pg_password or ""
            return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{env.db_name}"

        # Same cluster as control plane — swap DB name only
        base = settings.DATABASE_URL  # postgresql+asyncpg://user:pass@host:port/oms_db
        # Replace the last path segment (DB name) with env.db_name
        return re.sub(r"/[^/]+$", f"/{env.db_name}", base)

    def _build_base_url(self, env: "Environment") -> str:
        """Build asyncpg DSN pointing to the maintenance 'postgres' DB (for CREATE DATABASE)."""
        if env.pg_host:
            host = env.pg_host
            port = env.pg_port or "5432"
            user = env.pg_user or "postgres"
            password = env.pg_password or ""
            return f"postgresql://{user}:{password}@{host}:{port}/postgres"

        # Strip asyncpg dialect and swap DB name → postgres
        base = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
        return re.sub(r"/[^/]+$", "/postgres", base)


# Module-level singleton — import this everywhere
registry = EnvironmentEngineRegistry.get_instance()
