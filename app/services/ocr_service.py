from typing import Any

from .receipt_parser import parse_italian_receipt, parse_italian_receipt_text


def parse_browser_ocr(raw_text: str, tokens: list[dict[str, Any]] | None = None) -> dict:
    """Parse OCR produced in the browser.

    Prefer spatial tokens when the frontend has them. Fall back to raw text so the endpoint
    remains resilient when a browser/device cannot provide word boxes.
    """
    if tokens:
        parsed = parse_italian_receipt(tokens)
        # Keep the browser's original text for debugging/review.
        if raw_text and raw_text.strip():
            parsed["raw_text"] = raw_text
        return parsed
    return parse_italian_receipt_text(raw_text)
