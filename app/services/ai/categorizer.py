"""Expense categorisation: cheap keyword rules first, AI only when the rules don't know."""
import re

from app.models.enums import ExpenseCategory
from app.services.ai.llm import LLMError, ask_json

KEYWORD_RULES: dict[ExpenseCategory, list[str]] = {
    ExpenseCategory.travel: ["uber", "ola", "rapido", "indigo", "air india", "akasa", "vistara", "irctc",
                             "railway", "metro", "taxi", "cab", "flight", "toll", "fuel", "petrol", "diesel"],
    ExpenseCategory.meals: ["swiggy", "zomato", "restaurant", "cafe", "café", "kitchen", "dhaba", "food",
                            "lunch", "dinner", "breakfast", "starbucks", "domino", "pizza", "biryani"],
    ExpenseCategory.accommodation: ["hotel", "oyo", "airbnb", "inn", "resort", "lodge", "treebo", "fabhotel"],
    ExpenseCategory.software: ["aws", "amazon web services", "github", "google workspace", "microsoft 365",
                               "figma", "notion", "slack", "zoom", "adobe", "subscription", "saas", "openai"],
    ExpenseCategory.office_supplies: ["stationery", "printer", "toner", "paper", "staples", "office supplies"],
    ExpenseCategory.training: ["course", "udemy", "coursera", "workshop", "training", "certification", "exam fee"],
}
CATEGORIES = [c.value for c in ExpenseCategory]


def rule_based(text: str) -> ExpenseCategory | None:
    t = text.lower()
    for category, words in KEYWORD_RULES.items():
        if any(re.search(rf"\b{re.escape(w)}\b", t) for w in words):
            return category
    return None


async def categorize(vendor: str | None, description: str | None) -> tuple[ExpenseCategory, str]:
    """Returns (category, source) where source is 'rules', 'ai' or 'default'."""
    text = " ".join(x for x in [vendor, description] if x).strip()
    if not text:
        return ExpenseCategory.other, "default"

    category = rule_based(text)
    if category:
        return category, "rules"

    prompt = (f"Classify this company expense into exactly one category from {CATEGORIES}.\n"
              f"Vendor: {vendor or '-'}\nDescription: {description or '-'}\n"
              'Answer as JSON: {"category": "<one of the list>"}')
    try:
        answer = await ask_json(prompt)
        value = str(answer.get("category", "")).strip().lower()
        if value in CATEGORIES:
            return ExpenseCategory(value), "ai"
    except LLMError:
        pass
    return ExpenseCategory.other, "default"
