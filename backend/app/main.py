from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .db import Db
from .features import extract_features
from .models import DerivedOut, HealthOut, HistoryOut, RiskOut, TelemetryIn, TelemetryOut, utc_now
from .nasa_baseline import baseline_active, baseline_file_exists
from .risk import score_risk
from .settings import load_settings


settings = load_settings()
db = Db(db_path=settings.db_path, db_url=settings.db_url)

app = FastAPI(title="Digital Twin Motor API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class WsHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def add(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.add(ws)

    async def remove(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast_json(self, payload: dict[str, Any]) -> None:
        async with self._lock:
            clients = list(self._clients)
        if not clients:
            return
        coros = []
        for ws in clients:
            coros.append(_safe_send(ws, payload))
        await asyncio.gather(*coros, return_exceptions=True)

    async def count(self) -> int:
        async with self._lock:
            return len(self._clients)


async def _safe_send(ws: WebSocket, payload: dict[str, Any]) -> None:
    try:
        await ws.send_json(payload)
    except Exception:
        pass


ws_hub = WsHub()


def _to_out(row, previous_row) -> TelemetryOut:
    risk = score_risk(current=row, previous=previous_row)
    feats = extract_features(current=row, previous=previous_row)
    return TelemetryOut(
        id=row.id,
        ts=row.ts,
        temp_c=row.temp_c,
        amps=row.amps,
        vibration=row.vibration,
        pulses=row.pulses,
        pwm=row.pwm,
        is_running=row.is_running,
        risk=RiskOut(
            score=risk.score,
            level=risk.level,
            health=risk.health,
            reasons=risk.reasons,
            eta_seconds=risk.eta_seconds,
            eta_label=risk.eta_label,
            recommendations=risk.recommendations,
            baseline_z_max=risk.baseline_z_max,
        ),
        derived=DerivedOut(pulse_rate=feats.pulse_rate),
    )


@app.get("/api/health", response_model=HealthOut)
async def health() -> HealthOut:
    if db.kind().startswith("sqlite"):
        target = str(db.path) if db.path is not None else db.safe_url()
    else:
        target = db.safe_url()
    return HealthOut(
        status="ok",
        db_kind=db.kind(),
        db_target=target,
        nasa_baseline_active=baseline_active(),
        nasa_baseline_file_exists=baseline_file_exists(),
        ws_clients=await ws_hub.count(),
    )


@app.post("/api/telemetry", response_model=TelemetryOut)
async def ingest_telemetry(payload: TelemetryIn) -> TelemetryOut:
    ts = payload.ts or utc_now()
    row = db.insert(
        ts=ts,
        temp_c=payload.temp_c,
        amps=payload.amps,
        vibration=payload.vibration,
        pulses=payload.pulses,
        pwm=payload.pwm,
        is_running=payload.is_running,
    )
    prev = db.previous(before_id=row.id)
    out = _to_out(row, prev)
    await ws_hub.broadcast_json({"type": "telemetry", "data": out.model_dump(mode="json")})
    return out


@app.get("/api/latest", response_model=TelemetryOut)
async def latest() -> TelemetryOut:
    row = db.latest()
    if row is None:
        now = utc_now()
        from .db import TelemetryRow

        empty = TelemetryRow(
            id=0,
            ts=now,
            temp_c=0.0,
            amps=0.0,
            vibration=0.0,
            pulses=0,
            pwm=0,
            is_running=False,
        )
        return _to_out(empty, None)
    prev = db.previous(before_id=row.id)
    return _to_out(row, prev)


@app.get("/api/history", response_model=HistoryOut)
async def history(limit: int = 300) -> HistoryOut:
    items = db.history(limit=limit)
    out_items: list[TelemetryOut] = []
    prev = None
    for it in items:
        out_items.append(_to_out(it, prev))
        prev = it
    return HistoryOut(items=out_items)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    await ws_hub.add(ws)
    try:
        # Push latest on connect
        latest_row = db.latest()
        if latest_row is not None:
            prev = db.previous(before_id=latest_row.id)
            out = _to_out(latest_row, prev)
            await ws.send_json({"type": "telemetry", "data": out.model_dump(mode="json")})

        while True:
            # keep connection alive; client messages are optional
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await ws_hub.remove(ws)


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
