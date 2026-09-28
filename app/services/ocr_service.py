from functools import lru_cache
import cv2
import numpy as np

from app.services.receipt_parser import parse_italian_receipt


@lru_cache(maxsize=1)
def get_ocr_engine():
    # Lazy import keeps the API bootable before the first OCR call.
    from paddleocr import PaddleOCR
    return PaddleOCR(use_angle_cls=True, lang="latin", show_log=False)


def preprocess_image(image_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Invalid image")

    h, w = image.shape[:2]

    # Receipts have very small print. Upscale smaller phone photos instead of shrinking them.
    if max(h, w) < 2600:
        scale = min(1.6, 2600 / max(h, w))
        if scale > 1.05:
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    elif max(h, w) > 3600:
        scale = 3600 / max(h, w)
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    # Local contrast enhancement works well on thermal paper while preserving PaddleOCR edges.
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    return gray


def recognize_receipt(image_bytes: bytes) -> dict:
    image = preprocess_image(image_bytes)
    ocr = get_ocr_engine()
    result = ocr.ocr(image, cls=True)

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

    return parse_italian_receipt(tokens)
