"""Shared test setup.

Tests use their own database, never your real one:
- locally: an in-memory SQLite database (nothing to install)
- in CI:   a PostgreSQL service, via TEST_DATABASE_URL
The AI is never called for real in tests; AI functions are replaced with fakes.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-long-enough-for-hs256")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app import models as _models  # noqa: F401  (registers all tables)

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "sqlite://")
if TEST_DATABASE_URL.startswith("sqlite"):
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
else:
    engine = create_engine(TEST_DATABASE_URL)
TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    session = TestingSession()
    yield session
    session.close()


def register(client, email, name="Test User", password="secret123"):
    r = client.post("/auth/register", json={"email": email, "full_name": name, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


def auth(client, email, password="secret123"):
    r = client.post("/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def org(client):
    """A small company: finance admin, a Sales team with a manager and two employees, an Ops manager."""
    for email in ["admin@acme.com", "mgr@acme.com", "ravi@acme.com", "priya@acme.com", "ops@acme.com"]:
        register(client, email)
    admin = auth(client, "admin@acme.com")
    sales = client.post("/admin/teams", json={"name": "Sales"}, headers=admin).json()["id"]
    ops = client.post("/admin/teams", json={"name": "Ops"}, headers=admin).json()["id"]
    client.patch("/admin/users/2", json={"role": "manager", "team_id": sales}, headers=admin)
    client.patch("/admin/users/3", json={"team_id": sales}, headers=admin)
    client.patch("/admin/users/4", json={"team_id": sales}, headers=admin)
    client.patch("/admin/users/5", json={"role": "manager", "team_id": ops}, headers=admin)
    return {
        "admin": admin, "mgr": auth(client, "mgr@acme.com"), "ravi": auth(client, "ravi@acme.com"),
        "priya": auth(client, "priya@acme.com"), "ops_mgr": auth(client, "ops@acme.com"),
        "sales_id": sales, "ops_id": ops,
    }


def create_expense(client, headers, amount="450.00", category="meals", vendor="Cafe Coffee Day",
                   expense_date="2026-10-03", **extra):
    r = client.post("/expenses", json={"amount": amount, "category": category, "vendor": vendor,
                                       "expense_date": expense_date, **extra}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def upload(client, headers, expense_id, content=b"\x89PNG-test-image", name="r.png", mime="image/png"):
    return client.post(f"/expenses/{expense_id}/receipt", files={"file": (name, content, mime)}, headers=headers)
