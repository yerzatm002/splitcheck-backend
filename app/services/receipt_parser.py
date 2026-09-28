import re
from decimal import Decimal, ROUND_HALF_UP
from statistics import median
from typing import Any

SKIP_PATTERNS = [
    r"totale complessivo",
    r"^totale$",
    r"di cui iva",
    r"pagamento",
    r"contante",
    r"non riscosso",
    r"resto",
    r"importo pagato",
    r"arrotondamento",
    r"sconto",
    r"documento commerciale",
    r"descrizione",
    r"prezzo",
    r"p\.?\s*iva",
    r"orario",
    r"numero cassa",
    r"documento\s*n",
    r"server\s*rt",
    r"firma elettronica",
    r"ecr",
    r"codice",
]

# Receipt prices: 1,19 / 1.19 / 29,96 / 29.96
PRICE_RE = re.compile(r"(?<!\d)(\d{1,5}[,.]\d{2})(?!\d)")
VAT_RE = re.compile(r"(?<!\d)\d{1,2}(?:[,.]\d+)?\s*%(?!\w)")
WEIGHT_RE = re.compile(r"(\d+[,.]\d{3})\s*kg\b", re.I)
NET_WEIGHT_RE = re.compile(
    r"(?:\b(?:netto|net)\b\s*[:=-]?\s*(\d+[,.]\d{3})\s*kg\b|"
    r"(\d+[,.]\d{3})\s*kg\s*\b(?:netto|net)\b)",
    re.I,
)
PER_KG_RE = re.compile(
    r"(?:\bEUR\b|€)\s*(\d+[,.]\d{2,3})\s*/\s*kg\b|"
    r"(\d+[,.]\d{2,3})\s*(?:EUR|€)?\s*/\s*kg\b|"
    r"(\d+[,.]\d{2,3})\s*(?:EUR|€)?\s*(?:per|al)\s*kg\b",
    re.I,
)
DATE_RE = re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b")
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
GROSS_TARE_RE = re.compile(r"\b(?:lordo|tara|peso\s+lordo)\b", re.I)
WEIGHT_METADATA_WORDS_RE = re.compile(r"\b(?:netto|net|lordo|tara)\b", re.I)


