"""Tenant-mode guards — gate endpoints based on the organization's B2B/B2C mode."""
from fastapi import Depends, HTTPException, Request

from app.dependencies.auth import get_current_user  # ensures JWT is valid first


def require_b2b(request: Request, _: dict = Depends(get_current_user)) -> None:
    """Block the endpoint if the org is B2C_ONLY (B2B features not enabled)."""
    mode = getattr(request.state, "tenant_mode", "HYBRID")
    if mode == "B2C_ONLY":
        raise HTTPException(
            status_code=403,
            detail="B2B features are not enabled for this organization. "
                   "A Platform Owner can enable them under Platform Console → Organizations → Mode.",
        )


def require_b2c(request: Request, _: dict = Depends(get_current_user)) -> None:
    """Block the endpoint if the org is B2B_ONLY (B2C creation not permitted)."""
    mode = getattr(request.state, "tenant_mode", "HYBRID")
    if mode == "B2B_ONLY":
        raise HTTPException(
            status_code=403,
            detail="B2C order creation is not enabled for this organization. "
                   "A Platform Owner can enable it under Platform Console → Organizations → Mode.",
        )
