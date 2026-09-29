# Deploy backend to Render

The backend no longer runs OCR models. OCR runs in the browser with Tesseract.js.

## Render settings

Build command:

```text
python -m pip install --upgrade pip && pip install -r requirements.txt
```

Start command:

```text
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Health check: `/health`

Environment variables:

- `DATABASE_URL` — Neon PostgreSQL connection string
- `SECRET_KEY` — long random secret
- `INITIAL_USER_PASSWORD` — initial password for seeded users
- `CORS_ORIGINS` — Vercel URL and optionally localhost, comma-separated
- `ENVIRONMENT=production`

Delete the old `PRELOAD_OCR_ON_STARTUP` variable if it is still present. It is no longer used.

There must be no PaddleOCR model downloads in runtime logs after this version is deployed.
