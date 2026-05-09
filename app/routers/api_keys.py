"""API key management endpoints — programmatic access without user sessions."""
import hashlib
import secrets
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.postgres import get_db
from app.dependencies.auth import require_superadmin
from app.models.postgres.api_key_models import ApiKey

router = APIRouter(tags=["API Keys"])


# ---------------------------------------------------------------------------
# Inline schemas
# ---------------------------------------------------------------------------

class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    scopes: List[str] = Field(default_factory=list)
    expires_at: Optional[datetime] = None


class ApiKeyCreatedResponse(BaseModel):
    id: uuid.UUID
    name: str
    # The raw key is returned ONCE ONLY on creation — never on subsequent reads
    key: str
    prefix: str
    scopes: List[str]
    expires_at: Optional[datetime]
    created_at: datetime


class ApiKeyResponse(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    scopes: List[str]
    last_used_at: Optional[datetime]
    is_active: bool
    expires_at: Optional[datetime]
    created_at: datetime
    owner_user_id: Optional[uuid.UUID]

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/api-keys", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_superadmin),
):
    """
    Create a new API key for programmatic access to the OMS API.

    The raw key (format ``kr_<43 url-safe chars>``) is returned in the ``key``
    field of this response **exactly once**.  It is immediately hashed with
    SHA-256 before storage and cannot be recovered afterwards.  Copy the key to
    a secure location before closing the response.

    The 12-character ``prefix`` field is stored in plaintext so that you can
    identify the key in list responses without knowing the full value.

    Requires superadmin authentication.

    **Scopes** (pass any subset):
    - ``orders:read`` / ``orders:write``
    - ``inventory:read`` / ``inventory:write``
    - ``sourcing_rules:read``
    - ``admin:read``

    **Authentication with the issued key:**

        curl http://localhost:8000/orders/ -H "X-API-Key: kr_<your-key>"
    """
    raw_key = "kr_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    owner_id: Optional[uuid.UUID] = None
    raw_uid = user.get("id")
    if raw_uid:
        try:
            owner_id = uuid.UUID(str(raw_uid))
        except ValueError:
            pass

    api_key = ApiKey(
        key_prefix=raw_key[:12],
        key_hash=key_hash,
        name=body.name,
        scopes=body.scopes,
        owner_user_id=owner_id,
        expires_at=body.expires_at,
        is_active=True,
    )
    db.add(api_key)
    await db.flush()  # populate id + created_at

    return ApiKeyCreatedResponse(
        id=api_key.id,
        name=api_key.name,
        key=raw_key,
        prefix=api_key.key_prefix,
        scopes=api_key.scopes,
        expires_at=api_key.expires_at,
        created_at=api_key.created_at,
    )


@router.get("/api-keys", response_model=List[ApiKeyResponse])
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_superadmin),
):
    """
    List all API keys ordered by creation date (newest first).

    The raw key and its SHA-256 hash are never included in list responses.
    Each item returns ``prefix``, ``scopes``, ``is_active``, ``last_used_at``,
    and ``expires_at`` — enough information to identify and audit a key without
    compromising it.

    Requires superadmin authentication.
    """
    rows = (await db.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))).scalars().all()
    return rows


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_superadmin),
):
    """
    Revoke an API key.

    Sets ``is_active=False`` on the key record.  Any subsequent request that
    presents this key will be rejected with HTTP 401.  The database row is
    intentionally retained so that audit logs referencing the key's ``prefix``
    remain traceable.

    This operation is **idempotent** — revoking an already-revoked key returns
    HTTP 204 without error.

    Requires superadmin authentication.
    """
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")

    if not api_key.is_active:
        # Idempotent — revoking an already-revoked key is a no-op
        return

    await db.execute(
        update(ApiKey)
        .where(ApiKey.id == key_id)
        .values(is_active=False)
    )
