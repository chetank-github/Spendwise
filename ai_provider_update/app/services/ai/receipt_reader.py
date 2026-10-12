"""AI receipt reader: image/PDF bytes -> validated structured data (Gemini or Groq)."""
import base64
import json
import logging
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from google import genai
from google.genai import types
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings
from app.models.enums import ExpenseCategory

logger = logging.getLogger(__name__)

GSTIN_PATTERN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
CATEGORIES = [c.value for c in ExpenseCategory]

PROMPT = f"""You are an expense-receipt reader for an Indian company.
Read the attached receipt and return ONLY a JSON object with these fields:
- vendor: business name printed on the receipt, or null
- expense_date: date of purchase as YYYY-MM-DD, or null (Indian receipts use DD/MM/YYYY)
- total_amount: final amount paid including taxes, as a number, or null
- currency: 3-letter code, default "INR"
- tax_amount: total GST/tax (CGST+SGST+IGST), as a number, or null
- gstin: the seller's 15-character GSTIN if printed, else null
- category: one of {CATEGORIES}
- confidence: 0 to 1, how sure you are that vendor, date and total_amount are correct
Rules: never invent values; use null when unsure; total_amount is the grand total, not the subtotal."""


class ReceiptExtraction(BaseModel):
    vendor: str | None = None
    expense_date: str | None = None
    total_amount: float | None = None
    currency: str = "INR"
    tax_amount: float | None = None
    gstin: str | None = None
    category: str = "other"
    confidence: float = Field(default=0.0, ge=0, le=1)


class CleanReceipt(BaseModel):
    """What the rest of the app uses after our own validation (never trust raw AI output)."""
    vendor: str | None
    expense_date: date | None
    amount: Decimal | None
    currency: str
    tax_amount: Decimal | None
    gstin: str | None
    category: ExpenseCategory
    confidence: float
    warnings: list[str]
    raw: dict


class ReceiptAIError(Exception):
    pass


def _to_decimal(value: float | None) -> Decimal | None:
    if value is None:
        return None
    try:
        d = Decimal(str(value)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return d if d > 0 else None


def clean(extraction: ReceiptExtraction) -> CleanReceipt:
    """Business-rule validation of the AI output."""
    warnings: list[str] = []

    expense_date = None
    if extraction.expense_date:
        try:
            expense_date = date.fromisoformat(extraction.expense_date)
            if expense_date > date.today():
                warnings.append(f"AI read a future date ({expense_date}); please check")
                expense_date = None
        except ValueError:
            warnings.append(f"Could not understand date '{extraction.expense_date}'")

    amount = _to_decimal(extraction.total_amount)
    tax = _to_decimal(extraction.tax_amount)
    if amount and tax and tax >= amount:
        warnings.append("Tax amount is larger than the total; tax ignored")
        tax = None

    gstin = (extraction.gstin or "").replace(" ", "").upper() or None
    if gstin and not GSTIN_PATTERN.match(gstin):
        warnings.append(f"GSTIN '{gstin}' is not in a valid format")
        gstin = None

    category = extraction.category if extraction.category in CATEGORIES else "other"
    currency = (extraction.currency or "INR").upper()[:3]

    if extraction.confidence < settings.ai_min_confidence:
        warnings.append(f"Low AI confidence ({extraction.confidence:.2f}); please review all fields")

    return CleanReceipt(vendor=extraction.vendor, expense_date=expense_date, amount=amount,
                        currency=currency if len(currency) == 3 else "INR", tax_amount=tax, gstin=gstin,
                        category=ExpenseCategory(category), confidence=extraction.confidence,
                        warnings=warnings, raw=extraction.model_dump())


async def _ask_gemini(file_bytes: bytes, mime_type: str) -> str:
    if not settings.gemini_api_key:
        raise ReceiptAIError("GEMINI_API_KEY is not set in .env")
    client = genai.Client(api_key=settings.gemini_api_key)
    response = await client.aio.models.generate_content(
        model=settings.gemini_model,
        contents=[types.Part.from_bytes(data=file_bytes, mime_type=mime_type), PROMPT],
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0),
    )
    return response.text


async def _ask_groq(file_bytes: bytes, mime_type: str) -> str:
    if not settings.groq_api_key:
        raise ReceiptAIError("GROQ_API_KEY is not set in .env")
    if mime_type == "application/pdf":
        raise ReceiptAIError("The Groq provider reads images only; upload a JPG or PNG photo of the receipt")
    client = AsyncOpenAI(api_key=settings.groq_api_key, base_url="https://api.groq.com/openai/v1")
    image_url = f"data:{mime_type};base64,{base64.b64encode(file_bytes).decode()}"
    response = await client.chat.completions.create(
        model=settings.groq_model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]}],
    )
    return response.choices[0].message.content


PROVIDERS = {"gemini": _ask_gemini, "groq": _ask_groq}


async def extract_receipt(file_bytes: bytes, mime_type: str) -> CleanReceipt:
    ask = PROVIDERS.get(settings.ai_provider)
    if ask is None:
        raise ReceiptAIError(f"Unknown AI_PROVIDER '{settings.ai_provider}' (use gemini or groq)")

    last_error = None
    for attempt in (1, 2):  # one retry if the model returns invalid JSON
        try:
            text = await ask(file_bytes, mime_type)
            return clean(ReceiptExtraction.model_validate(json.loads(text)))
        except ReceiptAIError:
            raise
        except (json.JSONDecodeError, ValidationError, TypeError) as e:
            last_error = e
            logger.warning("Receipt AI returned invalid output (attempt %s): %s", attempt, e)
        except Exception as e:  # network, quota, wrong model name, access denied...
            logger.exception("Receipt AI call failed")
            raise ReceiptAIError(f"AI service error ({settings.ai_provider}): {e}") from e
    raise ReceiptAIError(f"AI returned unreadable output: {last_error}")
