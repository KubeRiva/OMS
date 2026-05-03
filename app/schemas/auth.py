from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


# ── Auth ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str = Field(..., max_length=254)  # RFC 5321 max length; prevents oversized inputs
    password: str = Field(..., max_length=1024)


class UserInfo(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None
    is_superadmin: bool
    platform_role: str = "USER"
    permissions: list[str]

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserInfo


# ── Groups ────────────────────────────────────────────────────────────────────

class GroupCreate(BaseModel):
    name: str
    description: Optional[str] = None
    permissions: list[str] = []


class GroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permissions: Optional[list[str]] = None


class GroupResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    permissions: list[str]
    user_count: int = 0

    model_config = {"from_attributes": True}


# ── Users ─────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    password: str
    group_id: Optional[str] = None
    is_superadmin: bool = False

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    group_id: Optional[str] = None
    is_active: Optional[bool] = None
    is_superadmin: Optional[bool] = None
    password: Optional[str] = None


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None
    is_active: bool
    is_superadmin: bool
    platform_role: str = "USER"
    group_id: Optional[str] = None
    group_name: Optional[str] = None
    permissions: list[str] = []
    created_at: str

    model_config = {"from_attributes": True}


# ── Access / RBAC ─────────────────────────────────────────────────────────────

class OrgRoleEntry(BaseModel):
    org_id: str
    org_name: str
    org_slug: str
    role: str   # ORG_OWNER | ORG_ADMIN | ORG_MEMBER
    granted_at: str


class EnvRoleEntry(BaseModel):
    env_id: str
    env_name: str
    env_type: str   # DEV | QA | STAGING | PROD
    env_status: str
    org_id: str
    org_name: str
    role: str       # OWNER | ADMIN | MEMBER | VIEWER
    granted_at: str


class UserAccessResponse(BaseModel):
    user_id: str
    email: str
    full_name: Optional[str] = None
    platform_role: str
    group_id: Optional[str] = None
    group_name: Optional[str] = None
    org_roles: list[OrgRoleEntry] = []
    env_roles: list[EnvRoleEntry] = []


class OrgMemberResponse(BaseModel):
    user_id: str
    user_email: str
    user_name: Optional[str] = None
    role: str
    granted_at: str
