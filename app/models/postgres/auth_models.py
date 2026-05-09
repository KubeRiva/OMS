import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    JSON,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.postgres import Base


class PlatformRole:
    """Platform-level role constants (stored as VARCHAR in DB)."""
    PLATFORM_OWNER = "PLATFORM_OWNER"
    SUPERADMIN = "SUPERADMIN"
    USER = "USER"


class UserGroup(Base):
    __tablename__ = "user_groups"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(String(500), nullable=True)
    permissions = Column(JSON, default=list, nullable=False)  # ["orders:view", "orders:manage", ...]

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    users = relationship("User", back_populates="group")

    def __repr__(self) -> str:
        return f"<UserGroup {self.name}>"


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_superadmin = Column(Boolean, default=False, nullable=False)
    # platform_role: 'PLATFORM_OWNER' | 'SUPERADMIN' | 'USER'
    # Added via ALTER TABLE in init_db; takes precedence over is_superadmin.
    platform_role = Column(String(20), nullable=True)  # NULL → derive from is_superadmin
    group_id = Column(UUID(as_uuid=True), ForeignKey("user_groups.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    group = relationship("UserGroup", back_populates="users")

    @property
    def effective_platform_role(self) -> str:
        """Resolve role: explicit platform_role wins; fall back to is_superadmin."""
        if self.platform_role:
            return self.platform_role
        return PlatformRole.SUPERADMIN if self.is_superadmin else PlatformRole.USER

    def __repr__(self) -> str:
        return f"<User {self.email}>"
