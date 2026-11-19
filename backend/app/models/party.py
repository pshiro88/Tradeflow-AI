from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class Exporter(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "exporters"

    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))


class Buyer(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "buyers"

    buyer_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    country: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
