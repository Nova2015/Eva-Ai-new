import csv
import json
import math
import hashlib
from pathlib import Path
from datetime import datetime, timezone

import numpy as np

ROOT = Path(r"D:\Eva_Ai_brain\eva_dataset_agent")
SPLIT_DIR = ROOT / "workspace" / "baseline_splits"
OUT = ROOT / "workspace" / "baseline_preprocessing"

FEATURES = [
    "formation_energy_per_atom",
    "energy_per_atom",
    "density",
    "volume",
    "n_elements",
    "contains_transition_metal",
]
TARGET = "band_gap"
SPLITS = ("train", "validation", "test")

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def load_split(name):
    path = SPLIT_DIR / f"materials_{name}.csv"
    if not path.exists():
        raise SystemExit(f"BLOCK: Missing split file: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        raise SystemExit(f"BLOCK: Empty split: {name}")

    X, y = [], []
    for line, row in enumerate(rows, start=2):
        values = []
        for col in FEATURES:
            raw = (row.get(col) or "").strip()
            if col == "contains_transition_metal":
                if raw.lower() in ("true", "1"):
                    value = 1.0
                elif raw.lower() in ("false", "0"):
                    value = 0.0
                else:
                    raise SystemExit(
                        f"BLOCK: Invalid boolean in {name}, line {line}: {raw!r}"
                    )
            else:
                try:
                    value = float(raw)
                except ValueError:
                    raise SystemExit(
                        f"BLOCK: Invalid numeric {col} in {name}, line {line}"
                    )
            if not math.isfinite(value):
                raise SystemExit(
                    f"BLOCK: Non-finite {col} in {name}, line {line}"
                )
            values.append(value)

        try:
            target = float(row[TARGET])
        except (ValueError, TypeError):
            raise SystemExit(f"BLOCK: Invalid target in {name}, line {line}")

        if not math.isfinite(target):
            raise SystemExit(f"BLOCK: Non-finite target in {name}, line {line}")

        X.append(values)
        y.append(target)

    return rows, np.asarray(X, dtype=np.float64), np.asarray(y, dtype=np.float64)

def metrics(y_true, y_pred):
    errors = y_true - y_pred
    mae = np.mean(np.abs(errors))
    rmse = np.sqrt(np.mean(errors ** 2))
    ss_res = np.sum(errors ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return {
        "mae": float(mae),
        "rmse": float(rmse),
        "r2": float(r2),
    }

class LocalStandardScaler:
    def fit_transform(self, X):
        self.mean_ = np.mean(X, axis=0)
        self.scale_ = np.std(X, axis=0)
        self.scale_[self.scale_ == 0] = 1.0
        return (X - self.mean_) / self.scale_

    def transform(self, X):
        return (X - self.mean_) / self.scale_

def main():
    if OUT.exists() and any(OUT.iterdir()):
        raise SystemExit(f"BLOCK: Output folder is not empty: {OUT}")

    loaded = {name: load_split(name) for name in SPLITS}
    train_rows, X_train, y_train = loaded["train"]

    scaler = LocalStandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)

    transformed = {"train": X_train_scaled}
    for name in ("validation", "test"):
        transformed[name] = scaler.transform(loaded[name][1])

    OUT.mkdir(parents=True, exist_ok=True)

    for name in SPLITS:
        rows = loaded[name][0]
        X_scaled = transformed[name]
        path = OUT / f"materials_{name}_scaled.csv"

        fieldnames = list(rows[0].keys()) + [
            f"{col}_scaled" for col in FEATURES
        ]

        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row, values in zip(rows, X_scaled):
                output_row = dict(row)
                for col, value in zip(FEATURES, values):
                    output_row[f"{col}_scaled"] = float(value)
                writer.writerow(output_row)

    train_mean = float(np.mean(y_train))
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "features": FEATURES,
        "target": TARGET,
        "target_units": "UNVERIFIED; retained source standardized values",
        "feature_scaler": {
            "type": "StandardScaler",
            "fit_on": "train_only",
            "mean": scaler.mean_.tolist(),
            "scale": scaler.scale_.tolist(),
        },
        "target_scaling": "No additional target scaling",
        "baseline": {
            "type": "constant train-target-mean predictor",
            "train_target_mean": train_mean,
            "metrics": {},
        },
        "split_files": {},
        "training_authorized": False,
        "limitations": [
            "This is a mean-predictor baseline, not a trained ML model.",
            "Target physical units and provenance remain unverified.",
            "Feature scaling does not establish scientific validity.",
        ],
    }

    for name in SPLITS:
        y = loaded[name][2]
        prediction = np.full(len(y), train_mean, dtype=np.float64)
        report["baseline"]["metrics"][name] = metrics(y, prediction)

        path = OUT / f"materials_{name}_scaled.csv"
        report["split_files"][name] = {
            "rows": len(y),
            "sha256": sha256(path),
        }

    (OUT / "preprocessing_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )

    print("BASELINE PREPROCESSING COMPLETE")
    for name in SPLITS:
        m = report["baseline"]["metrics"][name]
        print(
            f"{name}: rows={len(loaded[name][2])}, "
            f"MAE={m['mae']:.6f}, RMSE={m['rmse']:.6f}, R2={m['r2']:.6f}"
        )
    print(f"Output: {OUT}")
    print("Scaler fit: TRAIN ONLY")
    print("Training authorized: NO")

if __name__ == "__main__":
    main()

