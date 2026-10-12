from datetime import date
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AuditLog, Budget, Expense, User
from app.models.enums import ExpenseStatus, UserRole
from app.services import fraud_checks

RECEIPT_REQUIRED_ABOVE = Decimal("500")          # company rule: receipts needed above ₹500
COUNTED_STATUSES = (ExpenseStatus.submitted, ExpenseStatus.approved, ExpenseStatus.reimbursed)

# Allowed status changes: action -> (statuses it can start from, status it moves to)
TRANSITIONS = {
    "submit":    ((ExpenseStatus.draft, ExpenseStatus.rejected), ExpenseStatus.submitted),
    "approve":   ((ExpenseStatus.submitted,), ExpenseStatus.approved),
    "reject":    ((ExpenseStatus.submitted,), ExpenseStatus.rejected),
    "reimburse": ((ExpenseStatus.approved,), ExpenseStatus.reimbursed),
}


def month_range(d: date) -> tuple[date, date]:
    start = d.replace(day=1)
    end = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return start, end


def _transition(db: Session, expense: Expense, actor: User, action: str, comment: str | None = None) -> Expense:
    allowed_from, to_status = TRANSITIONS[action]
    if expense.status not in allowed_from:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"Cannot {action} an expense that is {expense.status.value}")
    old = expense.status
    expense.status = to_status
    db.add(AuditLog(expense_id=expense.id, actor_id=actor.id, action=action,
                    from_status=old.value, to_status=to_status.value, comment=comment))
    db.commit()
    db.refresh(expense)
    return expense


def check_policies(db: Session, expense: Expense, owner: User) -> list[str]:
    """Return human-readable warnings; does not block submission."""
    flags: list[str] = []
    if owner.team_id is None:
        return flags
    budget = db.scalar(select(Budget).where(Budget.team_id == owner.team_id,
                                            Budget.category == expense.category))
    if budget is None:
        return flags

    if budget.per_claim_limit is not None and expense.amount > budget.per_claim_limit:
        flags.append(f"Amount {expense.amount} exceeds the per-claim limit of {budget.per_claim_limit} "
                     f"for {expense.category.value}")

    start, end = month_range(expense.expense_date)
    team_member_ids = select(User.id).where(User.team_id == owner.team_id)
    already_spent = db.scalar(
        select(func.coalesce(func.sum(Expense.amount), 0)).where(
            Expense.owner_id.in_(team_member_ids),
            Expense.category == expense.category,
            Expense.status.in_(COUNTED_STATUSES),
            Expense.expense_date >= start, Expense.expense_date < end,
            Expense.id != expense.id,
        )
    )
    projected = Decimal(already_spent) + expense.amount
    if projected > budget.monthly_limit:
        flags.append(f"Team {expense.category.value} budget exceeded: {projected} of "
                     f"{budget.monthly_limit} for {start:%B %Y}")
    return flags


def submit(db: Session, expense: Expense, actor: User) -> Expense:
    if expense.owner_id != actor.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the owner can submit")
    if expense.amount > RECEIPT_REQUIRED_ABOVE and not expense.receipt_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"A receipt is required for expenses above {RECEIPT_REQUIRED_ABOVE}")
    expense.receipt_hash = fraud_checks.file_hash(expense.receipt_path)
    flags = check_policies(db, expense, actor)
    flags += fraud_checks.duplicate_flags(db, expense)
    flags += fraud_checks.unusual_amount_flags(db, expense, actor)
    if expense.ai_extracted and (expense.ai_confidence or 0) < settings.ai_min_confidence:
        flags.append("Filled in by AI with low confidence: verify against the receipt")
    expense.policy_flags = flags or None
    return _transition(db, expense, actor, "submit")


def ensure_can_review(db: Session, expense: Expense, reviewer: User) -> None:
    if expense.owner_id == reviewer.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot approve your own expense")
    if reviewer.role == UserRole.finance:
        return
    owner = db.get(User, expense.owner_id)
    if reviewer.role == UserRole.manager and reviewer.team_id is not None and owner.team_id == reviewer.team_id:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                        detail="Only the owner's team manager or finance can review this expense")


def approve(db: Session, expense: Expense, reviewer: User, comment: str | None) -> Expense:
    ensure_can_review(db, expense, reviewer)
    return _transition(db, expense, reviewer, "approve", comment)


def reject(db: Session, expense: Expense, reviewer: User, comment: str) -> Expense:
    ensure_can_review(db, expense, reviewer)
    return _transition(db, expense, reviewer, "reject", comment)


def reimburse(db: Session, expense: Expense, actor: User, comment: str | None) -> Expense:
    if actor.role != UserRole.finance:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only finance can mark as reimbursed")
    return _transition(db, expense, actor, "reimburse", comment)
