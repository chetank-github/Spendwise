from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models import Expense, User
from app.models.enums import ExpenseStatus, UserRole


def visible_expenses_query(user: User) -> Select:
    """Who can see what:
    - employee: only their own expenses
    - manager:  their own + everyone in their team
    - finance:  everything
    """
    query = select(Expense)
    if user.role == UserRole.finance:
        return query
    if user.role == UserRole.manager and user.team_id is not None:
        team_member_ids = select(User.id).where(User.team_id == user.team_id)
        return query.where(Expense.owner_id.in_(team_member_ids))
    return query.where(Expense.owner_id == user.id)


def get_visible_expense(db: Session, user: User, expense_id: int) -> Expense:
    expense = db.scalar(visible_expenses_query(user).where(Expense.id == expense_id))
    if expense is None:
        # 404 (not 403) so users cannot discover other people's expense IDs
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    return expense


def get_own_editable_expense(db: Session, user: User, expense_id: int) -> Expense:
    expense = get_visible_expense(db, user, expense_id)
    if expense.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the owner can change this expense")
    if expense.status not in (ExpenseStatus.draft, ExpenseStatus.rejected):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"Cannot change an expense that is {expense.status.value}")
    return expense