def _to_cents(value: str) -> int:
    value = value.strip()
    if "," in value:
        normalized = value.replace(".", "").replace(",", ".")
    else:
        normalized = value
    return int((Decimal(normalized) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _to_decimal(value: str) -> Decimal:
    return Decimal(value.replace(",", "."))


def _is_skip_line(line: str) -> bool:
    low = line.lower().strip()
    return any(re.search(pattern, low) for pattern in SKIP_PATTERNS)


def _looks_like_product(text: str) -> bool:
    text = text.strip()
    if not text or _is_skip_line(text):
        return False
    if DATE_RE.search(text) or TIME_RE.search(text):
        return False
    letters = sum(ch.isalpha() for ch in text)
    return letters >= 3


def _bbox_metrics(box: list[list[float]]) -> tuple[float, float, float, float, float, float]:
    xs = [float(p[0]) for p in box]
    ys = [float(p[1]) for p in box]
    x1, x2 = min(xs), max(xs)
    y1, y2 = min(ys), max(ys)
    return x1, y1, x2, y2, (x1 + x2) / 2, (y1 + y2) / 2


def _group_tokens_into_rows(tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group PaddleOCR tokens into visual receipt rows using y-position."""
    enriched = []
    heights = []
    for token in tokens:
        box = token.get("box")
        if not box or len(box) != 4:
            continue
        x1, y1, x2, y2, cx, cy = _bbox_metrics(box)
        height = max(y2 - y1, 1.0)
        heights.append(height)
        enriched.append({**token, "x1": x1, "x2": x2, "y1": y1, "y2": y2, "cx": cx, "cy": cy, "height": height})

    if not enriched:
        return []

    typical_height = median(heights) if heights else 20.0
    y_tolerance = max(8.0, typical_height * 0.60)

    enriched.sort(key=lambda t: (t["cy"], t["x1"]))
    rows: list[dict[str, Any]] = []

    for token in enriched:
        best_idx = None
        best_delta = None
        recent_rows = rows[-4:]
        base_idx = len(rows) - len(recent_rows)
        for idx, row in enumerate(recent_rows):
            absolute_idx = base_idx + idx
            delta = abs(token["cy"] - row["cy"])
            if delta <= y_tolerance and (best_delta is None or delta < best_delta):
                best_idx = absolute_idx
                best_delta = delta

        if best_idx is None:
            rows.append({"cy": token["cy"], "tokens": [token]})
        else:
            row = rows[best_idx]
            row["tokens"].append(token)
            row["cy"] = sum(t["cy"] for t in row["tokens"]) / len(row["tokens"])

    rows.sort(key=lambda r: r["cy"])
    for row in rows:
        row["tokens"].sort(key=lambda t: t["x1"])
        row["text"] = " ".join(t["text"].strip() for t in row["tokens"] if t["text"].strip())
        row["confidence"] = min((float(t.get("confidence", 0.0)) for t in row["tokens"]), default=0.0)
    return rows


def _extract_total_from_rows(rows: list[dict[str, Any]]) -> int:
    for index, row in enumerate(rows):
        text = row["text"]
        if re.search(r"totale\s+complessivo", text, re.I):
            prices = PRICE_RE.findall(text)
            if prices:
                return _to_cents(prices[-1])
            for nearby in rows[index + 1:index + 3]:
                prices = PRICE_RE.findall(nearby["text"])
                if prices:
                    return _to_cents(prices[-1])
    return 0


def _find_item_section(rows: list[dict[str, Any]]) -> tuple[int, int]:
    start = 0
    end = len(rows)

    for i, row in enumerate(rows):
        low = row["text"].lower()
        if "descrizione" in low or ("iva" in low and "prezzo" in low):
            start = i + 1
            break

    for i in range(start, len(rows)):
        low = rows[i]["text"].lower().strip()
        if re.search(r"\barticoli\b", low) or re.search(r"totale\s+complessivo", low):
            end = i
            break

    return start, end


def _description_without_columns(text: str) -> str:
    text = VAT_RE.sub(" ", text)
    text = PRICE_RE.sub(" ", text)
    text = re.sub(r"\bIVA\b", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" -.:;|_")
    return text


def _extract_net_weight(text: str) -> Decimal | None:
    match = NET_WEIGHT_RE.search(text)
    if not match:
        return None
    value = next((group for group in match.groups() if group), None)
    return _to_decimal(value) if value else None


def _extract_per_kg_cents(text: str) -> int | None:
    match = PER_KG_RE.search(text)
    if not match:
        return None
    value = next((group for group in match.groups() if group), None)
    return _to_cents(value) if value else None


def _is_weight_metadata_row(text: str) -> bool:
    """Return True for calculation rows that describe a weighed item, not the item itself.

    Typical Italian receipt examples:
      0.580kg LORDO - 0.004kg TARA
      0.576kg NETTO x EUR 0.98/kg
      NETTO 0,576 KG X EUR 0,98/KG

    These rows must enrich the following product row and must never become products.
    """
    low = text.lower()
    has_weight = bool(WEIGHT_RE.search(text))
    has_metadata_word = bool(WEIGHT_METADATA_WORDS_RE.search(text))
    has_per_kg = bool(_extract_per_kg_cents(text))
    return (has_weight and has_metadata_word) or (has_weight and has_per_kg) or bool(GROSS_TARE_RE.search(low))


def _weighted_expected_total_cents(weight: Decimal, unit_price_cents: int) -> int:
    return int((weight * Decimal(unit_price_cents)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _weight_matches_total(weight: Decimal, unit_price_cents: int, total_cents: int, tolerance_cents: int = 2) -> bool:
    expected = _weighted_expected_total_cents(weight, unit_price_cents)
    return abs(expected - total_cents) <= tolerance_cents


def _parse_spatial_items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    start, end = _find_item_section(rows)
    items: list[dict[str, Any]] = []

    # Weight metadata belongs to the NEXT actual product row on the IN'S receipts we target.
    pending_weight: Decimal | None = None
    pending_unit_price: int | None = None
    pending_weight_confidence: float = 1.0

    # Used for receipts where a product name is broken from its price onto a following row.
    pending_description: str | None = None
    pending_description_confidence: float = 0.0

    for row in rows[start:end]:
        text = row["text"].strip()
        if not text or _is_skip_line(text):
            continue
        if DATE_RE.search(text) or TIME_RE.search(text):
            continue

        # --- Weighed-product metadata -------------------------------------------------
        # Gross/tare rows are informational only. Do not use gross weight as quantity.
        if GROSS_TARE_RE.search(text):
            # A single OCR row can occasionally contain NETTO as well. In that rare case,
            # prefer the explicit NETTO value if present.
            net_weight = _extract_net_weight(text)
            if net_weight is not None:
                pending_weight = net_weight
                pending_weight_confidence = min(pending_weight_confidence, float(row["confidence"]))
            per_kg = _extract_per_kg_cents(text)
            if per_kg is not None:
                pending_unit_price = per_kg
                pending_weight_confidence = min(pending_weight_confidence, float(row["confidence"]))
            continue

        if _is_weight_metadata_row(text):
            net_weight = _extract_net_weight(text)
            # Fallback: if the line clearly says NETTO but OCR separated the word oddly,
            # use the first kg value on that row.
            if net_weight is None and re.search(r"\bnetto\b|\bnet\b", text, re.I):
                generic_weight = WEIGHT_RE.search(text)
                if generic_weight:
                    net_weight = _to_decimal(generic_weight.group(1))

            per_kg = _extract_per_kg_cents(text)
            if net_weight is not None:
                pending_weight = net_weight
            if per_kg is not None:
                pending_unit_price = per_kg
            pending_weight_confidence = min(pending_weight_confidence, float(row["confidence"]))
            # Critical: never let "0.576kg NETTO x EUR 0.98/kg" become an item.
            continue

        # Prefer the rightmost token containing a monetary value. Italian receipts usually
        # have description on the left, IVA in the middle, and final item total on the right.
        price_candidates: list[tuple[float, str]] = []
        for token in row["tokens"]:
            matches = PRICE_RE.findall(token["text"])
            if matches:
                price_candidates.append((token["x2"], matches[-1]))

        if not price_candidates:
            row_prices = PRICE_RE.findall(text)
            if row_prices:
                price_candidates.append((0.0, row_prices[-1]))

        description = _description_without_columns(text)

        if price_candidates:
            _, price_text = max(price_candidates, key=lambda p: p[0])
            price_cents = _to_cents(price_text)

            rightmost_price_token = None
            for token in reversed(row["tokens"]):
                if PRICE_RE.search(token["text"]):
                    rightmost_price_token = token
                    break
            if rightmost_price_token is not None:
                left_text = " ".join(
                    t["text"] for t in row["tokens"]
                    if t["x1"] < rightmost_price_token["x1"]
                )
                cleaner = _description_without_columns(left_text)
                if cleaner:
                    description = cleaner

            if _looks_like_product(description):
                is_weighted = pending_weight is not None and pending_unit_price is not None

                # Only attach pending weight metadata if its arithmetic agrees with the
                # printed item total. This prevents stale metadata from contaminating the
                # following ordinary product when OCR misses a row.
                if is_weighted and _weight_matches_total(pending_weight, pending_unit_price, price_cents):
                    quantity = pending_weight
                    unit = "kg"
                    unit_price_cents = pending_unit_price
                    confidence = min(float(row["confidence"]), pending_weight_confidence)
                else:
                    quantity = Decimal("1")
                    unit = "pcs"
                    unit_price_cents = None
                    confidence = float(row["confidence"])

                items.append({
                    "name": description,
                    "quantity": quantity,
                    "unit": unit,
                    "unit_price_cents": unit_price_cents,
                    "total_price_cents": price_cents,
                    "confidence": Decimal(str(round(confidence, 4))),
                })

                # Weight metadata can apply to one item only. Clear it even if arithmetic
                # did not match, because carrying it farther is more dangerous than losing it.
                pending_weight = None
                pending_unit_price = None
                pending_weight_confidence = 1.0
                pending_description = None
                continue

            if pending_description and _looks_like_product(pending_description):
                is_weighted = pending_weight is not None and pending_unit_price is not None
                if is_weighted and _weight_matches_total(pending_weight, pending_unit_price, price_cents):
                    quantity = pending_weight
                    unit = "kg"
                    unit_price_cents = pending_unit_price
                    confidence = min(float(row["confidence"]), pending_description_confidence, pending_weight_confidence)
                else:
                    quantity = Decimal("1")
                    unit = "pcs"
                    unit_price_cents = None
                    confidence = min(float(row["confidence"]), pending_description_confidence)

                items.append({
                    "name": pending_description,
                    "quantity": quantity,
                    "unit": unit,
                    "unit_price_cents": unit_price_cents,
                    "total_price_cents": price_cents,
                    "confidence": Decimal(str(round(confidence, 4))),
                })
                pending_weight = None
                pending_unit_price = None
                pending_weight_confidence = 1.0
                pending_description = None
                continue

        if _looks_like_product(description) and not PRICE_RE.search(text):
            pending_description = description
            pending_description_confidence = float(row["confidence"])

    return items


def parse_italian_receipt(tokens: list[dict[str, Any]]) -> dict:
    """Parse OCR tokens from an Italian retail receipt.

    `tokens` should contain text, confidence and PaddleOCR quadrilateral `box` coordinates.
    Spatial grouping is intentionally used instead of a flat list because prices and product
    descriptions are commonly returned as separate OCR boxes.
    """
    rows = _group_tokens_into_rows(tokens)
    raw_text = "\n".join(row["text"] for row in rows)
    total_cents = _extract_total_from_rows(rows)
    items = _parse_spatial_items(rows)

    return {
        "store_name": _guess_store(rows),
        "currency": "EUR",
        "total_cents": total_cents,
        "items": items,
        "raw_text": raw_text,
    }


def _guess_store(rows: list[dict[str, Any]]) -> str | None:
    for row in rows[:12]:
        text = row["text"].strip()
        low = text.lower()
        if "in's" in low or "ins mercato" in low or "in s mercato" in low:
            return "IN'S Mercato"
        if any(x in low for x in ["mercato", "market", "supermerc", "arredondo"]):
            if not any(x in low for x in ["p.iva", "via ", "corso "]):
                return text
    return None
