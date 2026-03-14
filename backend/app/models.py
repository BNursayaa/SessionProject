from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TelemetryIn(BaseModel):
    ts: datetime | None = Field(default=None, description="UTC timestamp; if omitted server sets now()")
    temp_c: float = Field(..., ge=-100, le=300)
    amps: float = Field(..., ge=0, le=200)
    vibration: float = Field(..., ge=0, le=1_000_000)
    pulses: int = Field(..., ge=0, le=10_000_000)
    pwm: int = Field(..., ge=0, le=255)
    is_running: bool = Field(...)

    model_config = {"extra": "forbid"}


class RiskOut(BaseModel):
    score: float = Field(..., ge=0, le=1, description="0..1, higher = worse")
    level: Literal["normal", "warning", "critical"]
    health: int = Field(..., ge=0, le=100, description="0..100, higher = better")
    reasons: list[str] = Field(default_factory=list)
    eta_seconds: float | None = Field(default=None, ge=0, description="ETA to a critical threshold (seconds)")
    eta_label: str | None = None
    recommendations: list[str] = Field(default_factory=list)
    baseline_z_max: float | None = Field(default=None, ge=0, description="Max z-score vs NASA baseline (if enabled)")
    ml_score: float | None = Field(default=None, ge=0, le=1, description="ML anomaly score (0..1) if enabled")

    model_config = {"extra": "forbid"}

class DerivedOut(BaseModel):
    pulse_rate: float = Field(..., ge=0, description="pulses per second (derived from pulses delta)")
    model_config = {"extra": "forbid"}


class TelemetryOut(BaseModel):
    id: int
    ts: datetime
    temp_c: float
    amps: float
    vibration: float
    pulses: int
    pwm: int
    is_running: bool
    risk: RiskOut
    derived: DerivedOut

    model_config = {"extra": "forbid"}


class HistoryOut(BaseModel):
    items: list[TelemetryOut]

    model_config = {"extra": "forbid"}


class NasaVibrationOut(BaseModel):
    mean: float
    std: float
    scale: float
    warn_z: float
    crit_z: float
    warn_raw: float | None = None
    crit_raw: float | None = None

    model_config = {"extra": "forbid"}


class HealthOut(BaseModel):
    status: Literal["ok"]
    db_kind: str
    db_target: str
    nasa_baseline_active: bool
    nasa_baseline_file_exists: bool
    nasa_rul_ml_file_exists: bool = False
    nasa_rul_ml_active: bool = False
    ml_anomaly_file_exists: bool = False
    ml_anomaly_active: bool = False
    nasa_vibration: NasaVibrationOut | None = None
    ws_clients: int

    model_config = {"extra": "forbid"}


ControlAction = Literal["start", "stop", "pwm_up", "pwm_down"]


class ControlCommandIn(BaseModel):
    action: ControlAction
    source: str | None = Field(default=None, max_length=200, description="Optional caller id (ui, script, etc)")

    model_config = {"extra": "forbid"}


class ControlCommandOut(BaseModel):
    id: int
    ts: datetime
    action: ControlAction
    status: Literal["pending", "claimed", "done", "failed"]
    source: str | None = None
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    done_at: datetime | None = None
    error: str | None = None

    model_config = {"extra": "forbid"}


class ControlClaimIn(BaseModel):
    client_id: str = Field(..., min_length=1, max_length=200)

    model_config = {"extra": "forbid"}


class ControlAckIn(BaseModel):
    ok: bool = Field(..., description="true if command was delivered to the device")
    error: str | None = Field(default=None, max_length=500)

    model_config = {"extra": "forbid"}


class ControlStateOut(BaseModel):
    desired_pwm: int = Field(..., ge=0, le=255)
    updated_at: datetime

    model_config = {"extra": "forbid"}
