from functools import lru_cache
import logging
import time

import cv2
import numpy as np

from app.services.receipt_parser import parse_italian_receipt

logger = logging.getLogger(__name__)

# 1.8K on the longest side is a good speed/accuracy balance for phone receipt photos.
OCR_MAX_SIDE = 1800
OCR_MIN_SIDE = 1100


@lru_cache(maxsize=1)
def get_ocr_engine():
    """Create PaddleOCR once per backend process and reuse it for every scan."""
    from paddleocr import PaddleOCR

    started = time.perf_counter()
    engine = PaddleOCR(
        use_angle_cls=False,
        lang="latin",
        show_log=False,
        det_limit_side_len=OCR_MAX_SIDE,
    )
    logger.info("PaddleOCR initialized in %.2fs", time.perf_counter() - started)
    return engine


def preprocess_image(image_bytes: bytes) -> np.ndarray:
    started = time.perf_counter()
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Invalid image")

    h, w = image.shape[:2]
    longest = max(h, w)

    # Large mobile photos are the main OCR performance bottleneck. Shrink them early.
    if longest > OCR_MAX_SIDE:
        scale = OCR_MAX_SIDE / longest
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    # Only modestly enlarge genuinely small images; never blow them up to 2600+ px.
    elif longest < OCR_MIN_SIDE:
        scale = min(1.35, OCR_MIN_SIDE / longest)
        if scale > 1.05:
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Thermal receipts benefit from light local contrast enhancement. Keep processing cheap.
    clahe = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    logger.info(
        "OCR preprocessing: input=%dx%d output=%dx%d in %.2fs",
        w,
        h,
        gray.shape[1],
        gray.shape[0],
        time.perf_counter() - started,
    )
    return gray


def recognize_receipt(image_bytes: bytes) -> dict:
    total_started = time.perf_counter()
    image = preprocess_image(image_bytes)
    ocr = get_ocr_engine()

    infer_started = time.perf_counter()
    # Angle classification is intentionally disabled for speed. The mobile UI asks for an
    # upright receipt, while Paddle's detector still handles small natural skew.
    result = ocr.ocr(image, cls=False)
    logger.info("PaddleOCR inference finished in %.2fs", time.perf_counter() - infer_started)

    tokens: list[dict] = []
    for page in result or []:
        for entry in page or []:
            if not entry or len(entry) < 2:
                continue
            box = entry[0]
            text = entry[1][0]
            confidence = float(entry[1][1])
            if not text or not str(text).strip():
                continue
            tokens.append({
                "box": box,
                "text": str(text).strip(),
                "confidence": confidence,
            })

    if not tokens:
        raise ValueError("No text recognized")

    parsed = parse_italian_receipt(tokens)
    logger.info(
        "Receipt OCR complete: %d tokens, %d items, %.2fs total",
        len(tokens),
        len(parsed.get("items", [])),
        time.perf_counter() - total_started,
    )
    return parsed
