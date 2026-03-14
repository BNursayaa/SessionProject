from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .db import Db
from .features import extract_features
from .models import (
    ControlAckIn,
    ControlClaimIn,
    ControlCommandIn,
    ControlCommandOut,
    ControlStateOut,
    DerivedOut,
    HealthOut,
    HistoryOut,
    NasaVibrationOut,
    RiskOut,
    TelemetryIn,
    TelemetryOut,
    utc_now,
)
from .nasa_baseline import baseline_active, baseline_file_exists
from .nasa_rul import model_active as nasa_rul_active, model_file_exists as nasa_rul_file_exists
from .ml.anomaly_iforest import model_active as ml_anomaly_active, model_file_exists as ml_anomaly_file_exists
from .risk import get_nasa_vibration_thresholds, score_risk
from .settings import load_settings


settings = load_settings()
db = Db(db_url=settings.db_url)

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
            ml_score=risk.ml_score,
        ),
        derived=DerivedOut(pulse_rate=feats.pulse_rate),
    )


def _control_to_out(row) -> ControlCommandOut:
    return ControlCommandOut(
        id=row.id,
        ts=row.ts,
        action=row.action,  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        source=row.source,
        claimed_by=row.claimed_by,
        claimed_at=row.claimed_at,
        done_at=row.done_at,
        error=row.error,
    )


@app.get("/api/health", response_model=HealthOut)
async def health() -> HealthOut:
    nasa_vib = None
    thr = get_nasa_vibration_thresholds()
    if thr is not None:
        nasa_vib = NasaVibrationOut(
            mean=thr.mean,
            std=thr.std,
            scale=thr.scale,
            warn_z=thr.warn_z,
            crit_z=thr.crit_z,
            warn_raw=thr.warn_raw,
            crit_raw=thr.crit_raw,
        )
    return HealthOut(
        status="ok",
        db_kind=db.kind(),
        db_target=db.safe_url(),
        nasa_baseline_active=baseline_active(),
        nasa_baseline_file_exists=baseline_file_exists(),
        nasa_rul_ml_file_exists=nasa_rul_file_exists(),
        nasa_rul_ml_active=nasa_rul_active(),
        ml_anomaly_file_exists=ml_anomaly_file_exists(),
        ml_anomaly_active=ml_anomaly_active(),
        nasa_vibration=nasa_vib,
        ws_clients=await ws_hub.count(),
    )


@app.post("/api/telemetry", response_model=TelemetryOut)
async def ingest_telemetry(payload: TelemetryIn) -> TelemetryOut:
    ts = payload.ts or utc_now()
    current_set = db.get_desired_pwm().int_value or 0
    if int(current_set) != int(payload.pwm):
        st = db.set_desired_pwm(value=int(payload.pwm))
        await ws_hub.broadcast_json(
            {
                "type": "control_state",
                "data": ControlStateOut(desired_pwm=st.int_value or 0, updated_at=st.ts).model_dump(mode="json"),
            }
        )

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


@app.post("/api/control", response_model=ControlCommandOut)
async def enqueue_control(payload: ControlCommandIn) -> ControlCommandOut:
    if payload.action in ("pwm_up", "pwm_down"):
        cur = db.get_desired_pwm().int_value or 0
        step = 10
        desired = cur + step if payload.action == "pwm_up" else cur - step
        st = db.set_desired_pwm(value=desired)
        await ws_hub.broadcast_json(
            {
                "type": "control_state",
                "data": ControlStateOut(desired_pwm=st.int_value or 0, updated_at=st.ts).model_dump(mode="json"),
            }
        )

    row = db.insert_command(action=payload.action, source=payload.source)
    out = _control_to_out(row)
    await ws_hub.broadcast_json({"type": "control", "data": out.model_dump(mode="json")})
    return out


@app.post("/api/control/claim", response_model=ControlCommandOut | None)
async def claim_control(payload: ControlClaimIn) -> ControlCommandOut | None:
    row = db.claim_next_command(claimed_by=payload.client_id)
    if row is None:
        return None
    return _control_to_out(row)


@app.post("/api/control/{cmd_id}/ack", response_model=ControlCommandOut)
async def ack_control(cmd_id: int, payload: ControlAckIn) -> ControlCommandOut:
    row = db.ack_command(cmd_id=cmd_id, ok=payload.ok, error=payload.error)
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="command not found")
    out = _control_to_out(row)
    await ws_hub.broadcast_json({"type": "control_ack", "data": out.model_dump(mode="json")})
    return out


@app.get("/api/control/state", response_model=ControlStateOut)
async def control_state() -> ControlStateOut:
    st = db.get_desired_pwm()
    return ControlStateOut(desired_pwm=st.int_value or 0, updated_at=st.ts)


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
        latest_row = db.latest()
        if latest_row is not None:
            prev = db.previous(before_id=latest_row.id)
            out = _to_out(latest_row, prev)
            await ws.send_json({"type": "telemetry", "data": out.model_dump(mode="json")})

        while True:
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
