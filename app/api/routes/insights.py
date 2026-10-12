from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import User
from app.models.enums import UserRole
from app.services.ai.summary import generate_summary

router = APIRouter(prefix="/ai/insights", tags=["ai"])


class MonthlyInsight(BaseModel):
    month: str
    source: str          # "ai" or "template" (fallback when AI is unavailable)
    cached: bool
    headline: str
    summary: str
    highlights: list[str]
    recommendations: list[str]
    facts: dict          # the exact numbers the summary is based on


@router.get("/monthly", response_model=MonthlyInsight)
async def monthly_insight(
    month: str = Query(pattern=r"^\d{4}-\d{2}$", examples=["2026-10"], description="YYYY-MM"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.manager, UserRole.finance)),
):
    """Plain-English spending summary for managers (team) and finance (whole company)."""
    try:
        date.fromisoformat(f"{month}-01")
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid month")
    return await generate_summary(db, user, month)
