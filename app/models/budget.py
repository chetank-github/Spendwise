from decimal import Decimal

from sqlalchemy import Enum, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ExpenseCategory


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("team_id", "category", name="uq_budget_team_category"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    category: Mapped[ExpenseCategory] = mapped_column(Enum(ExpenseCategory, native_enum=False, length=30))
    monthly_limit: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    per_claim_limit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))