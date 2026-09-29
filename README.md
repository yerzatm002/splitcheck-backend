# SplitCheck backend

FastAPI + Neon PostgreSQL backend for SplitCheck.

OCR is intentionally **not** executed on Render. The React frontend uses Tesseract.js in the user's browser and sends the recognized text to `POST /api/receipts/{id}/ocr-text`. The backend only parses Italian receipt text and stores structured items.

## Local start

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Swagger: `http://127.0.0.1:8000/docs`

## Production

Render needs `DATABASE_URL`, `SECRET_KEY`, `INITIAL_USER_PASSWORD`, `CORS_ORIGINS`, and `ENVIRONMENT=production`. No PaddleOCR/OpenCV/NumPy packages or OCR models are required.
