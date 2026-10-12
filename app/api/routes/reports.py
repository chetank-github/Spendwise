from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import Budget, Expense, Team, User
from app.models.enums import UserRole
from app.schemas.report import BudgetUsage, CategoryTotal, MonthlySummary
from app.services.expense_access import visible_expenses_query
from app.services.workflow import COUNTED_STATUSES, month_range

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/monthly", response_model=MonthlySummary)
def monthly_summary(
    month: str = Query(pattern=r"^\d{4}-\d{2}$", examples=["2026-10"], description="YYYY-MM"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.manager, UserRole.finance)),
):
    try:
        start, end = month_range(date.fromisoformat(f"{month}-01"))
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid month")

    base = (visible_expenses_query(user)
            .where(Expense.expense_date >= start, Expense.expense_date < end).subquery())

    by_status = dict(db.execute(select(base.c.status, func.count()).group_by(base.c.status)).all())
    counted = select(base).where(base.c.status.in_([s.value for s in COUNTED_STATUSES])).subquery()
    cat_rows = db.execute(select(counted.c.category, func.sum(counted.c.amount), func.count())
                          .group_by(counted.c.category).order_by(func.sum(counted.c.amount).desc())).all()
    by_category = [CategoryTotal(category=getattr(c, "value", c), total=t, count=n) for c, t, n in cat_rows]
    total = sum((c.total for c in by_category), Decimal("0"))

    # Budget usage per team + category (finance: all teams, manager: own team)
    budget_query = select(Budget, Team.name).join(Team, Team.id == Budget.team_id)
    if user.role == UserRole.manager:
        budget_query = budget_query.where(Budget.team_id == user.team_id)
    usage = []
    for budget, team_name in db.execute(budget_query).all():
        team_member_ids = select(User.id).where(User.team_id == budget.team_id)
        spent = db.scalar(select(func.coalesce(func.sum(Expense.amount), 0)).where(
            Expense.owner_id.in_(team_member_ids), Expense.category == budget.category,
            Expense.status.in_(COUNTED_STATUSES), Expense.expense_date >= start, Expense.expense_date < end))
        spent = Decimal(spent)
        usage.append(BudgetUsage(team_id=budget.team_id, team_name=team_name, category=budget.category.value,
                                 monthly_limit=budget.monthly_limit, spent=spent,
                                 used_pct=round(float(spent / budget.monthly_limit * 100), 1)))

    return MonthlySummary(month=month, total_spent=total, expense_count=sum(c.count for c in by_category),
                          by_category=by_category,
                          by_status={getattr(k, "value", k): v for k, v in by_status.items()},
                          budget_usage=usage)