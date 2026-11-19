import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class CreatedAtMixin:
    # Stored in UTC; the UI converts to the user's timezone.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TimestampMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


def enum_type(enum_cls: type, name: str) -> Enum:
    """Enum stored as VARCHAR with a CHECK constraint.

    Avoids native Postgres enum types, which clash when one enum is shared by several
    tables and are awkward to alter in migrations.
    """
    return Enum(enum_cls, name=name, native_enum=False, create_constraint=True, length=30)
