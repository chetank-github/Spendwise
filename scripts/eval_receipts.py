"""Benchmark the AI receipt reader against hand-labelled receipts.

Usage (venv active, from the project folder):
    python scripts/eval_receipts.py
Reads eval/labels.csv + eval/receipts/*, calls the real AI provider set in .env,
prints per-field accuracy and writes eval/results.md.
"""
import asyncio
import csv
import re
import sys
import time
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.services.ai.receipt_reader import ReceiptAIError, extract_receipt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "eval"
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".pdf": "application/pdf"}
FIELDS = ["vendor", "expense_date", "total_amount", "tax_amount", "gstin"]
PAUSE_SECONDS = 2  # stay under free-tier rate limits


def norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def money_equal(expected: str, got: Decimal | None) -> bool:
    if not expected:
        return got is None
    return got is not None and abs(Decimal(expected) - got) <= Decimal("1")


def score(label: dict, result) -> dict[str, bool]:
    return {
        "vendor": SequenceMatcher(None, norm(label["vendor"]), norm(result.vendor)).ratio() >= 0.8,
        "expense_date": str(result.expense_date or "") == label["expense_date"],
        "total_amount": money_equal(label["total_amount"], result.amount),
        "tax_amount": money_equal(label["tax_amount"], result.tax_amount),
        "gstin": (result.gstin or "") == label["gstin"],
    }


async def main() -> None:
    labels = list(csv.DictReader(open(ROOT / "labels.csv", newline="")))
    rows, latencies, failures = [], [], 0
    for label in labels:
        path = ROOT / "receipts" / label["file"]
        start = time.perf_counter()
        try:
            result = await extract_receipt(path.read_bytes(), MIME[path.suffix.lower()])
            ok = score(label, result)
        except ReceiptAIError as e:
            print(f"  {label['file']}: AI error: {e}")
            ok, failures = {f: False for f in FIELDS}, failures + 1
        latencies.append(time.perf_counter() - start)
        rows.append((label["file"], ok))
        marks = " ".join(f"{f}={'OK' if v else 'X'}" for f, v in ok.items())
        print(f"{label['file']:<24} {marks}  ({latencies[-1]:.1f}s)")
        await asyncio.sleep(PAUSE_SECONDS)

    n = len(rows)
    per_field = {f: sum(ok[f] for _, ok in rows) / n * 100 for f in FIELDS}
    all_correct = sum(all(ok.values()) for _, ok in rows) / n * 100
    overall = sum(per_field.values()) / len(FIELDS)
    lat = sorted(latencies)

    lines = [
        "# Receipt reader benchmark", "",
        f"- Provider: `{settings.ai_provider}`, model: "
        f"`{settings.groq_model if settings.ai_provider == 'groq' else settings.gemini_model}`",
        f"- Receipts: {n} (failed AI calls: {failures})",
        f"- **Field accuracy: {overall:.1f}%**, receipts fully correct: {all_correct:.1f}%",
        f"- Latency: median {lat[n // 2]:.1f}s, max {lat[-1]:.1f}s", "",
        "| Field | Accuracy |", "|---|---|",
        *[f"| {f} | {per_field[f]:.1f}% |" for f in FIELDS], "",
        "| Receipt | " + " | ".join(FIELDS) + " |", "|---" * (len(FIELDS) + 1) + "|",
        *[f"| {name} | " + " | ".join("✅" if ok[f] else "❌" for f in FIELDS) + " |" for name, ok in rows],
    ]
    (ROOT / "results.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n" + "\n".join(lines[:6]))
    print(f"\nSaved -> {ROOT / 'results.md'}")


if __name__ == "__main__":
    asyncio.run(main())
