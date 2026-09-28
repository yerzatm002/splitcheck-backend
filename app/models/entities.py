from datetime import datetime
from decimal import Decimal
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="USER")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    receipts: Mapped[list["Receipt"]] = relationship(back_populates="creator")


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    store_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    receipt_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    total_amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    raw_ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_status: Mapped[str] = mapped_column(String(30), default="NOT_STARTED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    creator: Mapped[User] = relationship(back_populates="receipts")
    participants: Mapped[list["Participant"]] = relationship(back_populates="receipt", cascade="all, delete-orphan")
    items: Mapped[list["ReceiptItem"]] = relationship(back_populates="receipt", cascade="all, delete-orphan")


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(100))

    receipt: Mapped[Receipt] = relationship(back_populates="participants")
    splits: Mapped[list["ItemSplit"]] = relationship(back_populates="participant", cascade="all, delete-orphan")


class ReceiptItem(Base):
    __tablename__ = "receipt_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(250))
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=1)
    unit: Mapped[str] = mapped_column(String(20), default="pcs")
    unit_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_price_cents: Mapped[int] = mapped_column(Integer)
    ocr_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    receipt: Mapped[Receipt] = relationship(back_populates="items")
    splits: Mapped[list["ItemSplit"]] = relationship(back_populates="item", cascade="all, delete-orphan")


class ItemSplit(Base):
    __tablename__ = "item_splits"

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_item_id: Mapped[int] = mapped_column(ForeignKey("receipt_items.id", ondelete="CASCADE"), index=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id", ondelete="CASCADE"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    share: Mapped[Decimal] = mapped_column(Numeric(10, 6))

    item: Mapped[ReceiptItem] = relationship(back_populates="splits")
    participant: Mapped[Participant] = relationship(back_populates="splits")
