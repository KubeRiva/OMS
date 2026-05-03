from fastapi import Depends, HTTPException, Request, status


async def get_current_user(request: Request) -> dict:
    """Extract the authenticated user from request state (set by auth middleware)."""
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user


async def require_superadmin(user: dict = Depends(get_current_user)) -> dict:
    """Require the current user to be a superadmin (SUPERADMIN or PLATFORM_OWNER)."""
    if not user.get("is_superadmin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


async def require_platform_owner(user: dict = Depends(get_current_user)) -> dict:
    """Require the current user to be a Platform Owner (exclusive top-tier role)."""
    if user.get("platform_role") != "PLATFORM_OWNER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform Owner access required",
        )
    return user
