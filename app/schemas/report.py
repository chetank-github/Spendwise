from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ExpenseCategory


class BudgetIn(BaseModel):
    team_id: int
    category: ExpenseCategory
    monthly_limit: Decimal = Field(gt=0, decimal_places=2)
    per_claim_limit: Decimal | None = Field(default=None, gt=0, decimal_places=2)


class BudgetOut(BudgetIn):
    model_config = ConfigDict(from_attributes=True)

    id: int


class CategoryTotal(BaseModel):
    category: str
    total: Decimal
    count: int


class BudgetUsage(BaseModel):
    team_id: int
    team_name: str
    category: str
    monthly_limit: Decimal
    spent: Decimal
    used_pct: float


class MonthlySummary(BaseModel):
    month: str
    total_spent: Decimal
    expense_count: int
    by_category: list[CategoryTotal]
    by_status: dict[str, int]
    budget_usage: list[BudgetUsage]