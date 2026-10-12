from tests.conftest import create_expense, upload


def test_full_approval_flow_with_audit_log(client, org):
    e = create_expense(client, org["ravi"], amount="1250.50")
    upload(client, org["ravi"], e["id"])
    eid = e["id"]
    assert client.post(f"/expenses/{eid}/submit", headers=org["ravi"]).json()["status"] == "submitted"
    r = client.post(f"/expenses/{eid}/reject", json={"comment": "Add attendees"}, headers=org["mgr"])
    assert r.json()["status"] == "rejected"
    client.patch(f"/expenses/{eid}", json={"description": "Lunch with Acme (4 people)"}, headers=org["ravi"])
    client.post(f"/expenses/{eid}/submit", headers=org["ravi"])
    assert client.post(f"/expenses/{eid}/approve", headers=org["mgr"]).json()["status"] == "approved"
    assert client.post(f"/expenses/{eid}/reimburse", headers=org["admin"]).json()["status"] == "reimbursed"
    history = client.get(f"/expenses/{eid}/history", headers=org["ravi"]).json()
    assert [h["action"] for h in history] == ["submit", "reject", "submit", "approve", "reimburse"]
    assert history[1]["comment"] == "Add attendees"


def test_receipt_required_above_500(client, org):
    e = create_expense(client, org["ravi"], amount="501")
    r = client.post(f"/expenses/{e['id']}/submit", headers=org["ravi"])
    assert r.status_code == 400 and "receipt" in r.json()["detail"].lower()


def test_review_permissions(client, org):
    e = create_expense(client, org["mgr"], amount="200")       # manager's own expense
    client.post(f"/expenses/{e['id']}/submit", headers=org["mgr"])
    assert client.post(f"/expenses/{e['id']}/approve", headers=org["mgr"]).status_code == 403   # no self-approval
    other = create_expense(client, org["ravi"], amount="200")
    client.post(f"/expenses/{other['id']}/submit", headers=org["ravi"])
    assert client.post(f"/expenses/{other['id']}/approve", headers=org["ops_mgr"]).status_code == 404  # other team
    assert client.post(f"/expenses/{other['id']}/reimburse", headers=org["mgr"]).status_code == 403   # finance only
    assert client.post(f"/expenses/{other['id']}/reject", json={}, headers=org["mgr"]).status_code == 422


def test_illegal_transitions_return_409(client, org):
    e = create_expense(client, org["ravi"], amount="200")
    assert client.post(f"/expenses/{e['id']}/approve", headers=org["mgr"]).status_code == 409   # draft
    client.post(f"/expenses/{e['id']}/submit", headers=org["ravi"])
    client.post(f"/expenses/{e['id']}/approve", headers=org["mgr"])
    assert client.post(f"/expenses/{e['id']}/approve", headers=org["mgr"]).status_code == 409   # twice
    assert client.patch(f"/expenses/{e['id']}", json={"amount": "1"}, headers=org["ravi"]).status_code == 409


def test_budget_flags_and_monthly_report(client, org):
    client.put("/admin/budgets", json={"team_id": org["sales_id"], "category": "meals",
                                       "monthly_limit": "1000", "per_claim_limit": "400"}, headers=org["admin"])
    a = create_expense(client, org["ravi"], amount="450")
    flags = client.post(f"/expenses/{a['id']}/submit", headers=org["ravi"]).json()["policy_flags"]
    assert any("per-claim limit" in f for f in flags)
    b = create_expense(client, org["priya"], amount="300")
    upload(client, org["priya"], b["id"])
    c = create_expense(client, org["priya"], amount="350", vendor="Other Cafe")
    client.post(f"/expenses/{b['id']}/submit", headers=org["priya"])
    flags = client.post(f"/expenses/{c['id']}/submit", headers=org["priya"]).json()["policy_flags"]
    assert any("budget exceeded" in f for f in flags)

    report = client.get("/reports/monthly?month=2026-10", headers=org["mgr"]).json()
    assert report["total_spent"] == "1100.00" and report["expense_count"] == 3
    assert report["budget_usage"][0]["used_pct"] == 110.0
    assert client.get("/reports/monthly?month=2026-10", headers=org["ravi"]).status_code == 403


def test_expense_without_flags_stores_sql_null(client, org, db):
    """Regression: JSON None must be SQL NULL, otherwise 'expenses with warnings' is over-counted."""
    from sqlalchemy import text
    e = create_expense(client, org["ravi"], amount="100")
    client.post(f"/expenses/{e['id']}/submit", headers=org["ravi"])
    assert db.execute(text("SELECT COUNT(*) FROM expenses WHERE policy_flags IS NULL")).scalar() == 1
