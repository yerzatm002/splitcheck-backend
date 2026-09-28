from functools import lru_cache
import logging
from pathlib import Path
import time

import cv2
import numpy as np

from app.services.receipt_parser import parse_italian_receipt

logger = logging.getLogger(__name__)

# 1.8K on the longest side is a good speed/accuracy balance for phone receipt photos.
OCR_MAX_SIDE = 1800
OCR_MIN_SIDE = 1100
PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_ROOT = PROJECT_ROOT / "ocr_models"
DET_MODEL_DIR = MODEL_ROOT / "det"
REC_MODEL_DIR = MODEL_ROOT / "rec"
CLS_MODEL_DIR = MODEL_ROOT / "cls"


def _model_ready(path: Path) -> bool:
    return path.exists() and (
        any(path.glob("*.pdmodel"))
        or any(path.glob("*.pdiparams"))
        or any(path.glob("inference.json"))
    )


@lru_cache(maxsize=1)
def get_ocr_engine():
    """Create PaddleOCR once per backend process and reuse it for every scan.

    On Render, detector, recognizer, and classifier model files are downloaded
    during the build into ``ocr_models/``. PaddleOCR 2.x may resolve/download the
    classifier at construction time even when angle classification is disabled,
    so we provide a local classifier directory too. Runtime inference still uses
    ``cls=False`` and therefore does not run angle classification.
    """
    from paddleocr import PaddleOCR

    if (
        not _model_ready(DET_MODEL_DIR)
        or not _model_ready(REC_MODEL_DIR)
        or not _model_ready(CLS_MODEL_DIR)
    ):
        raise RuntimeError(
            "OCR model files are missing. Run `python scripts/preload_ocr.py` "
            "before starting the service."
        )

    started = time.perf_counter()
    engine = PaddleOCR(
        use_angle_cls=False,
        lang="latin",
        show_log=False,
        det_limit_side_len=OCR_MAX_SIDE,
        det_model_dir=str(DET_MODEL_DIR),
        rec_model_dir=str(REC_MODEL_DIR),
        cls_model_dir=str(CLS_MODEL_DIR),
    )
    logger.info(
        "PaddleOCR initialized from preloaded models in %.2fs (det=%s, rec=%s, cls=%s)",
        time.perf_counter() - started,
        DET_MODEL_DIR,
        REC_MODEL_DIR,
        CLS_MODEL_DIR,
    )
    return engine


def preprocess_image(image_bytes: bytes) -> np.ndarray:
    started = time.perf_counter()
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Invalid image")

    h, w = image.shape[:2]
    longest = max(h, w)

    if longest > OCR_MAX_SIDE:
        scale = OCR_MAX_SIDE / longest
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    elif longest < OCR_MIN_SIDE:
        scale = min(1.35, OCR_MIN_SIDE / longest)
        if scale > 1.05:
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
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
