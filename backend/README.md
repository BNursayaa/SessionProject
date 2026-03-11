# Backend (FastAPI)

## Run

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.main
```

## PostgreSQL (optional)

1) Create a `backend/.env` (do not commit passwords) and set:

- `DT_DB_URL=postgresql+psycopg://postgres:...@localhost:5432/digital_twin`

2) Create the database `digital_twin` in PostgreSQL (pgAdmin or psql).
3) Restart the backend. Tables are created automatically on startup.

## API

- `POST /api/telemetry` ingest a point
- `GET /api/latest` latest point + risk
- `GET /api/history?limit=300` history + risk
- `GET /api/health` service status
- `WS /ws` realtime stream (server broadcasts new points)
