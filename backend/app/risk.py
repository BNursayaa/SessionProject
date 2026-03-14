from __future__ import annotations

from dataclasses import dataclass
import os
import time

from .db import TelemetryRow
from .features import extract_features
from .ml.anomaly_iforest import score_anomaly
from .nasa_baseline import get_baseline
from .nasa_rul import estimate_rul_seconds, model_active as nasa_rul_active


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return float(default)
    try:
        return float(raw)
    except Exception:
        return float(default)


NASA_VIBRATION_SCALE = _env_float("DT_NASA_VIBRATION_SCALE", 1.0)
NASA_RUL_WARN_SECONDS = _env_float("DT_NASA_RUL_WARN_SECONDS", 3600.0)
NASA_RUL_CRIT_SECONDS = _env_float("DT_NASA_RUL_CRIT_SECONDS", 600.0)
NASA_RUL_AFFECTS_SCORE = _env_float("DT_NASA_RUL_AFFECTS_SCORE", 1.0)
NASA_BASELINE_WARN_Z = _env_float("DT_NASA_BASELINE_WARN_Z", 5.0)
NASA_BASELINE_CRIT_Z = _env_float("DT_NASA_BASELINE_CRIT_Z", 8.0)
NASA_VIBRATION_EMA_ALPHA = _env_float("DT_NASA_VIBRATION_EMA_ALPHA", 0.2)
NASA_TRANSIENT_SECONDS = _env_float("DT_NASA_TRANSIENT_SECONDS", 2.0)
NASA_BASELINE_CONFIRM_SAMPLES = int(_env_float("DT_NASA_BASELINE_CONFIRM_SAMPLES", 3.0))


_vib_ema_raw: float | None = None
_last_pwm: int | None = None
_last_pwm_change_t: float | None = None
_baseline_warn_streak: int = 0
_baseline_crit_streak: int = 0


@dataclass(frozen=True)
class NasaVibrationThresholds:
    mean: float
    std: float
    scale: float
    warn_z: float
    crit_z: float
    warn_raw: float | None
    crit_raw: float | None


def get_nasa_vibration_thresholds() -> NasaVibrationThresholds | None:
    baseline = get_baseline()
    if baseline is None:
        return None
    st = baseline.features.get("vibration")
    if st is None:
        return None

    scale = float(NASA_VIBRATION_SCALE)
    warn_z = max(0.1, float(NASA_BASELINE_WARN_Z))
    crit_z = max(warn_z + 0.1, float(NASA_BASELINE_CRIT_Z))

    if scale > 0:
        warn_raw = (float(st.mean) + warn_z * float(st.std)) / scale
        crit_raw = (float(st.mean) + crit_z * float(st.std)) / scale
    else:
        warn_raw = None
        crit_raw = None

    return NasaVibrationThresholds(
        mean=float(st.mean),
        std=float(st.std),
        scale=scale,
        warn_z=warn_z,
        crit_z=crit_z,
        warn_raw=float(warn_raw) if warn_raw is not None else None,
        crit_raw=float(crit_raw) if crit_raw is not None else None,
    )


@dataclass(frozen=True)
class Risk:
    score: float  # 0..1
    level: str  # normal|warning|critical
    health: int  # 0..100
    reasons: list[str]
    eta_seconds: float | None
    eta_label: str | None
    recommendations: list[str]
    baseline_z_max: float | None
    ml_score: float | None


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            out.append(it)
            seen.add(it)
    return out


