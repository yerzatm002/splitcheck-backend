import re
from decimal import Decimal, ROUND_HALF_UP
from difflib import SequenceMatcher
from statistics import median
from typing import Any

# -----------------------------------------------------------------------------
# OCR-tolerant Italian receipt parser.
# Works with either spatial OCR tokens (preferred) or plain Tesseract text.
# -----------------------------------------------------------------------------

SKIP_PATTERNS = [
    r"totale\s+(?:complessivo|coplessivo|complessino|complesslvo)",
    r"^totale$",
    r"di\s+cui\s+iva",
    r"pagamento",
    r"contante",
    r"elettronico",
    r"non\s+riscosso",
    r"resto",
    r"importo\s+pagato",
    r"arrotondamento",
    r"sconto",
    r"documento\s+commerciale",
    r"descrizione",
    r"prezzo",
    r"p\.?\s*iva",
    r"orario",
    r"numero\s+cassa",
    r"documento\s*n",
    r"doc\.?\s*n",
    r"server\s*rt",
    r"firma\s+elettronica",
    r"ecr",
    r"codice",
]

# Strict and tolerant monetary forms. Tesseract commonly reads decimal separator as ':'
# and the final digit 6 as '%' on thermal receipts, e.g. 29,9% -> 29,96.
STRICT_PRICE_RE = re.compile(r"(?<!\d)(\d{1,5}[,.]\d{2})(?!\d)")
TOLERANT_PRICE_RE = re.compile(r"(?<!\d)(\d{1,5}[,.:]\d{1,2}%?)(?!\d)")
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


