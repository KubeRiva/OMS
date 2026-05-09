"""API key model for programmatic access without user sessions."""
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database.postgres import Base


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # First 12 chars of the raw key — displayed in the UI so users can identify it
    key_prefix = Column(String(12), nullable=False)
    # SHA-256 hex digest of the full raw key — used for lookup; never returned to callers
    key_hash = Column(String(64), nullable=False, unique=True)
    name = Column(String(200), nullable=False)
    owner_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # e.g. ["orders:read", "orders:write", "inventory:read"]
    scopes = Column(JSON, default=list, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        # Fast lookup path: hash check short-circuits immediately on inactive keys
        Index("ix_api_keys_active_hash", "is_active", "key_hash"),
    )

    def __repr__(self) -> str:
        return f"<ApiKey {self.key_prefix}… name={self.name!r}>"
