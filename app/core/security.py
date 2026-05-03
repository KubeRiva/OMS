import uuid as _uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt as _bcrypt
from fastapi import HTTPException, status
from jose import JWTError, jwt

from app.config import settings

ALGORITHM = "HS256"
_BLOCKLIST_PREFIX = "jwt:blocked:"


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return _bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


def create_access_token(data: dict[str, Any]) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode["exp"] = expire
    to_encode.setdefault("jti", str(_uuid.uuid4()))  # unique token ID for revocation
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


_REDIS_UNAVAILABLE = object()  # sentinel


async def _is_token_revoked(jti: str):
    """Return True if the token ID is on the Redis blocklist.

    Returns the sentinel _REDIS_UNAVAILABLE when Redis cannot be reached so
    callers can fail-closed (deny the request) rather than fail-open.
    """
    try:
        from app.database.redis_client import get_redis_client
        redis = get_redis_client()
        if redis is None:
            # Redis not configured at all — treat as unavailable (fail-closed)
            return _REDIS_UNAVAILABLE
        result = await redis.exists(f"{_BLOCKLIST_PREFIX}{jti}")
        await redis.aclose()
        return bool(result)
    except Exception:
        return _REDIS_UNAVAILABLE  # fail-closed: Redis outage → deny


async def revoke_token(token: str) -> None:
    """Add a token's jti to the Redis blocklist with TTL = remaining token lifetime."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        jti = payload.get("jti")
        exp = payload.get("exp")
        if not jti or not exp:
            return
        ttl = max(1, int(exp - datetime.now(timezone.utc).timestamp()))
        from app.database.redis_client import get_redis_client
        redis = get_redis_client()
        if redis is None:
            return
        await redis.setex(f"{_BLOCKLIST_PREFIX}{jti}", ttl, "1")
        await redis.aclose()
    except Exception:
        pass  # best-effort


def verify_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("sub") is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


async def verify_token_async(token: str) -> dict[str, Any]:
    """Async variant that additionally checks the Redis revocation blocklist
    and the per-user disable key set when an account is deactivated.

    Fails closed: if Redis is unavailable the request is denied with 401 to
    prevent revoked tokens from being accepted during an outage.
    """
    payload = verify_token(token)
    jti = payload.get("jti")
    if jti:
        revoked = await _is_token_revoked(jti)
        if revoked is _REDIS_UNAVAILABLE:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication service temporarily unavailable",
            )
        if revoked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
            )
    # Check per-user disable marker (set when account is deactivated via admin)
    sub = payload.get("sub")
    if sub:
        try:
            from app.database.redis_client import get_redis_client
            redis = get_redis_client()
            if redis is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication service temporarily unavailable",
                )
            disabled = await redis.exists(f"user:disabled:{sub}")
            await redis.aclose()
            if disabled:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Account has been disabled",
                )
        except HTTPException:
            raise
        except Exception:
            # Redis connection error — fail-closed
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication service temporarily unavailable",
            )
    return payload
