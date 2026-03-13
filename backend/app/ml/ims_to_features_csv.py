from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except Exception:
        return False


def _read_signal(path: Path) -> list[float]:
    """
    IMS bearing files are typically plain text with whitespace-separated numeric columns.
    This reader is intentionally tolerant:
    - if a row has 2+ numeric tokens, takes the last numeric token as amplitude
    - skips non-numeric rows
    """
    values: list[float] = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            parts = [p for p in line.strip().replace(",", " ").split() if p]
            nums = [float(p) for p in parts if _is_number(p)]
            if len(nums) >= 1:
                values.append(float(nums[-1]))
    return values


@dataclass(frozen=True)
class VibFeatures:
    rms: float
    peak: float
    kurtosis: float


def _kurtosis(values: list[float]) -> float:
    n = len(values)
    if n < 4:
        return 0.0
    mean = sum(values) / n
    m2 = sum((x - mean) ** 2 for x in values) / n
    if m2 <= 0:
        return 0.0
    m4 = sum((x - mean) ** 4 for x in values) / n
    return float(m4 / (m2**2))


def extract_features(values: list[float]) -> VibFeatures:
    if not values:
        return VibFeatures(rms=0.0, peak=0.0, kurtosis=0.0)
    n = len(values)
    rms = math.sqrt(sum(x * x for x in values) / n)
    peak = max(abs(x) for x in values)
    kurt = _kurtosis(values)
    return VibFeatures(rms=float(rms), peak=float(peak), kurtosis=float(kurt))


def main() -> None:
    p = argparse.ArgumentParser(description="Convert NASA IMS Bearings txt files into a features CSV")
    p.add_argument("--dir", required=True, help="Root directory containing IMS txt files (recursive)")
    p.add_argument("--out", required=True, help="Output CSV path")
    p.add_argument(
        "--feature",
        default="rms",
        choices=["rms", "peak", "kurtosis"],
        help="Which single feature to map into the 'vibration' column for baseline building",
    )
    p.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Optional cap for number of files to process (0 = no limit). Useful for quick tests.",
    )
    args = p.parse_args()

    root = Path(args.dir)
    ignore_ext = {
        ".zip",
        ".7z",
        ".rar",
        ".gz",
        ".tar",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".pdf",
        ".md",
        ".json",
        ".yaml",
        ".yml",
        ".py",
        ".exe",
        ".dll",
    }
    files = sorted([fp for fp in root.rglob("*") if fp.is_file() and fp.suffix.lower() not in ignore_ext])
    if not files:
        raise SystemExit(f"No files found under: {root}")
    if args.max_files and args.max_files > 0:
        files = files[: int(args.max_files)]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    processed = 0
    skipped_empty = 0
    skipped_error = 0
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["file", "vibration", "vib_rms", "vib_peak", "vib_kurtosis"])
        w.writeheader()
        for fp in files:
            try:
                values = _read_signal(fp)
            except Exception:
                skipped_error += 1
                continue
            if not values:
                skipped_empty += 1
                continue
            feats = extract_features(values)
            mapped = getattr(feats, args.feature)
            w.writerow(
                {
                    "file": str(fp.relative_to(root)),
                    "vibration": f"{mapped:.10f}",
                    "vib_rms": f"{feats.rms:.10f}",
                    "vib_peak": f"{feats.peak:.10f}",
                    "vib_kurtosis": f"{feats.kurtosis:.10f}",
                }
            )
            processed += 1

    print(
        f"Wrote {out_path} with {processed} rows "
        f"(scanned={len(files)}, skipped_empty={skipped_empty}, skipped_error={skipped_error})"
    )


if __name__ == "__main__":
    main()
