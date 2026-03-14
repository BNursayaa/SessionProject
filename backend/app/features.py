from __future__ import annotations

from dataclasses import dataclass

from .db import TelemetryRow


@dataclass(frozen=True)
class Features:
    temp_c: float
    amps: float
    vibration: float
    pulse_rate: float


def extract_features(*, current: TelemetryRow, previous: TelemetryRow | None) -> Features:
    pulse_rate = 0.0
    if current.is_running and previous is not None:
        dt = (current.ts - previous.ts).total_seconds()
        if dt > 0:
            pulse_rate = max(0.0, (current.pulses - previous.pulses) / dt)

    return Features(
        temp_c=float(current.temp_c),
        amps=float(current.amps),
        vibration=float(current.vibration),
        pulse_rate=float(pulse_rate),
    )
