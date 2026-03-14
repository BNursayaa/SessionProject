# Digital Twin — Motor (Arduino UNO)

This repo is a diploma project scaffold for a **digital twin** of an electric motor:
real-time monitoring + an MVP of predictive maintenance.

## Architecture

`Arduino UNO` → `USB Serial` → `Python gateway` → `FastAPI backend + PostgreSQL` → `Next.js dashboard`

## Quick start (local)

### 1) PostgreSQL (Docker)

```powershell
docker compose up -d postgres
```

Copy `.env.example` → `.env` (repo root) and set `POSTGRES_PASSWORD` locally.
The `.env` file is ignored by git.

### 2) Backend (API + DB + risk)

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# copy backend/.env.example -> backend/.env and set DT_DB_URL
python -m app.main
```

Backend runs at `http://localhost:8000`.

### 3) Gateway (Serial → Backend)

```powershell
cd gateway
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python gateway.py --api-base http://127.0.0.1:8000 --port COM7 --baud 115200 --verbose
```

### 4) Frontend (Dashboard)

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

## PWM: Set vs Out (why UI and LCD can differ)

Many DC motors do not spin reliably below a minimum PWM (deadzone). In this project:

- **Set PWM**: the user request (stored in backend `control_state`).
- **Out PWM**: the applied output PWM from Arduino telemetry.

If `Set PWM < 30`, the Arduino reports `Out PWM = 0` (motor may not spin). The dashboard shows both values.

## Predictive maintenance (MVP): what “ML” is here

Right now the “ML/predictive” block is a practical MVP made of:

1) **Rule-based checks** (temperature/current/vibration thresholds + trends).
2) **NASA baseline anomaly** (z-score vs `backend/app/ml/nasa_baseline.json`).
3) **NASA RUL estimate (optional)** using an envelope curve from `backend/app/ml/nasa_rul_model.json`.

Important: NASA files are not trained on your exact motor, so you must calibrate and tune.

### NASA vibration calibration

Your device vibration units differ from NASA IMS bearings. Use:

- `DT_NASA_VIBRATION_SCALE` to map device vibration → NASA domain
- `DT_NASA_BASELINE_WARN_Z`, `DT_NASA_BASELINE_CRIT_Z` to tune sensitivity

The backend exposes computed thresholds in:

- `GET /api/health` → `nasa_vibration` (warn/crit thresholds in your raw vibration units)

