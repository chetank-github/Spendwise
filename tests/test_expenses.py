from tests.conftest import create_expense, upload


def test_create_and_validation(client, org):
    e = create_expense(client, org["ravi"], amount="1250.50")
    assert e["status"] == "draft" and e["amount"] == "1250.50" and e["currency"] == "INR"
    bad = [{"amount": "-5", "expense_date": "2026-10-01"},
           {"amount": "10", "expense_date": "2099-01-01"},
           {"amount": "10", "expense_date": "2026-10-01", "currency": "RUPEES"}]
    for body in bad:
        assert client.post("/expenses", json=body, headers=org["ravi"]).status_code == 422


def test_visibility_rules(client, org):
    create_expense(client, org["ravi"])
    create_expense(client, org["priya"])
    create_expense(client, org["ops_mgr"])
    total = lambda who: client.get("/expenses", headers=org[who]).json()["total"]
    assert total("ravi") == 1          # employee: own only
    assert total("mgr") == 2           # manager: own team
    assert total("admin") == 3         # finance: everything
    assert client.get("/expenses/1", headers=org["ops_mgr"]).status_code == 404  # other team: hidden


def test_filters_search_and_pagination(client, org):
    create_expense(client, org["ravi"], amount="4800", category="travel", vendor="IndiGo", expense_date="2026-09-20")
    create_expense(client, org["ravi"], amount="300", vendor="Barbeque Nation")
    create_expense(client, org["ravi"], amount="120", vendor="Chai Point")
    get = lambda q: client.get(f"/expenses?{q}", headers=org["ravi"]).json()
    assert get("category=travel")["total"] == 1
    assert get("search=barbeque")["total"] == 1
    assert get("min_amount=200")["total"] == 2
    assert get("date_from=2026-10-01")["total"] == 2
    page = get("page=2&page_size=2")
    assert page["total"] == 3 and len(page["items"]) == 1


def test_only_owner_can_edit_and_only_drafts_deleted(client, org):
    e = create_expense(client, org["ravi"])
    assert client.patch(f"/expenses/{e['id']}", json={"amount": "1"}, headers=org["mgr"]).status_code == 403
    assert client.patch(f"/expenses/{e['id']}", json={"vendor": "New"}, headers=org["ravi"]).json()["vendor"] == "New"
    client.post(f"/expenses/{e['id']}/submit", headers=org["ravi"])
    assert client.delete(f"/expenses/{e['id']}", headers=org["ravi"]).status_code == 409


def test_receipt_upload_rules(client, org):
    e = create_expense(client, org["ravi"])
    assert upload(client, org["ravi"], e["id"]).json()["has_receipt"] is True
    assert upload(client, org["ravi"], e["id"], b"hello", "x.txt", "text/plain").status_code == 415
    assert upload(client, org["ravi"], e["id"], b"0" * (6 * 1024 * 1024)).status_code == 413
    assert client.get(f"/expenses/{e['id']}/receipt", headers=org["mgr"]).status_code == 200
    assert client.get(f"/expenses/{e['id']}/receipt", headers=org["ops_mgr"]).status_code == 404
