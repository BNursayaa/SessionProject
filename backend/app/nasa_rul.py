from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any


@dataclass(frozen=True)
class RulPoint:
    t_seconds: float
    vibration: float
    vibration_envelope: float


@dataclass(frozen=True)
class NasaRulModel:
    source: str
    t_end_seconds: float
    dt_median_seconds: float | None
    points: list[RulPoint]


def model_path() -> Path:
    default_path = Path(__file__).resolve().parent / "ml" / "nasa_rul_model.json"
    return Path(os.getenv("DT_NASA_RUL_MODEL_PATH", str(default_path)))


_lock = Lock()
_cached_mtime: float | None = None
_cached: NasaRulModel | None = None


def get_rul_model() -> NasaRulModel | None:
    global _cached_mtime, _cached
    path = model_path()
    if not path.exists():
        with _lock:
            _cached_mtime = None
            _cached = None
        return None

    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None

    with _lock:
        if _cached is not None and _cached_mtime == mtime:
            return _cached

        obj = json.loads(path.read_text(encoding="utf-8"))
        pts_raw: list[dict[str, Any]] = list(obj.get("points", []))
        points: list[RulPoint] = []
        for it in pts_raw:
            try:
                points.append(
                    RulPoint(
                        t_seconds=float(it["t_seconds"]),
                        vibration=float(it["vibration"]),
                        vibration_envelope=float(it["vibration_envelope"]),
                    )
                )
            except Exception:
                continue

        points.sort(key=lambda p: p.t_seconds)
        if not points:
            _cached = None
            _cached_mtime = mtime
            return None

        t_end = float(obj.get("t_end_seconds", points[-1].t_seconds))
        dt_med = obj.get("dt_median_seconds")
        dt_med_f = float(dt_med) if dt_med is not None else None
        _cached = NasaRulModel(
            source=str(obj.get("source", "NASA/IMS bearings")),
            t_end_seconds=t_end,
            dt_median_seconds=dt_med_f,
            points=points,
        )
        _cached_mtime = mtime
        return _cached


def model_file_exists() -> bool:
    return model_path().exists()


def model_active() -> bool:
    return get_rul_model() is not None


def estimate_rul_seconds(*, vibration: float) -> float | None:
    """
    Estimate Remaining Useful Life (seconds) by aligning the current vibration level
    to a NASA IMS run-to-failure vibration envelope curve.

    IMPORTANT:
    - `vibration` must be in the SAME domain as the model (typically RMS values).
    - If your device vibration is in another scale, apply DT_NASA_VIBRATION_SCALE first.
    """
    model = get_rul_model()
    if model is None:
        return None

    pts = model.points
    if not pts:
        return None

    v = float(vibration)
    env = [p.vibration_envelope for p in pts]

    # Find earliest index where envelope >= v (monotonic envelope).
    lo, hi = 0, len(env) - 1
    if v <= env[0]:
        idx = 0
    elif v >= env[-1]:
        idx = hi
    else:
        while lo < hi:
            mid = (lo + hi) // 2
            if env[mid] >= v:
                hi = mid
            else:
                lo = mid + 1
        idx = lo

    t_at = pts[idx].t_seconds
    t_end = float(model.t_end_seconds)
    return max(0.0, t_end - t_at)

