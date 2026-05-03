"""
Utilities for environment-aware Celery workers.

Workers receive an optional environment_id string. If provided, they fetch
the Environment record from the control DB to get the correct data-plane
DATABASE_URL, MongoDB DB names, etc.

If environment_id is empty / None, falls back to the default production
settings (settings.DATABASE_URL, settings.MONGODB_DB, etc.) — preserving
full backward compatibility.
"""
import re
import logging

logger = logging.getLogger(__name__)


def get_env_db_url(environment_id: str = "") -> str:
    """Return the async DATABASE_URL for the given environment."""
    from app.config import settings
    if not environment_id:
        return settings.DATABASE_URL

    env_config = _fetch_env_config(environment_id)
    if env_config is None:
        logger.warning("env_utils: environment %s not found, using default DB", environment_id)
        return settings.DATABASE_URL

    return _build_db_url(env_config["db_name"], env_config)


def get_env_mongo_events_db(environment_id: str = "") -> str:
    from app.config import settings
    if not environment_id:
        return settings.MONGODB_DB

    env_config = _fetch_env_config(environment_id)
    if env_config is None:
        return settings.MONGODB_DB
    return env_config["mongo_events_db"]


def get_env_mongo_ai_db(environment_id: str = "") -> str:
    from app.config import settings
    if not environment_id:
        return settings.MONGODB_AI_DB

    env_config = _fetch_env_config(environment_id)
    if env_config is None:
        return settings.MONGODB_AI_DB
    return env_config["mongo_ai_db"]


def list_active_environment_ids() -> list[str]:
    """
    Return IDs of all ACTIVE environments (for fan-out beat tasks).
    Uses a synchronous DB connection (Celery beat context).
    """
    try:
        import sqlalchemy as sa
        from app.config import settings

        engine = sa.create_engine(settings.SYNC_DATABASE_URL, pool_pre_ping=True)
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text("SELECT id FROM environments WHERE status = 'ACTIVE'")
            ).fetchall()
        engine.dispose()
        return [str(r[0]) for r in rows]
    except Exception as exc:
        logger.warning("env_utils: failed to list active environments: %s", exc)
        return [""]  # Fall back to default env (empty string = settings.DATABASE_URL)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _fetch_env_config(environment_id: str) -> dict | None:
    """Fetch env record synchronously from control DB."""
    try:
        import sqlalchemy as sa
        from app.config import settings

        engine = sa.create_engine(settings.SYNC_DATABASE_URL, pool_pre_ping=True)
        with engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT db_name, mongo_events_db, mongo_ai_db, pg_host, pg_port, pg_user, pg_password "
                    "FROM environments WHERE id = :id"
                ),
                {"id": environment_id},
            ).fetchone()
        engine.dispose()
        if row is None:
            return None
        return {
            "db_name": row[0],
            "mongo_events_db": row[1],
            "mongo_ai_db": row[2],
            "pg_host": row[3],
            "pg_port": row[4],
            "pg_user": row[5],
            "pg_password": row[6],
        }
    except Exception as exc:
        logger.warning("env_utils: DB lookup for env %s failed: %s", environment_id, exc)
        return None


def _build_db_url(db_name: str, env_config: dict) -> str:
    from app.config import settings

    if env_config.get("pg_host"):
        host = env_config["pg_host"]
        port = env_config.get("pg_port") or "5432"
        user = env_config.get("pg_user") or "postgres"
        password = env_config.get("pg_password") or ""
        return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db_name}"

    # Same cluster — swap DB name only
    return re.sub(r"/[^/]+$", f"/{db_name}", settings.DATABASE_URL)
