# Gateway (Arduino UNO Serial → Backend API)

Arduino UNO has no Wi‑Fi, so we use a PC gateway:

`UNO (USB Serial)` → `gateway.py` → `POST /api/telemetry`

## Run (simulate)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python gateway.py --simulate
```

## Run (real Arduino)

```powershell
python gateway.py --port COM3 --baud 9600
```

### Expected Serial format (recommended)

One JSON object per line, e.g.

```json
{"temp_c": 36.5, "amps": 0.4, "vibration": 120, "pulses": 1234, "pwm": 150, "is_running": true}
```

