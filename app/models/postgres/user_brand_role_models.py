"""User-to-brand role assignments — scopes a user's data access to specific brands."""
import uuid

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database.postgres import Base


class UserBrandRole(Base):
    """Maps a user to a brand within a specific environment.

    When a user has one or more UserBrandRole rows for the active environment,
    their data access (orders, inventory, etc.) is restricted to those brands.
    Users with no rows are treated as having no brand access (empty scope).
    Superadmins and Platform Owners bypass this table entirely.

    Roles:
      VIEWER   — read-only access to brand data
      OPERATOR — can create/update orders and manage inventory for the brand
      ADMIN    — full brand-level management including configuration
    """

    __tablename__ = "user_brand_roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    brand_id = Column(
        UUID(as_uuid=True),
        ForeignKey("brands.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    environment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("environments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # VIEWER | OPERATOR | ADMIN
    role = Column(String(20), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "brand_id", "environment_id", name="uq_user_brand_env"),
        Index("ix_user_brand_roles_env", "environment_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<UserBrandRole user={self.user_id} brand={self.brand_id} "
            f"env={self.environment_id} role={self.role}>"
        )
