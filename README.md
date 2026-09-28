# SplitCheck Backend

FastAPI backend for a mobile-first receipt splitting PWA.

## MVP features

- JWT authentication
- 3 seeded users: Бауыржан, Санжар, Ерзат
- Neon PostgreSQL support
- Italian receipt OCR using free/open-source PaddleOCR
- Receipt/item editing endpoints
- Participants can be registered users or temporary names
- Equal item splitting between 1, 2, 3+ participants
- Exact cent-based arithmetic, including rounding remainders
- Receipt summary endpoint
- Render-ready without Docker

## Default accounts

The first startup creates these users:

- `bauyrzhan` — ADMIN
- `sanzhar` — USER
- `yerzat` — USER

Temporary initial password for all three:

`SplitCheck2026!`

Change it before real use. The MVP currently does not expose a password-change endpoint.

## 1. Local setup (Windows)

Use Python 3.10.

```powershell
py -3.10 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
```

For a quick local test, you may put this into `.env`:

```env
DATABASE_URL=sqlite:///./splitcheck.db
SECRET_KEY=local-development-secret-change-me
CORS_ORIGINS=http://localhost:5173
```

Run:

```powershell
uvicorn app.main:app --reload
```

Open Swagger:

`http://127.0.0.1:8000/docs`

## 2. Neon

Create a Neon PostgreSQL project and copy its connection string.

Convert it to SQLAlchemy/psycopg format if needed:

```env
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST/DBNAME?sslmode=require
```

The app creates tables automatically on startup for the MVP.

## 3. Render without Docker

Create a new Web Service from the repository.

Use:

- Runtime: Python
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health check: `/health`

Environment variables:

- `DATABASE_URL`
- `SECRET_KEY`
- `CORS_ORIGINS=https://YOUR-APP.vercel.app`

### PaddleOCR note

On the first OCR request PaddleOCR may download model files. This can make the first request much slower than later ones. Render's small/free instances can also be memory-constrained; if OCR fails because of RAM, the rest of the backend still works and OCR can later be moved to a separate service without changing the frontend API significantly.

## Core API

### Authentication

- `POST /api/auth/login`
- `GET /api/auth/me`
- `GET /api/users`

### Receipts

- `POST /api/receipts`
- `GET /api/receipts`
- `GET /api/receipts/{id}`
- `DELETE /api/receipts/{id}`

### OCR

- `POST /api/receipts/{id}/ocr`

Send `multipart/form-data` with field `file`.

### Participants

- `POST /api/receipts/{id}/participants`
- `DELETE /api/receipts/{id}/participants/{participant_id}`

### Items

- `POST /api/receipts/{id}/items`
- `PATCH /api/receipts/{id}/items/{item_id}`
- `DELETE /api/receipts/{id}/items/{item_id}`

### Split

- `PUT /api/receipts/{id}/items/{item_id}/split`

Example body:

```json
{
  "participant_ids": [1, 2, 3]
}
```

### Summary

- `GET /api/receipts/{id}/summary`

## Recommended flow for the frontend

1. Login.
2. Create receipt and participants.
3. Upload receipt image to OCR endpoint.
4. Show OCR result for manual correction.
5. Split each item between selected participants.
6. Fetch summary.

## Important MVP limitation

The Italian receipt parser is heuristic. It handles common labels such as `TOTALE COMPLESSIVO`, `IVA`, `PAGAMENTO`, `RESTO`, prices with decimal comma, and basic weighted products. Real receipts vary significantly, so the UI must always allow manual correction after OCR.
