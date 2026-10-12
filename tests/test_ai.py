"""AI features, tested with fake AI responses (no network, no API key, no cost)."""
import json

import pytest

from app.services.ai import categorizer, receipt_reader, summary
from app.services.ai.llm import LLMError
from app.services.ai.receipt_reader import ReceiptExtraction, clean
from tests.conftest import create_expense, upload

GOOD = {"vendor": "Spice Route Kitchen", "expense_date": "2026-10-03", "total_amount": 1344.0,
        "currency": "inr", "tax_amount": 64, "gstin": "27ABCDE1234F1Z5", "category": "meals", "confidence": 0.95}


@pytest.fixture
def fake_ai(monkeypatch):
    """Replace the provider call; tests push the raw texts the 'AI' should return."""
    replies = []

    async def fake_ask(file_bytes, mime_type):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setitem(receipt_reader.PROVIDERS, "gemini", fake_ask)
    monkeypatch.setattr(receipt_reader.settings, "ai_provider", "gemini")
    return replies


def test_scan_receipt_creates_prefilled_draft(client, org, fake_ai):
    fake_ai.append(json.dumps(GOOD))
    r = client.post("/ai/scan-receipt", files={"file": ("r.png", b"\x89PNG", "image/png")}, headers=org["ravi"])
    e = r.json()
    assert r.status_code == 201
    assert (e["vendor"], e["amount"], e["expense_date"], e["category"]) == ("Spice Route Kitchen", "1344.00", "2026-10-03", "meals")
    assert e["gstin"] == "27ABCDE1234F1Z5" and e["currency"] == "INR" and e["ai_extracted"] and e["has_receipt"]


def test_invalid_json_is_retried_once(client, org, fake_ai):
    fake_ai.extend(["not json at all", json.dumps(GOOD)])
    r = client.post("/ai/scan-receipt", files={"file": ("r.png", b"\x89PNG", "image/png")}, headers=org["ravi"])
    assert r.status_code == 201


def test_ai_failures_return_clean_errors(client, org, fake_ai):
    fake_ai.extend(["bad", "bad"])
    r = client.post("/ai/scan-receipt", files={"file": ("r.png", b"\x89PNG", "image/png")}, headers=org["ravi"])
    assert r.status_code == 502
    fake_ai.append(json.dumps({**GOOD, "total_amount": None}))
    r = client.post("/ai/scan-receipt", files={"file": ("r.png", b"\x89PNG", "image/png")}, headers=org["ravi"])
    assert r.status_code == 422


def test_guardrails_on_ai_output():
    r = clean(ReceiptExtraction(**{**GOOD, "gstin": "BADGSTIN", "tax_amount": 5000, "confidence": 0.4,
                                   "category": "spaceships", "expense_date": "2099-01-01"}))
    assert r.gstin is None and r.tax_amount is None and r.expense_date is None
    assert r.category.value == "other"
    assert len(r.warnings) == 4


@pytest.mark.parametrize("vendor,expected", [
    ("Uber India", "travel"), ("Swiggy", "meals"), ("OYO Rooms", "accommodation"),
    ("GitHub", "software"), ("Udemy", "training"),
])
def test_keyword_categorisation(vendor, expected):
    assert categorizer.rule_based(vendor).value == expected


def test_categorize_uses_ai_only_as_fallback(client, org, monkeypatch):
    calls = []

    async def fake_ask_json(prompt):
        calls.append(prompt)
        return {"category": "training"}

    monkeypatch.setattr(categorizer, "ask_json", fake_ask_json)
    r = client.post("/ai/categorize", json={"vendor": "Uber"}, headers=org["ravi"]).json()
    assert r == {"category": "travel", "source": "rules"} and not calls
    r = client.post("/ai/categorize", json={"vendor": "NASSCOM", "description": "summit"}, headers=org["ravi"]).json()
    assert r == {"category": "training", "source": "ai"} and len(calls) == 1

    async def broken(prompt):
        raise LLMError("down")

    monkeypatch.setattr(categorizer, "ask_json", broken)
    r = client.post("/ai/categorize", json={"vendor": "Mystery Co"}, headers=org["ravi"]).json()
    assert r == {"category": "other", "source": "default"}


def test_duplicate_receipt_detected_across_employees(client, org):
    a = create_expense(client, org["ravi"])
    upload(client, org["ravi"], a["id"], b"same-receipt-bytes")
    client.post(f"/expenses/{a['id']}/submit", headers=org["ravi"])
    b = create_expense(client, org["priya"], vendor="Different")
    upload(client, org["priya"], b["id"], b"same-receipt-bytes")
    flags = client.get(f"/ai/expenses/{b['id']}/risk-check", headers=org["priya"]).json()["flags"]
    assert any("another employee" in f for f in flags)
    assert client.get(f"/expenses/{b['id']}", headers=org["priya"]).json()["status"] == "draft"  # preview only


def test_same_amount_date_vendor_duplicate(client, org):
    a = create_expense(client, org["ravi"], vendor="Spice Route Kitchen")
    client.post(f"/expenses/{a['id']}/submit", headers=org["ravi"])
    b = create_expense(client, org["ravi"], vendor="Spice Route Kitchen ")
    flags = client.post(f"/expenses/{b['id']}/submit", headers=org["ravi"]).json()["policy_flags"]
    assert any("Possible duplicate" in f for f in flags)


def test_unusual_amount_flag(client, org):
    for i in range(6):
        x = create_expense(client, org["ravi"], amount=str(300 + i * 10), vendor=f"Cafe {i}", expense_date=f"2026-09-1{i}")
        client.post(f"/expenses/{x['id']}/submit", headers=org["ravi"])
    big = create_expense(client, org["ravi"], amount="2400", vendor="Taj")
    upload(client, org["ravi"], big["id"])
    flags = client.post(f"/expenses/{big['id']}/submit", headers=org["ravi"]).json()["policy_flags"]
    assert any("Unusual amount" in f for f in flags)


def test_monthly_insight_uses_ai_then_cache_then_template(client, org, monkeypatch):
    summary._cache.clear()
    e = create_expense(client, org["ravi"], amount="450")
    client.post(f"/expenses/{e['id']}/submit", headers=org["ravi"])
    calls = []

    async def fake_ask_json(prompt):
        calls.append(prompt)
        return {"headline": "INR 450.00 spent", "summary": "One meal.", "highlights": [], "recommendations": []}

    monkeypatch.setattr(summary, "ask_json", fake_ask_json)
    first = client.get("/ai/insights/monthly?month=2026-10", headers=org["mgr"]).json()
    second = client.get("/ai/insights/monthly?month=2026-10", headers=org["mgr"]).json()
    assert first["source"] == "ai" and not first["cached"] and second["cached"] and len(calls) == 1
    assert first["facts"]["total_spent"] == "450.00"
    assert '"total_spent": "450.00"' in calls[0]   # the AI is given the real numbers

    async def broken(prompt):
        raise LLMError("down")

    monkeypatch.setattr(summary, "ask_json", broken)
    fallback = client.get("/ai/insights/monthly?month=2026-09", headers=org["admin"]).json()
    assert fallback["source"] == "template"
    assert client.get("/ai/insights/monthly?month=2026-10", headers=org["ravi"]).status_code == 403
