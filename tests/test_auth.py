from tests.conftest import auth, register


def test_first_user_becomes_finance_admin_others_employees(client):
    assert register(client, "first@acme.com")["role"] == "finance"
    assert register(client, "second@acme.com")["role"] == "employee"


def test_password_is_hashed_and_never_returned(client, db):
    from app.models import User
    body = register(client, "a@acme.com", password="secret123")
    assert "password" not in body and "hashed_password" not in body
    stored = db.query(User).filter_by(email="a@acme.com").one().hashed_password
    assert stored != "secret123" and stored.startswith("$argon2")


def test_duplicate_email_rejected(client):
    register(client, "a@acme.com")
    r = client.post("/auth/register", json={"email": "a@acme.com", "full_name": "Again", "password": "secret123"})
    assert r.status_code == 409


def test_login_wrong_password(client):
    register(client, "a@acme.com")
    assert client.post("/auth/login", data={"username": "a@acme.com", "password": "wrongpass"}).status_code == 401


def test_me_requires_valid_token(client):
    register(client, "a@acme.com")
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    assert client.get("/auth/me", headers=auth(client, "a@acme.com")).json()["email"] == "a@acme.com"


def test_admin_routes_forbidden_for_employees(client, org):
    r = client.post("/admin/teams", json={"name": "Hackers"}, headers=org["ravi"])
    assert r.status_code == 403
