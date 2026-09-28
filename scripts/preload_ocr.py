from __future__ import annotations

import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = ROOT / "ocr_models"

MODELS = {
    "det": {
        "url": "https://paddleocr.bj.bcebos.com/PP-OCRv3/english/en_PP-OCRv3_det_infer.tar",
        "dirname": "en_PP-OCRv3_det_infer",
    },
    "rec": {
        "url": "https://paddleocr.bj.bcebos.com/PP-OCRv3/multilingual/latin_PP-OCRv3_rec_infer.tar",
        "dirname": "latin_PP-OCRv3_rec_infer",
    },
}


def _has_model_files(path: Path) -> bool:
    return any(path.glob("*.pdmodel")) or any(path.glob("inference.json")) or any(path.glob("*.pdiparams"))


def download_and_extract(name: str, url: str, dirname: str) -> Path:
    target = MODEL_ROOT / name
    if target.exists() and _has_model_files(target):
        print(f"[ocr-preload] {name}: already present at {target}")
        return target

    target.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"splitcheck-{name}-") as tmp:
        tmp_path = Path(tmp)
        archive = tmp_path / "model.tar"
        print(f"[ocr-preload] downloading {name}: {url}")
        urllib.request.urlretrieve(url, archive)

        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()
        with tarfile.open(archive, "r:*") as tf:
            tf.extractall(extract_dir)

        candidates = [
            extract_dir / dirname,
            *[p for p in extract_dir.rglob("*") if p.is_dir() and _has_model_files(p)],
        ]
        source = next((p for p in candidates if p.exists() and _has_model_files(p)), None)
        if source is None:
            raise RuntimeError(f"Could not find extracted PaddleOCR model files for {name}")

        for child in source.iterdir():
            destination = target / child.name
            if child.is_dir():
                if destination.exists():
                    shutil.rmtree(destination)
                shutil.copytree(child, destination)
            else:
                shutil.copy2(child, destination)

    if not _has_model_files(target):
        raise RuntimeError(f"PaddleOCR model {name} was not installed correctly at {target}")

    print(f"[ocr-preload] {name}: ready at {target}")
    return target


def main() -> None:
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    for name, cfg in MODELS.items():
        download_and_extract(name, cfg["url"], cfg["dirname"])
    print("[ocr-preload] all required OCR models are ready")


if __name__ == "__main__":
    main()
