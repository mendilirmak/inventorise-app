"""Database tables: Product, RestockLog, User.

Tables are created with `db.create_all()` at startup (see __init__.py).
That is fine for this project; a real product would use migrations
(Alembic) so the schema can change without dropping data.
"""

from datetime import UTC, datetime
from decimal import Decimal

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)


def utcnow():
    return datetime.now(UTC)


def as_utc(value):
    """SQLite drops the timezone when it stores a datetime; put UTC back."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class Product(db.Model):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    sku: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    # Numeric, not float: money must not suffer rounding errors.
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    stock_level: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    restocks: Mapped[list["RestockLog"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "sku": self.sku,
            "description": self.description,
            "price": float(self.price),
            "stock_level": self.stock_level,
            "created_at": as_utc(self.created_at).isoformat(),
            "updated_at": as_utc(self.updated_at).isoformat(),
        }


class RestockLog(db.Model):
    __tablename__ = "restock_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    quantity: Mapped[int]
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    product: Mapped[Product] = relationship(back_populates="restocks")

    def to_dict(self):
        return {
            "id": self.id,
            "product_id": self.product_id,
            "product_name": self.product.name,
            "quantity": self.quantity,
            "note": self.note,
            "created_at": as_utc(self.created_at).isoformat(),
        }


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    # Only hashes are stored: a leaked database reveals no passwords and no
    # usable API tokens.
    password_hash: Mapped[str] = mapped_column(String(255))
    api_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
