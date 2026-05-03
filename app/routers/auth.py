import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database.postgres import get_db
from app.models.postgres.auth_models import User
from app.core.security import create_access_token, verify_password
from app.schemas.auth import LoginRequest, TokenResponse, UserInfo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")  # Rate limit: 5 attempts per minute per IP
async def login(request: Request, response: Response, payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate a user and return a JWT access token."""
    client_ip = request.client.host
    result = await db.execute(
        select(User)
        .options(selectinload(User.group))
        .where(User.email == payload.email.lower())
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.hashed_password):
        logger.warning(f"Failed login attempt for {payload.email} from {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    platform_role = user.effective_platform_role
    is_superadmin = platform_role in ("SUPERADMIN", "PLATFORM_OWNER")

    permissions: list[str] = []
    if is_superadmin:
        permissions = ["*"]  # superadmin has all permissions
    elif user.group and user.group.permissions:
        permissions = user.group.permissions

    token_data = {
        "sub": str(user.id),
        "email": user.email,
        "full_name": user.full_name or "",
        "is_superadmin": is_superadmin,
        "platform_role": platform_role,
        "permissions": permissions,
    }
    access_token = create_access_token(token_data)

    user_info = UserInfo(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        is_superadmin=is_superadmin,
        platform_role=platform_role,
        permissions=permissions,
    )

    logger.info(f"User {user.email} logged in successfully")

    # Set httpOnly cookie so the browser sends the JWT automatically without
    # exposing it to JavaScript (mitigates XSS token theft).
    is_production = settings.ENVIRONMENT == "production"
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="strict",
        secure=is_production,  # Secure flag only in production (requires HTTPS)
        path="/",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )

    return TokenResponse(access_token=access_token, user=user_info)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response):
    """Revoke the current JWT by adding it to the Redis blocklist and clear the auth cookie."""
    from app.core.security import revoke_token
    # Accept token from Authorization header (Bearer) or from the httpOnly cookie
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""
    if not token:
        token = request.cookies.get("access_token", "")
    if token:
        await revoke_token(token)
    # Clear the httpOnly auth cookie regardless of whether revocation succeeded
    response.delete_cookie(key="access_token", path="/")


@router.get("/me", response_model=UserInfo)
async def get_me(request: Request):
    """Return the currently authenticated user's info from the JWT."""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return UserInfo(
        id=user["sub"],
        email=user["email"],
        full_name=user.get("full_name", ""),
        is_superadmin=user.get("is_superadmin", False),
        platform_role=user.get("platform_role", "USER"),
        permissions=user.get("permissions", []),
    )
