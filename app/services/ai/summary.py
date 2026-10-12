"""AI monthly spending summary.

Numbers are always computed with SQL; the AI only turns those facts into plain English.
If the AI is unavailable, a simple template summary is returned instead (graceful degradation).
"""
import json
import time
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.routes.reports import monthly_summary
from app.models import Expense, User
from app.services.ai.llm import LLMError, ask_json
from app.services.expense_access import visible_expenses_query
from app.services.workflow import COUNTED_STATUSES

CACHE_TTL_SECONDS = 600
_cache: dict[tuple, tuple[float, dict]] = {}


class AISummary(BaseModel):
    headline: str = Field(max_length=200)
    summary: str = Field(max_length=1500)
    highlights: list[str] = Field(default_factory=list, max_length=6)
    recommendations: list[str] = Field(default_factory=list, max_length=4)


def previous_month(month: str) -> str:
    d = date.fromisoformat(f"{month}-01")
    return f"{d.year - (d.month == 1)}-{(d.month - 2) % 12 + 1:02d}"


def _pct_change(now: Decimal, before: Decimal) -> float | None:
    if before == 0:
        return None
    return round(float((now - before) / before * 100), 1)


def build_facts(db: Session, user: User, month: str) -> dict:
    current = monthly_summary(month=month, db=db, user=user)
    prev_month = previous_month(month)
    previous = monthly_summary(month=prev_month, db=db, user=user)
    prev_by_cat = {c.category: c.total for c in previous.by_category}

    start = date.fromisoformat(f"{month}-01")
    end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    scoped = visible_expenses_query(user).where(
        Expense.expense_date >= start, Expense.expense_date < end).subquery()
    counted = select(scoped).where(scoped.c.status.in_([s.value for s in COUNTED_STATUSES])).subquery()
    top_vendors = db.execute(
        select(counted.c.vendor, func.sum(counted.c.amount), func.count())
        .where(counted.c.vendor.is_not(None))
        .group_by(counted.c.vendor).order_by(func.sum(counted.c.amount).desc()).limit(3)).all()
    flagged = db.scalar(select(func.count()).select_from(scoped).where(scoped.c.policy_flags.is_not(None)))

    return {
        "month": month,
        "currency": "INR",
        "total_spent": str(current.total_spent),
        "expense_count": current.expense_count,
        "previous_month": prev_month,
        "previous_total": str(previous.total_spent),
        "total_change_pct": _pct_change(current.total_spent, previous.total_spent),
        "by_category": [
            {"category": c.category, "total": str(c.total), "count": c.count,
             "change_vs_previous_pct": _pct_change(c.total, prev_by_cat.get(c.category, Decimal("0")))}
            for c in current.by_category],
        "by_status": current.by_status,
        "budget_usage": [b.model_dump(mode="json") for b in current.budget_usage],
        "top_vendors": [{"vendor": v, "total": str(t), "count": n} for v, t, n in top_vendors],
        "expenses_with_warnings": flagged,
    }


def template_summary(facts: dict) -> AISummary:
    cats = facts["by_category"]
    top = f"{cats[0]['category']} (INR {cats[0]['total']})" if cats else "no spending"
    change = facts["total_change_pct"]
    trend = f"{'up' if change > 0 else 'down'} {abs(change)}% vs {facts['previous_month']}" if change is not None else "no previous month to compare"
    over = [b for b in facts["budget_usage"] if b["used_pct"] >= 100]
    return AISummary(
        headline=f"INR {facts['total_spent']} spent in {facts['month']} ({trend})",
        summary=(f"{facts['expense_count']} expenses totalling INR {facts['total_spent']}. "
                 f"Largest category: {top}. {facts['expenses_with_warnings']} expense(s) carry warnings."),
        highlights=[f"{b['team_name']} {b['category']} budget at {b['used_pct']}%" for b in over],
        recommendations=[],
    )


async def generate_summary(db: Session, user: User, month: str) -> dict:
    facts = build_facts(db, user, month)
    cache_key = (user.id, month, json.dumps(facts, sort_keys=True))
    hit = _cache.get(cache_key)
    if hit and time.time() - hit[0] < CACHE_TTL_SECONDS:
        return {**hit[1], "cached": True}

    prompt = (
        "You are a finance analyst writing a short monthly expense summary for a manager in India.\n"
        "Use ONLY the facts in the JSON below. Do not invent numbers, names or causes. "
        "Mention amounts in INR exactly as given.\n"
        "Return JSON with keys: headline (one sentence), summary (3-4 sentences), "
        "highlights (up to 4 short bullet strings: biggest changes, budgets at or over 80%, warnings), "
        "recommendations (up to 3 short, practical actions).\n\n"
        f"FACTS:\n{json.dumps(facts, indent=2)}"
    )
    source = "ai"
    try:
        result = AISummary.model_validate(await ask_json(prompt))
    except (LLMError, ValidationError, TypeError, ValueError):
        result, source = template_summary(facts), "template"

    response = {"month": month, "source": source, **result.model_dump(), "facts": facts}
    if source == "ai":
        _cache[cache_key] = (time.time(), response)
    return {**response, "cached": False}
