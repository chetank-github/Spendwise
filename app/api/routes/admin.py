from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import Budget, Team, User
from app.models.enums import UserRole
from app.schemas.report import BudgetIn, BudgetOut
from app.schemas.user import TeamCreate, TeamOut, UserOut, UserUpdate

# Every route in this file is restricted to the finance (admin) role.
router = APIRouter(prefix="/admin", tags=["admin"],
                   dependencies=[Depends(require_roles(UserRole.finance))])


@router.post("/teams", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
def create_team(data: TeamCreate, db: Session = Depends(get_db)):
    if db.scalar(select(Team).where(Team.name == data.name)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Team already exists")
    team = Team(name=data.name)
    db.add(team)
    db.commit()
    db.refresh(team)
    return team


@router.get("/teams", response_model=list[TeamOut])
def list_teams(db: Session = Depends(get_db)):
    return db.scalars(select(Team).order_by(Team.name)).all()


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.id)).all()


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, data: UserUpdate, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if data.team_id is not None and db.get(Team, data.team_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


@router.put("/budgets", response_model=BudgetOut)
def set_budget(data: BudgetIn, db: Session = Depends(get_db)):
    """Create or update the budget for one team + category."""
    if db.get(Team, data.team_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    budget = db.scalar(select(Budget).where(Budget.team_id == data.team_id, Budget.category == data.category))
    if budget is None:
        budget = Budget(**data.model_dump())
        db.add(budget)
    else:
        budget.monthly_limit = data.monthly_limit
        budget.per_claim_limit = data.per_claim_limit
    db.commit()
    db.refresh(budget)
    return budget


@router.get("/budgets", response_model=list[BudgetOut])
def list_budgets(team_id: int | None = None, db: Session = Depends(get_db)):
    query = select(Budget).order_by(Budget.team_id, Budget.category)
    if team_id:
        query = query.where(Budget.team_id == team_id)
    return db.scalars(query).all()