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


class HealthOut(BaseModel):
    status: Literal["ok"]
    db_kind: str
    db_target: str
    nasa_baseline_active: bool
    nasa_baseline_file_exists: bool
    ws_clients: int

    model_config = {"extra": "forbid"}
