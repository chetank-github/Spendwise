"""Duplicate and unusual-amount detection, run when an expense is submitted."""
import hashlib
import re
import statistics
from datetime import timedelta
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Expense, User
from app.models.enums import ExpenseStatus

ACTIVE_STATUSES = (ExpenseStatus.submitted, ExpenseStatus.approved, ExpenseStatus.reimbursed)
UNUSUAL_RATIO = 3          # flag if amount > 3x the usual (median) amount
MIN_HISTORY = 5            # need at least 5 past expenses to judge "usual"
HISTORY_DAYS = 180


def file_hash(path: str | None) -> str | None:
    if not path or not Path(path).exists():
        return None
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def duplicate_flags(db: Session, expense: Expense) -> list[str]:
    flags: list[str] = []

    # 1) Exact same receipt image already claimed (by anyone)
    if expense.receipt_hash:
        same_image = db.scalars(select(Expense).where(
            Expense.receipt_hash == expense.receipt_hash, Expense.id != expense.id,
            Expense.status.in_(ACTIVE_STATUSES))).all()
        for other in same_image:
            who = "you" if other.owner_id == expense.owner_id else "another employee"
            flags.append(f"Same receipt image was already claimed by {who} in expense #{other.id}")

    # 2) Same person, same amount, same date, similar vendor
    candidates = db.scalars(select(Expense).where(
        Expense.owner_id == expense.owner_id, Expense.id != expense.id,
        Expense.amount == expense.amount, Expense.expense_date == expense.expense_date,
        Expense.status.in_(ACTIVE_STATUSES))).all()
    already = {f.split("#")[-1] for f in flags}
    for other in candidates:
        if str(other.id) in already:
            continue
        a, b = _norm(expense.vendor), _norm(other.vendor)
        if not a or not b or SequenceMatcher(None, a, b).ratio() >= 0.8:
            flags.append(f"Possible duplicate of expense #{other.id} (same amount, date and vendor)")
    return flags


def unusual_amount_flags(db: Session, expense: Expense, owner: User) -> list[str]:
    since = expense.expense_date - timedelta(days=HISTORY_DAYS)
    base = select(Expense.amount).where(
        Expense.category == expense.category, Expense.id != expense.id,
        Expense.status.in_(ACTIVE_STATUSES), Expense.expense_date >= since)

    history = db.scalars(base.where(Expense.owner_id == owner.id)).all()
    scope = "your"
    if len(history) < MIN_HISTORY and owner.team_id is not None:
        team_ids = select(User.id).where(User.team_id == owner.team_id)
        history = db.scalars(base.where(Expense.owner_id.in_(team_ids))).all()
        scope = "your team's"
    if len(history) < MIN_HISTORY:
        return []

    usual = statistics.median(history)
    if usual > 0 and expense.amount > usual * UNUSUAL_RATIO:
        ratio = expense.amount / usual
        return [f"Unusual amount: {ratio:.1f}x {scope} usual {expense.category.value} expense "
                f"(median {usual:.2f})"]
    return []