def _fold(text: str) -> str:
    """Normalize OCR text for fuzzy structural matching, not for display."""
    text = text.lower()
    text = text.replace("€", " eur ")
    text = re.sub(r"[^a-z0-9à-ÿ]+", " ", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def _similar(a: str, b: str, threshold: float = 0.72) -> bool:
    return SequenceMatcher(None, _fold(a), _fold(b)).ratio() >= threshold


def _normalize_money_token(value: str, monetary_context: bool = True) -> str | None:
    s = value.strip().replace(" ", "")
    # Decimal separator OCR error.
    s = s.replace(":", ".")
    # On totals/prices, a terminal '%' is frequently OCR for '6': 29,9% -> 29,96.
    if monetary_context and re.fullmatch(r"\d{1,5}[,.]\d%", s):
        s = s[:-1] + "6"
    if not re.fullmatch(r"\d{1,5}[,.]\d{1,2}", s):
        return None
    whole, frac = re.split(r"[,.]", s)
    # One fractional digit is accepted only as OCR damage; pad rather than invent a new digit.
    if len(frac) == 1:
        frac += "0"
    return f"{whole}.{frac}"


def _to_cents(value: str) -> int:
    normalized = _normalize_money_token(value)
    if normalized is None:
        raise ValueError(f"Not a money value: {value!r}")
    return int((Decimal(normalized) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _extract_money_candidates(text: str, *, exclude_vat: bool = True) -> list[tuple[str, int, int]]:
    """Return (raw, start, end) price-like tokens, optionally excluding VAT percentages."""
    out: list[tuple[str, int, int]] = []
    vat_spans = [m.span() for m in VAT_RE.finditer(text)] if exclude_vat else []
    for m in TOLERANT_PRICE_RE.finditer(text):
        span = m.span(1)
        if any(not (span[1] <= a or span[0] >= b) for a, b in vat_spans):
            continue
        raw = m.group(1)
        if _normalize_money_token(raw) is not None:
            out.append((raw, span[0], span[1]))
    return out


def _to_decimal(value: str) -> Decimal:
    return Decimal(value.replace(",", "."))


def _is_skip_line(line: str) -> bool:
    low = _fold(line)
    if any(re.search(pattern, low) for pattern in SKIP_PATTERNS):
        return True
    # Fuzzy guards for badly OCR'd structural lines.
    return (
        _similar(low, "totale complessivo", 0.66)
        or _similar(low, "documento commerciale", 0.72)
        or _similar(low, "firma elettronica", 0.72)
        or _similar(low, "di cui iva", 0.76)
    )


def _looks_like_product(text: str) -> bool:
    text = text.strip()
    if not text or _is_skip_line(text):
        return False
    # Reject metadata date/time rows, but do not mistake a price like 1:19 for a time.
    if DATE_RE.search(text) or (TIME_RE.search(text) and re.search(r"\b(?:doc|server|ecr)\b", text, re.I)):
        return False
    letters = sum(ch.isalpha() for ch in text)
    if letters < 3:
        return False
    # Reject lines dominated by OCR garbage/punctuation.
    alnum = sum(ch.isalnum() for ch in text)
    visible = sum(not ch.isspace() for ch in text)
    return visible == 0 or (alnum / visible) >= 0.45


def _clean_description(text: str) -> str:
    text = VAT_RE.sub(" ", text)
    # Remove only price-like values; preserve ordinary digits such as X50 / 30PZ / 8V.
    for raw, start, end in reversed(_extract_money_candidates(text)):
        text = text[:start] + " " + text[end:]
    text = re.sub(r"\bIVA\b", " ", text, flags=re.I)
    text = re.sub(r"^[^A-Za-zÀ-ÿ0-9]+|[^A-Za-zÀ-ÿ0-9?]+$", "", text)
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
    has_weight = bool(WEIGHT_RE.search(text))
    has_metadata_word = bool(WEIGHT_METADATA_WORDS_RE.search(text))
    has_per_kg = _extract_per_kg_cents(text) is not None
    return (has_weight and has_metadata_word) or (has_weight and has_per_kg) or bool(GROSS_TARE_RE.search(text))


def _weighted_expected_total_cents(weight: Decimal, unit_price_cents: int) -> int:
    return int((weight * Decimal(unit_price_cents)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _weight_matches_total(weight: Decimal, unit_price_cents: int, total_cents: int, tolerance_cents: int = 2) -> bool:
    return abs(_weighted_expected_total_cents(weight, unit_price_cents) - total_cents) <= tolerance_cents


def _is_header_line(text: str) -> bool:
    f = _fold(text)
    return (
        "descrizione" in f
        or ("iva" in f and "prezzo" in f)
        or _similar(f, "descrizione iva prezzo", 0.67)
    )


def _is_items_end_line(text: str) -> bool:
    f = _fold(text)
    # ARTICOLI is often OCR'd PARTICOLE / ARTICOLE / ARTICOL1.
    first = f.split(" ", 1)[0] if f else ""
    return (
        "articoli" in f
        or "particole" in f
        or SequenceMatcher(None, first, "articoli").ratio() >= 0.67
        or _similar(f, "totale complessivo", 0.66)
    )


def _is_total_line(text: str) -> bool:
    f = _fold(text)
    return "totale" in f and ("compl" in f or _similar(f, "totale complessivo", 0.62))


def _extract_total_from_text_lines(lines: list[str]) -> int:
    for i, line in enumerate(lines):
        if not _is_total_line(line):
            continue
        candidates = _extract_money_candidates(line, exclude_vat=False)
        if candidates:
            return _to_cents(candidates[-1][0])
        for nearby in lines[i + 1:i + 3]:
            candidates = _extract_money_candidates(nearby, exclude_vat=False)
            if candidates:
                return _to_cents(candidates[-1][0])
    return 0


def _guess_store_from_lines(lines: list[str]) -> str | None:
    for text in lines[:12]:
        low = _fold(text)
        if "ins mercato" in low or "in s mercato" in low or "mercato" == low:
            return "IN'S Mercato" if "ins" in low or "in s" in low else "mercato"
        if any(x in low for x in ["mercato", "market", "supermerc", "arredondo"]):
            if not any(x in low for x in ["p iva", "via ", "corso "]):
                return text.strip()
    return None


def _split_item_section(lines: list[str]) -> list[str]:
    start = 0
    for i, line in enumerate(lines):
        if _is_header_line(line):
            start = i + 1
            break
    end = len(lines)
    for i in range(start, len(lines)):
        if _is_items_end_line(lines[i]):
            end = i
            break
    return lines[start:end]


def _line_price_and_description(line: str) -> tuple[str, int | None]:
    candidates = _extract_money_candidates(line)
    if not candidates:
        return _clean_description(line), None
    raw, start, end = candidates[-1]
    # Prefer an amount located toward the right half of a row. In plain text we approximate
    # this using character position. This avoids treating numbers embedded in descriptions as prices.
    price_cents = _to_cents(raw)
    description = _clean_description(line[:start])
    return description, price_cents



def _extract_article_count(lines: list[str]) -> int | None:
    for line in lines:
        f = _fold(line)
        first = f.split(" ", 1)[0] if f else ""
        if "articoli" in f or "particole" in f or SequenceMatcher(None, first, "articoli").ratio() >= 0.67:
            nums = re.findall(r"\b(\d{1,3})\b", line)
            if nums:
                value = int(nums[-1])
                if 1 <= value <= 200:
                    return value
    return None

def parse_italian_receipt_text(raw_text: str) -> dict:
    """Parse plain Tesseract text.

    Important design choice: product rows whose price was not recognized are preserved with
    total_price_cents=None instead of being silently dropped. The REVIEW UI can then ask the
    user to correct only those rows. A parser cannot safely invent prices that OCR did not read.
    """
    raw_text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw_text.split("\n")]
    lines = [line for line in lines if line]

    total_cents = _extract_total_from_text_lines(lines)
    section = _split_item_section(lines)
    article_count = _extract_article_count(lines)
    items: list[dict[str, Any]] = []

    pending_weight: Decimal | None = None
    pending_unit_price: int | None = None
    pending_description: str | None = None

    for line in section:
        if _is_skip_line(line) or DATE_RE.search(line) or (TIME_RE.search(line) and re.search(r"\b(?:doc|server|ecr)\b", line, re.I)):
            continue

        if _is_weight_metadata_row(line):
            net = _extract_net_weight(line)
            if net is None and re.search(r"\bnetto\b|\bnet\b", line, re.I):
                m = WEIGHT_RE.search(line)
                if m:
                    net = _to_decimal(m.group(1))
            per_kg = _extract_per_kg_cents(line)
            if net is not None:
                pending_weight = net
            if per_kg is not None:
                pending_unit_price = per_kg
            continue

        description, price_cents = _line_price_and_description(line)

        # Price-only OCR fragments can complete the immediately preceding no-price item.
        if price_cents is not None and not _looks_like_product(description):
            if items and items[-1]["total_price_cents"] is None:
                items[-1]["total_price_cents"] = price_cents
                items[-1]["confidence"] = Decimal("0.55")
            continue

        if _looks_like_product(description):
            if price_cents is None:
                items.append({
                    "name": description,
                    "quantity": Decimal("1"),
                    "unit": "pcs",
                    "unit_price_cents": None,
                    "total_price_cents": None,
                    "confidence": Decimal("0.45"),
                })
            else:
                weighted = (
                    pending_weight is not None
                    and pending_unit_price is not None
                    and _weight_matches_total(pending_weight, pending_unit_price, price_cents)
                )
                items.append({
                    "name": description,
                    "quantity": pending_weight if weighted else Decimal("1"),
                    "unit": "kg" if weighted else "pcs",
                    "unit_price_cents": pending_unit_price if weighted else None,
                    "total_price_cents": price_cents,
                    "confidence": Decimal("0.70"),
                })
                pending_weight = None
                pending_unit_price = None

            if article_count and len(items) >= article_count:
                break

        # Ignore pure garbage/noise rows.

    return {
        "store_name": _guess_store_from_lines(lines),
        "currency": "EUR",
        "total_cents": total_cents,
        "items": items,
        "raw_text": raw_text,
    }


# ---------------------------- Spatial token parser ----------------------------

def _bbox_metrics(box: list[list[float]]) -> tuple[float, float, float, float, float, float]:
    xs = [float(p[0]) for p in box]
    ys = [float(p[1]) for p in box]
    x1, x2 = min(xs), max(xs)
    y1, y2 = min(ys), max(ys)
    return x1, y1, x2, y2, (x1 + x2) / 2, (y1 + y2) / 2


def _group_tokens_into_rows(tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
    y_tolerance = max(7.0, typical_height * 0.52)
    enriched.sort(key=lambda t: (t["cy"], t["x1"]))
    rows: list[dict[str, Any]] = []

    for token in enriched:
        best_idx = None
        best_delta = None
        for absolute_idx in range(max(0, len(rows) - 5), len(rows)):
            row = rows[absolute_idx]
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
        row["text"] = " ".join(t["text"].strip() for t in row["tokens"] if str(t.get("text", "")).strip())
        row["confidence"] = min((float(t.get("confidence", 0.0)) for t in row["tokens"]), default=0.0)
    return rows


def _extract_total_from_rows(rows: list[dict[str, Any]]) -> int:
    return _extract_total_from_text_lines([row["text"] for row in rows])


def _find_item_section(rows: list[dict[str, Any]]) -> tuple[int, int]:
    start = 0
    for i, row in enumerate(rows):
        if _is_header_line(row["text"]):
            start = i + 1
            break
    end = len(rows)
    for i in range(start, len(rows)):
        if _is_items_end_line(rows[i]["text"]):
            end = i
            break
    return start, end


def _parse_spatial_items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    start, end = _find_item_section(rows)
    items: list[dict[str, Any]] = []
    pending_weight: Decimal | None = None
    pending_unit_price: int | None = None
    pending_weight_confidence = 1.0

    for row in rows[start:end]:
        text = row["text"].strip()
        if not text or _is_skip_line(text) or DATE_RE.search(text) or TIME_RE.search(text):
            continue

        if _is_weight_metadata_row(text):
            net = _extract_net_weight(text)
            if net is None and re.search(r"\bnetto\b|\bnet\b", text, re.I):
                m = WEIGHT_RE.search(text)
                if m:
                    net = _to_decimal(m.group(1))
            per_kg = _extract_per_kg_cents(text)
            if net is not None:
                pending_weight = net
            if per_kg is not None:
                pending_unit_price = per_kg
            pending_weight_confidence = min(pending_weight_confidence, float(row["confidence"]))
            continue

        # Rightmost price token wins. This is much safer than parsing the flattened row.
        price_candidates: list[tuple[float, str, dict[str, Any]]] = []
        for token in row["tokens"]:
            for raw, _, _ in _extract_money_candidates(str(token.get("text", ""))):
                price_candidates.append((float(token["x2"]), raw, token))

        price_cents: int | None = None
        description = _clean_description(text)
        if price_candidates:
            _, raw, rightmost = max(price_candidates, key=lambda p: p[0])
            price_cents = _to_cents(raw)
            left_text = " ".join(t["text"] for t in row["tokens"] if t["x1"] < rightmost["x1"])
            cleaner = _clean_description(left_text)
            if cleaner:
                description = cleaner

        if not _looks_like_product(description):
            continue

        if price_cents is None:
            items.append({
                "name": description,
                "quantity": Decimal("1"),
                "unit": "pcs",
                "unit_price_cents": None,
                "total_price_cents": None,
                "confidence": Decimal(str(round(float(row["confidence"]), 4))),
            })
            continue

        weighted = (
            pending_weight is not None
            and pending_unit_price is not None
            and _weight_matches_total(pending_weight, pending_unit_price, price_cents)
        )
        items.append({
            "name": description,
            "quantity": pending_weight if weighted else Decimal("1"),
            "unit": "kg" if weighted else "pcs",
            "unit_price_cents": pending_unit_price if weighted else None,
            "total_price_cents": price_cents,
            "confidence": Decimal(str(round(min(float(row["confidence"]), pending_weight_confidence if weighted else 1.0), 4))),
        })
        pending_weight = None
        pending_unit_price = None
        pending_weight_confidence = 1.0

    return items


def parse_italian_receipt(tokens: list[dict[str, Any]]) -> dict:
    rows = _group_tokens_into_rows(tokens)
    raw_text = "\n".join(row["text"] for row in rows)
    return {
        "store_name": _guess_store_from_lines([row["text"] for row in rows]),
        "currency": "EUR",
        "total_cents": _extract_total_from_rows(rows),
        "items": _parse_spatial_items(rows),
        "raw_text": raw_text,
    }
