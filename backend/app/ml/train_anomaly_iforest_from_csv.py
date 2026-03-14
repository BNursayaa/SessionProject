from __future__ import annotations

import argparse
import csv
import math
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


def _percentile(xs: list[float], q: float) -> float:
    if not xs:
        return math.nan
    xs2 = sorted(xs)
    if q <= 0:
        return float(xs2[0])
    if q >= 100:
        return float(xs2[-1])
    k = (len(xs2) - 1) * (q / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(xs2[int(k)])
    d0 = xs2[int(f)] * (c - k)
    d1 = xs2[int(c)] * (k - f)
    return float(d0 + d1)


def main() -> None:
    p = argparse.ArgumentParser(description="Train an IsolationForest anomaly model from NASA IMS features CSV")
    p.add_argument("--csv", required=True, help="Input CSV path (ims_features.csv)")
    p.add_argument("--out", required=True, help="Output joblib path")
    p.add_argument("--vibration-col", default="vibration", help="Column to use as vibration feature")
    p.add_argument(
        "--train-fraction",
        type=float,
        default=0.2,
        help="Fraction of earliest samples treated as healthy training data (0..1).",
    )
    p.add_argument("--contamination", type=float, default=0.02, help="IsolationForest contamination (0..0.5).")
    p.add_argument("--random-state", type=int, default=42)
    args = p.parse_args()

    in_path = Path(args.csv)
    if not in_path.exists():
        raise SystemExit(f"CSV not found: {in_path}")

    vib: list[float] = []
    times: list[datetime | None] = []
    with in_path.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            v_raw = row.get(args.vibration_col)
            if v_raw is None or v_raw == "":
                continue
            fp = str(row.get("file") or "")
            t = _parse_ims_timestamp(fp)
            if t is None:
                continue
            times.append(t)
            vib.append(float(v_raw))

    if len(vib) < 200:
        raise SystemExit(f"Not enough rows ({len(vib)}) in {in_path}")

    pairs = sorted(zip(times, vib), key=lambda x: x[0])  # type: ignore[index]
    vib_sorted = [float(v) for _, v in pairs]

    frac = max(0.05, min(0.95, float(args.train_fraction)))
    n_train = max(50, int(round(len(vib_sorted) * frac)))
    x_train = [[v] for v in vib_sorted[:n_train]]

    from sklearn.ensemble import IsolationForest  # type: ignore[import-not-found]
    from joblib import dump as joblib_dump  # type: ignore[import-not-found]

    contamination = max(0.0, min(0.5, float(args.contamination)))
    model = IsolationForest(
        n_estimators=300,
        contamination=contamination,
        random_state=int(args.random_state),
    )
    model.fit(x_train)

    decision = model.decision_function(x_train)
    anomaly = [-float(d) for d in decision]
    p95 = _percentile(anomaly, 95.0)
    p99 = _percentile(anomaly, 99.0)

    out = {
        "source": "NASA IMS Bearings (IsolationForest anomaly detector)",
        "vibration_col": str(args.vibration_col),
        "train_fraction": float(frac),
        "contamination": float(contamination),
        "anomaly_p95": float(p95),
        "anomaly_p99": float(p99),
        "model": model,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    joblib_dump(out, out_path)
    print(f"Wrote {out_path} (train_n={n_train}, p95={p95:.6f}, p99={p99:.6f})")


if __name__ == "__main__":
    main()

