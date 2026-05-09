"""
Control-plane models: organizations, environments, user_environment_roles.
All three tables live in oms_db alongside users/user_groups.
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.postgres import Base


class TenantMode(str, enum.Enum):
    B2C_ONLY = "B2C_ONLY"   # retail-only; B2B endpoints and UI hidden
    B2B_ONLY = "B2B_ONLY"   # wholesale/contract only; B2C creation blocked
    HYBRID   = "HYBRID"     # both modes active (default)


class EnvironmentType(str, enum.Enum):
    DEV = "DEV"
    QA = "QA"
    STAGING = "STAGING"
    PROD = "PROD"


class EnvironmentStatus(str, enum.Enum):
    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class EnvironmentRole(str, enum.Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"
    VIEWER = "VIEWER"


class OrgRole(str, enum.Enum):
    ORG_OWNER = "ORG_OWNER"
    ORG_ADMIN = "ORG_ADMIN"
    ORG_MEMBER = "ORG_MEMBER"


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    slug = Column(String(80), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    tenant_mode = Column(String(20), default=TenantMode.HYBRID.value, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    environments = relationship("Environment", back_populates="organization", cascade="all, delete-orphan")
    org_member_roles = relationship("UserOrganizationRole", back_populates="organization", cascade="all, delete-orphan", foreign_keys="UserOrganizationRole.organization_id")

    def __repr__(self) -> str:
        return f"<Organization {self.slug}>"


class Environment(Base):
    __tablename__ = "environments"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_env_org_slug"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    slug = Column(String(80), nullable=False)
    env_type = Column(Enum(EnvironmentType), nullable=False, default=EnvironmentType.DEV)
    status = Column(Enum(EnvironmentStatus), nullable=False, default=EnvironmentStatus.PROVISIONING)

    # Data-plane connection info (NULL = same cluster as control plane)
    db_name = Column(String(200), unique=True, nullable=False)
    mongo_events_db = Column(String(200), nullable=False)
    mongo_ai_db = Column(String(200), nullable=False)
    es_index_prefix = Column(String(200), nullable=False)

    # Optional per-cluster overrides (NULL = inherit from settings)
    pg_host = Column(String(255), nullable=True)
    pg_port = Column(String(10), nullable=True)
    pg_user = Column(String(100), nullable=True)
    pg_password = Column(String(255), nullable=True)

    # URL of the deployed pod for this environment (used by frontend switcher to redirect)
    base_url = Column(String(500), nullable=True)

    is_default = Column(Boolean, default=False, nullable=False)
    provisioned_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    organization = relationship("Organization", back_populates="environments")
    member_roles = relationship("UserEnvironmentRole", back_populates="environment", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Environment {self.db_name} ({self.status.value})>"


class UserEnvironmentRole(Base):
    __tablename__ = "user_environment_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "environment_id", name="uq_user_env"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    environment_id = Column(UUID(as_uuid=True), ForeignKey("environments.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(Enum(EnvironmentRole), nullable=False, default=EnvironmentRole.MEMBER)
    granted_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    environment = relationship("Environment", back_populates="member_roles")

    def __repr__(self) -> str:
        return f"<UserEnvironmentRole user={self.user_id} env={self.environment_id} role={self.role.value}>"


class UserOrganizationRole(Base):
    """Per-org role for a user — grants access to manage/view all environments in an org."""
    __tablename__ = "user_organization_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="uq_user_org"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(Enum(OrgRole), nullable=False, default=OrgRole.ORG_MEMBER)
    granted_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    organization = relationship("Organization", back_populates="org_member_roles", foreign_keys=[organization_id])

    def __repr__(self) -> str:
        return f"<UserOrganizationRole user={self.user_id} org={self.organization_id} role={self.role.value}>"
