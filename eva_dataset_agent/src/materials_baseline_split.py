import csv
import json
import hashlib
import random
import math
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

ROOT = Path(r"D:\Eva_Ai_brain")
SOURCE = ROOT / "eva_dataset_agent" / "workspace" / "validated" / "materials_cleaned.csv"
OUT = ROOT / "eva_dataset_agent" / "workspace" / "baseline_splits"

SEED = 42
GROUP_COLUMN = "formula_pretty"
ID_COLUMN = "material_id"
TARGET = "band_gap"

FEATURES = [
    "formation_energy_per_atom",
    "energy_per_atom",
    "density",
    "volume",
    "n_elements",
    "contains_transition_metal",
]

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def main():
    if not SOURCE.exists():
        raise SystemExit(f"BLOCK: Source not found: {SOURCE}")

    if OUT.exists() and any(OUT.iterdir()):
        raise SystemExit(
            f"BLOCK: Output folder is not empty: {OUT}\n"
            "Do not overwrite existing split files."
        )

    required = [ID_COLUMN, GROUP_COLUMN, TARGET] + FEATURES
    rows = []
    seen_ids = set()
    groups = defaultdict(list)

    with SOURCE.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in required if c not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit(f"BLOCK: Missing columns: {missing}")

        for line, row in enumerate(reader, start=2):
            mid = (row.get(ID_COLUMN) or "").strip()
            formula = (row.get(GROUP_COLUMN) or "").strip()

            if not mid or not formula:
                raise SystemExit(f"BLOCK: Missing ID/formula at CSV line {line}")

            if mid in seen_ids:
                raise SystemExit(f"BLOCK: Duplicate material_id: {mid}")

            seen_ids.add(mid)

            for col in [TARGET] + FEATURES:
                value = (row.get(col) or "").strip()

                if col == "contains_transition_metal":
                    if value.lower() not in ("true", "false", "1", "0"):
                        raise SystemExit(
                            f"BLOCK: Invalid boolean {col} at CSV line {line}: {value!r}"
                        )
                    continue

                try:
                    number = float(value)
                except ValueError:
                    raise SystemExit(
                        f"BLOCK: Non-numeric {col} at CSV line {line}: {value!r}"
                    )
                if not math.isfinite(number):
                    raise SystemExit(
                        f"BLOCK: Non-finite {col} at CSV line {line}"
                    )

            rows.append(row)
            groups[formula].append(row)

    if not rows:
        raise SystemExit("BLOCK: No records found.")

    # Deterministic grouping: identical formula groups never cross splits.
    group_names = sorted(groups)
    rng = random.Random(SEED)
    rng.shuffle(group_names)

    n = len(group_names)
    n_train = int(n * 0.80)
    n_val = int(n * 0.10)

    train_groups = set(group_names[:n_train])
    val_groups = set(group_names[n_train:n_train + n_val])
    test_groups = set(group_names[n_train + n_val:])

    assignments = {
        "train": train_groups,
        "validation": val_groups,
        "test": test_groups,
    }

    split_rows = {
        name: [r for r in rows if r[GROUP_COLUMN].strip() in group_set]
        for name, group_set in assignments.items()
    }

    # Verify group isolation.
    group_sets = {
        name: {r[GROUP_COLUMN].strip() for r in data}
        for name, data in split_rows.items()
    }
    if (group_sets["train"] & group_sets["validation"] or
        group_sets["train"] & group_sets["test"] or
        group_sets["validation"] & group_sets["test"]):
        raise SystemExit("BLOCK: Formula leakage detected.")

    OUT.mkdir(parents=True, exist_ok=True)

    results = {}
    for name, data in split_rows.items():
        path = OUT / f"materials_{name}.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=required + [
                c for c in rows[0].keys() if c not in required
            ])
            writer.writeheader()
            writer.writerows(data)

        targets = [float(r[TARGET]) for r in data]
        results[name] = {
            "rows": len(data),
            "formula_groups": len(group_sets[name]),
            "target_mean": sum(targets) / len(targets) if targets else None,
            "target_min": min(targets) if targets else None,
            "target_max": max(targets) if targets else None,
            "sha256": sha256(path),
            "file": str(path),
        }

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source": str(SOURCE),
        "source_sha256": sha256(SOURCE),
        "source_rows": len(rows),
        "unique_material_ids": len(seen_ids),
        "unique_formula_groups": len(groups),
        "seed": SEED,
        "group_column": GROUP_COLUMN,
        "target": TARGET,
        "target_units": "UNVERIFIED; values appear standardized",
        "features": FEATURES,
        "excluded_target_derived_feature": "is_semiconductor",
        "split_method": "deterministic formula-group split",
        "requested_group_ratios": {
            "train": 0.80,
            "validation": 0.10,
            "test": 0.10,
        },
        "splits": results,
        "formula_leakage_check": "PASS",
        "training_authorized": False,
        "limitations": [
            "This creates splits only; it does not train a model.",
            "Formula grouping does not guarantee independence of related materials.",
            "Target units and original scaler parameters remain unverified.",
            "No target stratification is performed.",
        ],
    }

    manifest_path = OUT / "baseline_split_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8"
    )

    print("BASELINE SPLIT CREATED")
    print("Source rows:", len(rows))
    print("Unique formula groups:", len(groups))
    for name, info in results.items():
        print(
            f"{name}: rows={info['rows']}, "
            f"groups={info['formula_groups']}, "
            f"target_mean={info['target_mean']:.5f}"
        )
    print("Formula leakage check: PASS")
    print("Manifest:", manifest_path)
    print("Training authorized: NO")

if __name__ == "__main__":
    main()

