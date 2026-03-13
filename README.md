# Digital Twin Motor (UNO) — SessionProject

This repo is a дипломный проект scaffold for:
**“Разработка цифрового двойника производственного оборудования для мониторинга и предиктивного обслуживания”**
with a concrete object: **smart industrial electric motor** (Arduino UNO макет).

## Architecture (UNO friendly)

`Arduino UNO` → `USB Serial` → `Python gateway` → `FastAPI backend + PostgreSQL` → `Next.js dashboard`

## Quick start (local)

### 1) Backend (API + DB + risk)

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# optional (recommended): PostgreSQL
# cd ..
# docker compose up -d postgres
# cd backend
# copy .env.example to .env and set DT_DB_URL

python -m app.main
```

Backend runs at `http://localhost:8000`.

### 2) Gateway (Serial → Backend)

```powershell
cd gateway
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# simulate (no Arduino needed)
python gateway.py --simulate

# real Arduino (example)
python gateway.py --port COM3 --baud 9600
```

### 3) Frontend (Dashboard)

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

## Notes

- The current “predictive” block is a baseline heuristic + placeholder for a NASA-trained model.
- Optional “NASA comparison”: put `backend/app/ml/nasa_baseline.json` (see `backend/app/ml/README.md`).
  - Check `http://localhost:8000/api/health` fields `nasa_baseline_file_exists` and `nasa_baseline_active`.
- Folders like `backend/.venv` and `frontend/node_modules` are generated locally (ignored by `.gitignore`).

## Arduino change (needed for real data)

Add Serial JSON output to your sketch (see `arduino/serial_telemetry_snippet.ino`).

## Smoke-check (your PC)

1) Start backend: `scripts\\run-backend.ps1`
2) Start gateway simulation: `scripts\\run-gateway-sim.ps1`
3) Start frontend: `scripts\\run-frontend.ps1`

If everything is OK:
- `http://localhost:8000/api/health` returns `status=ok`
- `http://localhost:3000` shows cards + live chart updating every ~1s
