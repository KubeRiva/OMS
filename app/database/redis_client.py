import redis.asyncio as aioredis
from typing import Optional, AsyncGenerator
from app.config import settings
import logging

logger = logging.getLogger(__name__)

redis_pool: Optional[aioredis.ConnectionPool] = None


async def init_redis():
    global redis_pool
    redis_pool = aioredis.ConnectionPool.from_url(
        settings.REDIS_URL,
        max_connections=50,
        decode_responses=True,
    )
    # Verify connection
    client = aioredis.Redis(connection_pool=redis_pool)
    await client.ping()
    await client.aclose()
    logger.info("Redis connection pool initialized")


async def close_redis():
    global redis_pool
    if redis_pool:
        await redis_pool.disconnect()
        logger.info("Redis connection pool closed")


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    if redis_pool is None:
        raise RuntimeError("Redis pool not initialized. Call init_redis() first.")
    client = aioredis.Redis(connection_pool=redis_pool)
    try:
        yield client
    finally:
        await client.aclose()


def get_redis_client() -> Optional[aioredis.Redis]:
    """Return a Redis client directly (caller is responsible for aclose). Returns None if not initialized."""
    if redis_pool is None:
        return None
    return aioredis.Redis(connection_pool=redis_pool)


def get_redis_sync():
    """Synchronous Redis client for Celery tasks."""
    import redis
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


# Cache helpers
async def cache_get(key: str, redis_client: aioredis.Redis) -> Optional[str]:
    return await redis_client.get(key)


async def cache_set(key: str, value: str, ttl: int, redis_client: aioredis.Redis):
    await redis_client.setex(key, ttl, value)


async def cache_delete(key: str, redis_client: aioredis.Redis):
    await redis_client.delete(key)


async def cache_delete_pattern(pattern: str, redis_client: aioredis.Redis):
    keys = await redis_client.keys(pattern)
    if keys:
        await redis_client.delete(*keys)
