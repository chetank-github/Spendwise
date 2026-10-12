import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models import Expense, User
from app.models.enums import ExpenseCategory, ExpenseStatus
from app.schemas.expense import ExpenseCreate, ExpenseList, ExpenseOut, ExpenseUpdate
from app.services.expense_access import (get_own_editable_expense, get_visible_expense,
                                         visible_expenses_query)

router = APIRouter(prefix="/expenses", tags=["expenses"])

ALLOWED_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf"}


def to_out(e: Expense) -> ExpenseOut:
    return ExpenseOut.model_validate({**e.__dict__, "has_receipt": e.receipt_path is not None})


@router.post("", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
def create_expense(data: ExpenseCreate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    expense = Expense(**data.model_dump(), owner_id=user.id, status=ExpenseStatus.draft)
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return to_out(expense)


@router.get("", response_model=ExpenseList)
def list_expenses(
    status_: ExpenseStatus | None = Query(default=None, alias="status"),
    category: ExpenseCategory | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    min_amount: Decimal | None = Query(default=None, ge=0),
    max_amount: Decimal | None = Query(default=None, ge=0),
    search: str | None = Query(default=None, max_length=100, description="Search vendor or description"),
    owner_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = visible_expenses_query(user)
    if status_:
        query = query.where(Expense.status == status_)
    if category:
        query = query.where(Expense.category == category)
    if date_from:
        query = query.where(Expense.expense_date >= date_from)
    if date_to:
        query = query.where(Expense.expense_date <= date_to)
    if min_amount is not None:
        query = query.where(Expense.amount >= min_amount)
    if max_amount is not None:
        query = query.where(Expense.amount <= max_amount)
    if search:
        pattern = f"%{search}%"
        query = query.where(or_(Expense.vendor.ilike(pattern), Expense.description.ilike(pattern)))
    if owner_id:
        query = query.where(Expense.owner_id == owner_id)

    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(Expense.expense_date.desc(), Expense.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return ExpenseList(items=[to_out(e) for e in rows], total=total, page=page, page_size=page_size)


@router.get("/{expense_id}", response_model=ExpenseOut)
def get_expense(expense_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return to_out(get_visible_expense(db, user, expense_id))


@router.patch("/{expense_id}", response_model=ExpenseOut)
def update_expense(expense_id: int, data: ExpenseUpdate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    expense = get_own_editable_expense(db, user, expense_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(expense, field, value.upper() if field == "currency" and value else value)
    db.commit()
    db.refresh(expense)
    return to_out(expense)


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(expense_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    expense = get_own_editable_expense(db, user, expense_id)
    if expense.status != ExpenseStatus.draft:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft expenses can be deleted")
    if expense.receipt_path:
        Path(expense.receipt_path).unlink(missing_ok=True)
    db.delete(expense)
    db.commit()


@router.post("/{expense_id}/receipt", response_model=ExpenseOut)
async def upload_receipt(expense_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    expense = get_own_editable_expense(db, user, expense_id)
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            detail="Receipt must be a JPG, PNG or PDF")
    content = await file.read()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Receipt must be under {settings.max_upload_mb} MB")

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    # Random file name: never trust the user's file name (path tricks, clashes)
    path = upload_dir / f"{uuid.uuid4().hex}{ALLOWED_TYPES[file.content_type]}"
    path.write_bytes(content)

    if expense.receipt_path:
        Path(expense.receipt_path).unlink(missing_ok=True)
    expense.receipt_path = str(path)
    db.commit()
    db.refresh(expense)
    return to_out(expense)


@router.get("/{expense_id}/receipt")
def download_receipt(expense_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    expense = get_visible_expense(db, user, expense_id)
    if not expense.receipt_path or not Path(expense.receipt_path).exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No receipt uploaded")
    return FileResponse(expense.receipt_path)