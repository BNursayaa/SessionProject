from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Stats:
    n: int = 0
    mean: float = 0.0
    m2: float = 0.0

    def add(self, x: float) -> None:
        self.n += 1
        delta = x - self.mean
        self.mean += delta / self.n
        delta2 = x - self.mean
        self.m2 += delta * delta2

    def std(self) -> float:
        if self.n < 2:
            return 1.0
        return math.sqrt(self.m2 / (self.n - 1))


def main() -> None:
    p = argparse.ArgumentParser(description="Build NASA baseline stats JSON from a CSV file")
    p.add_argument("--csv", required=True, help="Input CSV path")
    p.add_argument("--out", required=True, help="Output JSON path (nasa_baseline.json)")
    p.add_argument("--cols", default="temp_c,amps,vibration,pulse_rate", help="Comma-separated feature columns")
    args = p.parse_args()

    cols = [c.strip() for c in args.cols.split(",") if c.strip()]
    stats = {c: Stats() for c in cols}

    with open(args.csv, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            for c in cols:
                if c not in row or row[c] in ("", None):
                    continue
                stats[c].add(float(row[c]))

    out = {
        "features": {c: {"mean": stats[c].mean, "std": stats[c].std()} for c in cols},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()

