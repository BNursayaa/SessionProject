from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any
import os


@dataclass(frozen=True)
class IForestModel:
    source: str
    vibration_col: str
    model: Any
    anomaly_p95: float
    anomaly_p99: float


def model_path() -> Path:
    default_path = Path(__file__).resolve().parent / "nasa_anomaly_iforest.joblib"
    return Path(os.getenv("DT_NASA_ANOMALY_MODEL_PATH", str(default_path)))


_lock = Lock()
_cached_mtime: float | None = None
_cached: IForestModel | None = None


def get_iforest_model() -> IForestModel | None:
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

        try:
            from joblib import load as joblib_load  # type: ignore[import-not-found]
        except Exception:
            _cached = None
            _cached_mtime = mtime
            return None

        try:
            obj = joblib_load(path)
        except Exception:
            _cached = None
            _cached_mtime = mtime
            return None

        if not isinstance(obj, dict):
            _cached = None
            _cached_mtime = mtime
            return None

        model = obj.get("model")
        vib_col = str(obj.get("vibration_col") or "vibration")
        p95 = obj.get("anomaly_p95")
        p99 = obj.get("anomaly_p99")
        if model is None or p95 is None or p99 is None:
            _cached = None
            _cached_mtime = mtime
            return None

        _cached = IForestModel(
            source=str(obj.get("source") or "NASA IMS Bearings (IsolationForest)"),
            vibration_col=vib_col,
            model=model,
            anomaly_p95=float(p95),
            anomaly_p99=float(p99),
        )
        _cached_mtime = mtime
        return _cached


def model_file_exists() -> bool:
    return model_path().exists()


def model_active() -> bool:
    return get_iforest_model() is not None


def score_anomaly(*, vibration: float) -> tuple[float | None, str | None]:
    """
    Returns:
      (ml_score_0_1, ml_level)
    where ml_level is one of: normal|warning|critical.
    """
    m = get_iforest_model()
    if m is None:
        return None, None

    x = float(vibration)
    try:
        decision = float(m.model.decision_function([[x]])[0])
    except Exception:
        return None, None

    anomaly = -decision
    p95 = float(m.anomaly_p95)
    p99 = float(m.anomaly_p99)
    if p99 <= p95:
        return None, None

    if anomaly <= p95:
        score = 0.0
    elif anomaly >= p99:
        score = 1.0
    else:
        score = (anomaly - p95) / (p99 - p95)

    if score >= 1.0:
        level = "critical"
    elif score > 0.0:
        level = "warning"
    else:
        level = "normal"

    return max(0.0, min(1.0, float(score))), level

