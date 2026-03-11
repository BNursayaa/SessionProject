from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock


@dataclass(frozen=True)
class FeatureStats:
    mean: float
    std: float


@dataclass(frozen=True)
class NasaBaseline:
    features: dict[str, FeatureStats]


def baseline_path() -> Path:
    default_path = Path(__file__).resolve().parent / "ml" / "nasa_baseline.json"
    return Path(os.getenv("DT_NASA_BASELINE_PATH", str(default_path)))

_lock = Lock()
_cached_mtime: float | None = None
_cached: NasaBaseline | None = None

def get_baseline() -> NasaBaseline | None:
    """
    Loads `nasa_baseline.json` if present.
    Cached by file mtime so you can generate the file and just restart the backend.
    """
    global _cached_mtime, _cached
    path = baseline_path()
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
        feats = obj.get("features", {})
        features: dict[str, FeatureStats] = {}
        for k, v in feats.items():
            try:
                mean = float(v["mean"])
                std = float(v["std"])
                if std <= 0:
                    std = 1.0
                features[str(k)] = FeatureStats(mean=mean, std=std)
            except Exception:
                continue

        _cached = NasaBaseline(features=features) if features else None
        _cached_mtime = mtime
        return _cached


def baseline_file_exists() -> bool:
    return baseline_path().exists()


def baseline_active() -> bool:
    return get_baseline() is not None
