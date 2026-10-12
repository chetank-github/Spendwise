from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import ExpenseCategory, ExpenseStatus


class ExpenseBase(BaseModel):
    amount: Decimal = Field(gt=0, le=10_000_000, decimal_places=2)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    category: ExpenseCategory = ExpenseCategory.other
    vendor: str | None = Field(default=None, max_length=200)
    expense_date: date
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("expense_date")
    @classmethod
    def not_in_future(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("expense_date cannot be in the future")
        return v

    @field_validator("currency")
    @classmethod
    def upper_currency(cls, v: str) -> str:
        return v.upper()


class ExpenseCreate(ExpenseBase):
    pass


class ExpenseUpdate(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0, le=10_000_000, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    category: ExpenseCategory | None = None
    vendor: str | None = Field(default=None, max_length=200)
    expense_date: date | None = None
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("expense_date")
    @classmethod
    def not_in_future(cls, v: date | None) -> date | None:
        if v is not None and v > date.today():
            raise ValueError("expense_date cannot be in the future")
        return v


class ExpenseOut(ExpenseBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    status: ExpenseStatus
    has_receipt: bool
    policy_flags: list[str] = []
    gstin: str | None = None
    tax_amount: Decimal | None = None
    ai_extracted: bool = False
    ai_confidence: float | None = None
    created_at: datetime
    updated_at: datetime

    # Skip the "no future dates" rule when reading existing rows from the database
    @field_validator("expense_date")
    @classmethod
    def not_in_future(cls, v: date) -> date:
        return v


class ExpenseList(BaseModel):
    items: list[ExpenseOut]
    total: int
    page: int
    page_size: int


class ActionComment(BaseModel):
    comment: str | None = Field(default=None, max_length=1000)


class RejectRequest(BaseModel):
    comment: str = Field(min_length=3, max_length=1000, description="Reason for rejection")


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_id: int
    action: str
    from_status: str | None
    to_status: str | None
    comment: str | None
    created_at: datetime