def score_risk(*, current: TelemetryRow, previous: TelemetryRow | None) -> Risk:
    """
    Predictive maintenance (MVP):
    - simple rule thresholds (temp/amps/vibration + trends)
    - optional NASA baseline z-score (if nasa_baseline.json exists)
    - optional NASA RUL estimate (if nasa_rul_model.json exists)

    NASA models are not trained on your exact motor. You must calibrate DT_NASA_VIBRATION_SCALE
    and tune z-thresholds for your device/environment.
    """
    reasons: list[str] = []
    recommendations: list[str] = []
    eta_seconds: float | None = None
    eta_label: str | None = None
    baseline_z_max: float | None = None
    ml_score: float | None = None

    temp_warn, temp_crit = 55.0, 70.0
    amps_warn, amps_crit = 1.5, 2.5
    vib_warn, vib_crit = 350.0, 700.0
    baseline = get_baseline()

    global _vib_ema_raw
    global _last_pwm, _last_pwm_change_t, _baseline_warn_streak, _baseline_crit_streak
    now_mono = time.monotonic()

    if not current.is_running:
        _last_pwm = None
        _last_pwm_change_t = None
        _baseline_warn_streak = 0
        _baseline_crit_streak = 0
    else:
        if _last_pwm is None:
            _last_pwm = int(current.pwm)
            _last_pwm_change_t = now_mono
        elif int(current.pwm) != int(_last_pwm):
            _last_pwm = int(current.pwm)
            _last_pwm_change_t = now_mono
            _baseline_warn_streak = 0
            _baseline_crit_streak = 0
            _vib_ema_raw = float(current.vibration)

    transient_s = max(0.0, float(NASA_TRANSIENT_SECONDS))
    pwm_transient = (
        current.is_running
        and _last_pwm_change_t is not None
        and (now_mono - float(_last_pwm_change_t)) < transient_s
    )

    if not current.is_running:
        _vib_ema_raw = None
        vib_nasa_raw = float(current.vibration)
        vib_nasa_raw_prev = vib_nasa_raw
    else:
        alpha = max(0.01, min(1.0, float(NASA_VIBRATION_EMA_ALPHA)))
        prev_ema = _vib_ema_raw
        if _vib_ema_raw is None:
            _vib_ema_raw = float(current.vibration)
        else:
            _vib_ema_raw = (1.0 - alpha) * float(_vib_ema_raw) + alpha * float(current.vibration)
        vib_nasa_raw = float(_vib_ema_raw)
        vib_nasa_raw_prev = float(prev_ema) if prev_ema is not None else vib_nasa_raw

    temp_component = 0.0
    if current.is_running and current.temp_c >= temp_warn:
        temp_component = (current.temp_c - temp_warn) / max(1.0, (temp_crit - temp_warn))
        reasons.append("Temperature is high")
        recommendations.append("Check cooling / ventilation; reduce load if needed")

    amps_component = 0.0
    if current.is_running and current.amps >= amps_warn:
        amps_component = (current.amps - amps_warn) / max(1.0, (amps_crit - amps_warn))
        reasons.append("Current is high (possible overload)")
        recommendations.append("Check load, power supply, wiring, and motor driver")

    vib_component = 0.0
    if current.is_running and baseline is None and current.vibration >= vib_warn:
        vib_component = (current.vibration - vib_warn) / max(1.0, (vib_crit - vib_warn))
        reasons.append("Vibration is high (bearing wear / imbalance possible)")
        recommendations.append("Check bearings, mounting, alignment, and balance; reduce PWM/load")

    trend_component = 0.0
    if current.is_running and previous is not None:
        dt = (current.ts - previous.ts).total_seconds()
        if dt >= 0.25:
            temp_rate = (current.temp_c - previous.temp_c) / dt
            amps_rate = (current.amps - previous.amps) / dt
            if temp_rate > 0.06 and (current.temp_c >= temp_warn or previous.temp_c >= temp_warn):
                trend_component = max(trend_component, _clamp01((temp_rate - 0.06) / 0.10))
                reasons.append("Temperature is rising fast")
                recommendations.append("Reduce PWM/load and check cooling")
                if current.temp_c < temp_crit:
                    eta = (temp_crit - current.temp_c) / max(1e-6, temp_rate)
                    if eta > 0:
                        eta_seconds = eta if eta_seconds is None else min(eta_seconds, eta)
                        eta_label = "ETA to critical temperature"
            if amps_rate > 0.01 and (current.amps >= amps_warn or previous.amps >= amps_warn):
                trend_component = max(trend_component, _clamp01((amps_rate - 0.01) / 0.03))
                reasons.append("Current is rising fast")
                recommendations.append("Check overload and reduce PWM/load")
                if current.amps < amps_crit:
                    eta = (amps_crit - current.amps) / max(1e-6, amps_rate)
                    if eta > 0:
                        eta_seconds = eta if eta_seconds is None else min(eta_seconds, eta)
                        eta_label = "ETA to critical current"

    score = _clamp01(max(temp_component, amps_component, vib_component, trend_component))

    baseline_component = 0.0
    if current.is_running and baseline is not None and not pwm_transient:
        feats = extract_features(current=current, previous=previous)
        warn_z = max(0.1, float(NASA_BASELINE_WARN_Z))
        crit_z = max(warn_z + 0.1, float(NASA_BASELINE_CRIT_Z))

        def z(name: str, value: float) -> float | None:
            st = baseline.features.get(name)
            if st is None:
                return None
            if name == "vibration":
                return max(0.0, (value - st.mean) / st.std)
            return abs((value - st.mean) / st.std)

        z_values: list[float] = []
        for name, value in [
            ("temp_c", feats.temp_c),
            ("amps", feats.amps),
            ("vibration", vib_nasa_raw * NASA_VIBRATION_SCALE),
            ("pulse_rate", feats.pulse_rate),
        ]:
            zv = z(name, value)
            if zv is not None:
                z_values.append(zv)

        if z_values:
            z_cur = float(max(z_values))
            baseline_z_max = z_cur

            confirm_n = max(1, int(NASA_BASELINE_CONFIRM_SAMPLES))
            if z_cur >= crit_z:
                _baseline_crit_streak += 1
            else:
                _baseline_crit_streak = 0

            if z_cur >= warn_z:
                _baseline_warn_streak += 1
            else:
                _baseline_warn_streak = 0

            if _baseline_crit_streak >= confirm_n:
                baseline_component = 1.0
            elif _baseline_warn_streak >= confirm_n:
                ratio = (z_cur - warn_z) / max(1e-6, (crit_z - warn_z))
                baseline_component = 0.4 + 0.35 * _clamp01(ratio)
            else:
                baseline_component = 0.0

            if baseline_component > 0.0:
                reasons.append(
                    f"NASA baseline anomaly (z={z_cur:.2f}, confirm={confirm_n}, warn>={warn_z:.1f}, crit>={crit_z:.1f})"
                )
                recommendations.append("Reduce PWM/load and inspect bearings/mounting")

        score = _clamp01(max(score, baseline_component))

    if current.is_running and not pwm_transient:
        vib_ml = float(vib_nasa_raw) * float(NASA_VIBRATION_SCALE)
        s, lvl = score_anomaly(vibration=vib_ml)
        if s is not None and lvl is not None:
            ml_score = float(s)
            if lvl == "critical":
                score = _clamp01(max(score, 1.0))
                reasons.append(f"ML anomaly score is high ({ml_score:.2f})")
                recommendations.append("Stop and inspect bearings/mounting; reduce PWM/load")
            elif lvl == "warning":
                score = _clamp01(max(score, 0.4 + 0.35 * ml_score))
                reasons.append(f"ML anomaly score increased ({ml_score:.2f})")
                recommendations.append("Reduce PWM/load and monitor vibration trend")

    if current.is_running and nasa_rul_active() and not pwm_transient:
        vib_cal = float(vib_nasa_raw) * NASA_VIBRATION_SCALE
        rul = estimate_rul_seconds(vibration=vib_cal)
        if rul is not None:
            if eta_seconds is None or rul < eta_seconds:
                eta_seconds = float(rul)
                eta_label = "Estimated time to failure (NASA IMS)"

            warn_s = max(1.0, float(NASA_RUL_WARN_SECONDS))
            crit_s = max(0.0, min(warn_s, float(NASA_RUL_CRIT_SECONDS)))
            if rul <= crit_s:
                rul_component = 1.0
            elif rul <= warn_s:
                rul_component = _clamp01((warn_s - float(rul)) / max(1.0, (warn_s - crit_s)))
            else:
                rul_component = 0.0

            if rul_component > 0.0:
                mins = int(round(float(rul) / 60.0))
                reasons.append(f"Estimated RUL (NASA IMS): ~{mins} min")
                recommendations.append("Plan maintenance (bearing / vibration inspection)")
                if float(NASA_RUL_AFFECTS_SCORE) >= 0.5:
                    score = _clamp01(max(score, rul_component))

    if score >= 0.75:
        level = "critical"
    elif score >= 0.4:
        level = "warning"
    else:
        level = "normal"

    if not current.is_running:
        score = 0.0
        level = "normal"
        health = 100
        reasons = ["Stopped"]
        recommendations = []
        eta_seconds = None
        eta_label = None
        baseline_z_max = None
    else:
        health = int(round(100 * (1.0 - score)))

    unique_reasons = _dedup(reasons)
    recommendations = _dedup(recommendations)

    return Risk(
        score=score,
        level=level,
        health=health,
        reasons=unique_reasons,
        eta_seconds=float(eta_seconds) if eta_seconds is not None else None,
        eta_label=eta_label,
        recommendations=recommendations,
        baseline_z_max=baseline_z_max,
        ml_score=ml_score,
    )
