import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.expenses import ALLOWED_TYPES, to_out
from app.core.config import settings
from app.db.session import get_db
from app.models import Expense, User
from app.models.enums import ExpenseStatus
from app.schemas.expense import ExpenseOut
from app.services.ai import receipt_reader
from app.services.ai.receipt_reader import ReceiptAIError
from app.services.expense_access import get_own_editable_expense

router = APIRouter(prefix="/ai", tags=["ai"])


async def _read_upload(file: UploadFile) -> bytes:
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            detail="Receipt must be a JPG, PNG or PDF")
    content = await file.read()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Receipt must be under {settings.max_upload_mb} MB")
    return content


def _save(content: bytes, content_type: str) -> str:
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / f"{uuid.uuid4().hex}{ALLOWED_TYPES[content_type]}"
    path.write_bytes(content)
    return str(path)


def _apply(expense: Expense, r: receipt_reader.CleanReceipt, overwrite: bool) -> None:
    """Copy AI values onto the expense. With overwrite=False, only fill empty fields."""
    for field, value in [("vendor", r.vendor), ("expense_date", r.expense_date), ("amount", r.amount),
                         ("tax_amount", r.tax_amount), ("gstin", r.gstin)]:
        if value is not None and (overwrite or getattr(expense, field) is None):
            setattr(expense, field, value)
    if overwrite or expense.category.value == "other":
        expense.category = r.category
    expense.currency = r.currency if overwrite else expense.currency
    expense.ai_extracted = True
    expense.ai_confidence = r.confidence
    expense.ai_raw = r.raw
    expense.policy_flags = r.warnings or None


@router.post("/scan-receipt", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
async def scan_receipt(file: UploadFile = File(...), db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """Upload a receipt -> AI reads it -> a pre-filled draft expense is created."""
    content = await _read_upload(file)
    try:
        result = await receipt_reader.extract_receipt(content, file.content_type)
    except ReceiptAIError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))

    if result.amount is None or result.expense_date is None:
        raise HTTPException(status_code=422, detail={
            "message": "AI could not read the total amount or date. Please create the expense manually.",
            "ai_result": result.model_dump(mode="json"),
        })

    expense = Expense(owner_id=user.id, status=ExpenseStatus.draft, amount=result.amount,
                      expense_date=result.expense_date, receipt_path=_save(content, file.content_type))
    _apply(expense, result, overwrite=True)
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return to_out(expense)


@router.post("/expenses/{expense_id}/extract", response_model=ExpenseOut)
async def extract_for_expense(expense_id: int, overwrite: bool = False, db: Session = Depends(get_db),
                              user: User = Depends(get_current_user)):
    """Run the AI on an expense's existing receipt and fill in missing fields."""
    expense = get_own_editable_expense(db, user, expense_id)
    if not expense.receipt_path or not Path(expense.receipt_path).exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload a receipt first")
    mime = {v: k for k, v in ALLOWED_TYPES.items()}[Path(expense.receipt_path).suffix]
    try:
        result = await receipt_reader.extract_receipt(Path(expense.receipt_path).read_bytes(), mime)
    except ReceiptAIError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    _apply(expense, result, overwrite=overwrite)
    db.commit()
    db.refresh(expense)
    return to_out(expense)
