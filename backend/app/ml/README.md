# ML / NASA comparison (optional)

This backend supports an **optional** NASA-based baseline file:

- `backend/app/ml/nasa_baseline.json`
- enabled via env `DT_NASA_BASELINE_PATH` (or place the file at the default path)

## What is “baseline”

It’s a simple “normal behavior” statistics model built from a reference dataset
(e.g., NASA rotating machinery / bearing dataset):

```json
{
  "features": {
    "temp_c": { "mean": 30.0, "std": 2.0 },
    "amps": { "mean": 0.4, "std": 0.1 },
    "vibration": { "mean": 120.0, "std": 40.0 },
    "pulse_rate": { "mean": 40.0, "std": 8.0 }
  }
}
```

The backend converts your telemetry into features and computes a z-score anomaly level.
This is the simplest defensible “NASA comparison” for an MVP.

## How to build it (recommended workflow)

### Option A (best match for your motor): NASA/IMS Bearings

1) Download and unzip NASA IMS Bearings dataset.
2) Convert raw vibration files to a simple features CSV:

```powershell
python -m app.ml.ims_to_features_csv --dir "C:\\path\\to\\IMS" --out ".\\app\\ml\\ims_features.csv" --feature rms
```

Note: IMS files are often named like `2003.10.22.12.06.24` (numeric suffix), so the converter scans
most file types and skips non-numeric/empty ones automatically.

3) Build baseline JSON using only the `vibration` column:

```powershell
python -m app.ml.build_baseline_from_csv --csv ".\\app\\ml\\ims_features.csv" --out ".\\app\\ml\\nasa_baseline.json" --cols vibration
```

4) Restart backend.

## Calibration note (important)

NASA IMS Bearings vibration features (RMS/peak/kurtosis) are **not** in the same unit as your Arduino
`vibration` (derived from MPU6050 raw accelerometer counts). If you build a baseline from IMS RMS
values, you should set a calibration multiplier:

- `DT_NASA_VIBRATION_SCALE`

Example: if your typical device vibration is ~`327`, and your baseline JSON has `"mean": 0.1486`,
then `0.1486 / 327 ≈ 0.00046`.

## Optional: RUL / ETA model (time-to-failure estimate)

You can also build a simple *Remaining Useful Life* model from the same `ims_features.csv`:

```powershell
python -m app.ml.build_rul_model_from_csv --csv ".\\app\\ml\\ims_features.csv" --out ".\\app\\ml\\nasa_rul_model.json"
```

When `nasa_rul_model.json` exists, the backend estimates `eta_seconds` / `eta_label` as:
**"До отказа (NASA IMS)"** based on vibration alignment to the run-to-failure envelope.

### Option B (any dataset / your own “normal” data)

1) Prepare a CSV with feature columns (example): `temp_c,amps,vibration,pulse_rate`.
2) Run `build_baseline_from_csv.py` to generate `nasa_baseline.json`.
3) Restart backend.
