from __future__ import annotations

import argparse
import csv
import re
from datetime import datetime
from pathlib import Path


TS_RE = re.compile(r"(?P<ts>\d{4}\.\d{2}\.\d{2}\.\d{2}\.\d{2}\.\d{2})")


def _parse_ims_timestamp(s: str) -> datetime | None:
    m = TS_RE.search(s)
    if not m:
        return None
    try:
        return datetime.strptime(m.group("ts"), "%Y.%m.%d.%H.%M.%S")
    except Exception:
        return None


def _ema(values: list[float], alpha: float) -> list[float]:
    if not values:
        return []
    out: list[float] = []
    s = float(values[0])
    out.append(s)
    for x in values[1:]:
        s = alpha * float(x) + (1.0 - alpha) * s
        out.append(s)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Train an isotonic RUL model from NASA IMS features CSV")
    p.add_argument("--csv", required=True, help="Input CSV path (ims_features.csv)")
    p.add_argument("--out", required=True, help="Output joblib path")
    p.add_argument("--vibration-col", default="vibration", help="Column used as vibration feature")
    p.add_argument("--ema-alpha", type=float, default=0.2, help="EMA alpha (0..1) used to smooth vibration")
    args = p.parse_args()

    in_path = Path(args.csv)
    if not in_path.exists():
        raise SystemExit(f"CSV not found: {in_path}")

    rows: list[tuple[datetime, float]] = []
    with in_path.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            fp = str(row.get("file") or "")
            t = _parse_ims_timestamp(fp)
            if t is None:
                continue
            v_raw = row.get(args.vibration_col)
            if v_raw is None or v_raw == "":
                continue
            rows.append((t, float(v_raw)))

    if len(rows) < 200:
        raise SystemExit(f"Not enough rows ({len(rows)}) in {in_path}")

    rows.sort(key=lambda x: x[0])
    t0 = rows[0][0]
    t_seconds = [(t - t0).total_seconds() for t, _ in rows]
    vib = [float(v) for _, v in rows]
    alpha = max(0.01, min(0.99, float(args.ema_alpha)))
    vib_smooth = _ema(vib, alpha=alpha)

    t_end = float(t_seconds[-1])
    rul = [max(0.0, t_end - float(t)) for t in t_seconds]

    from sklearn.isotonic import IsotonicRegression  # type: ignore[import-not-found]
    from joblib import dump as joblib_dump  # type: ignore[import-not-found]

    iso = IsotonicRegression(increasing=False, out_of_bounds="clip")
    iso.fit(vib_smooth, rul)

    out = {
        "source": "NASA IMS Bearings (isotonic regression RUL)",
        "vibration_col": str(args.vibration_col),
        "ema_alpha": float(alpha),
        "t_end_seconds": float(t_end),
        "model": iso,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    joblib_dump(out, out_path)
    print(f"Wrote {out_path} (n={len(vib_smooth)}, t_end={t_end:.1f}s)")


if __name__ == "__main__":
    main()

