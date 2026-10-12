from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum, Float, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ExpenseCategory, ExpenseStatus


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    category: Mapped[ExpenseCategory] = mapped_column(
        Enum(ExpenseCategory, native_enum=False, length=30), default=ExpenseCategory.other)
    vendor: Mapped[str | None] = mapped_column(String(200))
    expense_date: Mapped[date] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)
    receipt_path: Mapped[str | None] = mapped_column(String(500))
    receipt_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    policy_flags: Mapped[list[str] | None] = mapped_column(JSON)
    gstin: Mapped[str | None] = mapped_column(String(15))
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    ai_extracted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    ai_confidence: Mapped[float | None] = mapped_column(Float)
    ai_raw: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[ExpenseStatus] = mapped_column(
        Enum(ExpenseStatus, native_enum=False, length=20), default=ExpenseStatus.draft, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())

    owner: Mapped["User"] = relationship(back_populates="expenses")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="expense")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    expense_id: Mapped[int] = mapped_column(ForeignKey("expenses.id"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(50))
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str | None] = mapped_column(String(20))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    expense: Mapped[Expense] = relationship(back_populates="audit_logs")
