from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes import admin, auth, expenses
from app.core.config import settings
from app.db.session import get_db

app = FastAPI(title=settings.app_name, version="0.3.0")

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(expenses.router)


@app.get("/health", tags=["health"])
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "app": settings.app_name, "database": "connected"}