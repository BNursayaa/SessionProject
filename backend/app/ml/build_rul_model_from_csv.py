from __future__ import annotations

import argparse
import csv
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


TS_RE = re.compile(r"(?P<ts>\d{4}\.\d{2}\.\d{2}\.\d{2}\.\d{2}\.\d{2})")


def _parse_ims_timestamp(s: str) -> datetime | None:
    """
    IMS files are often named like:
      2003.10.22.12.06.24
    or include the timestamp in the path.
    """
    m = TS_RE.search(s)
    if not m:
        return None
    try:
        return datetime.strptime(m.group("ts"), "%Y.%m.%d.%H.%M.%S")
    except Exception:
        return None


def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    xs2 = sorted(xs)
    n = len(xs2)
    mid = n // 2
    if n % 2 == 1:
        return float(xs2[mid])
    return float((xs2[mid - 1] + xs2[mid]) / 2.0)


def _ema(values: list[float], alpha: float = 0.2) -> list[float]:
    if not values:
        return []
    out: list[float] = []
    s = float(values[0])
    out.append(s)
    for x in values[1:]:
        s = alpha * float(x) + (1.0 - alpha) * s
        out.append(s)
    return out


def _envelope(values: list[float]) -> list[float]:
    out: list[float] = []
    m = -math.inf
    for x in values:
        m = max(m, float(x))
        out.append(m)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Build a simple NASA IMS RUL model from an IMS features CSV")
    p.add_argument("--csv", required=True, help="Input CSV path (from ims_to_features_csv.py)")
    p.add_argument("--out", required=True, help="Output JSON path (nasa_rul_model.json)")
    p.add_argument("--vibration-col", default="vibration", help="Column to use as vibration feature (default: vibration)")
    p.add_argument(
        "--ema-alpha",
        type=float,
        default=0.2,
        help="EMA alpha for smoothing vibration before building a monotonic envelope (0..1).",
    )
    args = p.parse_args()

    in_path = Path(args.csv)
    if not in_path.exists():
        raise SystemExit(f"CSV not found: {in_path}")

    times: list[datetime | None] = []
    vib: list[float] = []
    files: list[str] = []
    with in_path.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            if args.vibration_col not in row:
                continue
            v_raw = row.get(args.vibration_col)
            if v_raw is None or v_raw == "":
                continue
            v = float(v_raw)
            fp = str(row.get("file") or "")
            files.append(fp)
            times.append(_parse_ims_timestamp(fp))
            vib.append(v)

    if len(vib) < 10:
        raise SystemExit(f"Not enough rows ({len(vib)}) in {in_path}. Did you point to the extracted IMS folder?")

    # Build time axis (seconds from start).
    # Prefer parsed timestamps; fallback to uniform 1-step increments.
    t0: datetime | None = None
    parsed_pairs: list[tuple[datetime, float]] = []
    for t, v in zip(times, vib):
        if t is not None:
            parsed_pairs.append((t, v))

    if len(parsed_pairs) >= 10:
        parsed_pairs.sort(key=lambda x: x[0])
        t0 = parsed_pairs[0][0]
        t_seconds = [(t - t0).total_seconds() for t, _ in parsed_pairs]
        vib_series = [v for _, v in parsed_pairs]
        dts = [t_seconds[i] - t_seconds[i - 1] for i in range(1, len(t_seconds)) if t_seconds[i] > t_seconds[i - 1]]
        dt_med = _median(dts)
    else:
        t_seconds = [float(i) for i in range(len(vib))]
        vib_series = vib
        dt_med = None

    vib_smooth = _ema(vib_series, alpha=max(0.01, min(0.99, float(args.ema_alpha))))
    vib_env = _envelope(vib_smooth)
    t_end = float(t_seconds[-1])

    out = {
        "source": "NASA IMS Bearings (derived RUL model)",
        "t_end_seconds": t_end,
        "dt_median_seconds": dt_med,
        "points": [
            {"t_seconds": float(t), "vibration": float(v), "vibration_envelope": float(e)}
            for t, v, e in zip(t_seconds, vib_smooth, vib_env)
        ],
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_path} with {len(t_seconds)} points")


if __name__ == "__main__":
    main()

