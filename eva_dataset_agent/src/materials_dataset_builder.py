import argparse
import hashlib
import json
import math
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd


ROOT = Path(r"D:\Eva_Ai_brain\archive")
CSV_PATH = ROOT / "lithium_battery_materials.csv"
CIF_DIR = ROOT / "cif_files"

AGENT = Path(r"D:\Eva_Ai_brain\eva_dataset_agent")
VALIDATED = AGENT / "workspace" / "validated"
REJECTED = AGENT / "workspace" / "rejected"
MANIFESTS = AGENT / "workspace" / "manifests"
REPORTS = AGENT / "reports"

REQUIRED = [
    "material_id",
    "formula_pretty",
    "n_elements",
    "formation_energy_per_atom",
    "energy_per_atom",
    "band_gap",
    "density",
    "volume",
]

NUMERIC = [
    "n_elements",
    "formation_energy_per_atom",
    "energy_per_atom",
    "band_gap",
    "density",
    "volume",
]


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def build(write=False):
    if not CSV_PATH.is_file():
        raise FileNotFoundError(f"CSV not found: {CSV_PATH}")

    # Read all fields as text: preserve original stored values.
    df = pd.read_csv(CSV_PATH, dtype=str, keep_default_na=False)

    missing_columns = [c for c in REQUIRED if c not in df.columns]
    if missing_columns:
        raise ValueError(f"Missing required columns: {missing_columns}")

    original_rows = len(df)
    original_columns = list(df.columns)

    # Identify missing material IDs.
    id_text = df["material_id"].astype(str).str.strip()
    missing_id_mask = id_text.eq("")

    rejected_parts = []
    if missing_id_mask.any():
        missing_ids = df.loc[missing_id_mask].copy()
        missing_ids["rejection_reason"] = "missing_material_id"
        rejected_parts.append(missing_ids)

    valid_id_df = df.loc[~missing_id_mask].copy()

    # Identify material IDs with conflicting records.
    # Exact repeated rows are allowed; different rows for the same ID
    # are quarantined together.
    row_hashes = pd.util.hash_pandas_object(
        valid_id_df[original_columns], index=False
    ).astype(str)

    temp = valid_id_df[["material_id"]].copy()
    temp["_row_hash"] = row_hashes.values

    unique_variants = temp.groupby("material_id")["_row_hash"].nunique()
    conflict_ids = set(unique_variants[unique_variants > 1].index)

    conflict_mask = valid_id_df["material_id"].isin(conflict_ids)

    if conflict_mask.any():
        conflicts = valid_id_df.loc[conflict_mask].copy()
        conflicts["rejection_reason"] = "conflicting_rows_for_material_id"
        rejected_parts.append(conflicts)

    candidates = valid_id_df.loc[~conflict_mask].copy()

    # Validate required fields and numeric values without changing source values.
    invalid_reasons = {}

    for idx, row in candidates.iterrows():
        reasons = []

        if not str(row["formula_pretty"]).strip():
            reasons.append("missing_formula")

        for col in NUMERIC:
            raw = str(row[col]).strip()
            try:
                value = float(raw)
                if not math.isfinite(value):
                    reasons.append(f"non_finite_{col}")
            except (TypeError, ValueError):
                reasons.append(f"invalid_numeric_{col}")

        if reasons:
            invalid_reasons[idx] = ";".join(reasons)

    invalid_mask = candidates.index.isin(invalid_reasons.keys())

    if invalid_mask.any():
        invalid = candidates.loc[invalid_mask].copy()
        invalid["rejection_reason"] = [
            invalid_reasons[i] for i in invalid.index
        ]
        rejected_parts.append(invalid)

    accepted = candidates.loc[~invalid_mask].copy()

    # All remaining rows have exactly one distinct full record per material ID.
    accepted = accepted.drop_duplicates(subset=original_columns, keep="first")

    # CIF matching is an inventory check only. No CIF is parsed or copied.
    cif_files = sorted(CIF_DIR.glob("*.cif")) if CIF_DIR.is_dir() else []
    cif_ids = {p.stem for p in cif_files}
    accepted_ids = set(accepted["material_id"].astype(str))

    matched_cif_ids = sorted(accepted_ids & cif_ids)
    cif_without_csv = sorted(cif_ids - accepted_ids)
    materials_without_cif = len(accepted_ids - cif_ids)

    rejected = (
        pd.concat(rejected_parts, ignore_index=True)
        if rejected_parts
        else pd.DataFrame(columns=original_columns + ["rejection_reason"])
    )

    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "write" if write else "dry_run",
        "source_csv": str(CSV_PATH),
        "source_csv_sha256": sha256(CSV_PATH),
        "source_cif_directory": str(CIF_DIR),
        "source_rows": original_rows,
        "source_columns": original_columns,
        "accepted_unique_materials": len(accepted),
        "rejected_rows": len(rejected),
        "missing_material_id_rows": int(missing_id_mask.sum()),
        "conflicting_material_ids": len(conflict_ids),
        "exact_duplicate_rows_removed": original_rows
            - int(missing_id_mask.sum())
            - len(valid_id_df.loc[conflict_mask])
            - len(candidates.loc[invalid_mask])
            - len(accepted),
        "cif_files_found": len(cif_files),
        "cif_ids_matching_accepted_materials": len(matched_cif_ids),
        "accepted_materials_without_cif": materials_without_cif,
        "cif_files_without_accepted_csv_record": len(cif_without_csv),
        "cif_validation": "filename matching only; no crystallographic validation",
        "numeric_units": "unverified; source values preserved unchanged",
        "dataset_license": "unverified",
        "training_authorized": False,
    }

    print(json.dumps(report, indent=2, ensure_ascii=False))

    if not write:
        print("\nDRY RUN: no output files written.")
        return

    for folder in (VALIDATED, REJECTED, MANIFESTS, REPORTS):
        folder.mkdir(parents=True, exist_ok=True)

    clean_path = VALIDATED / "materials_cleaned.csv"
    rejected_path = REJECTED / "materials_rejected.csv"
    manifest_path = MANIFESTS / "materials_manifest.json"
    report_json = REPORTS / "materials_build_report.json"
    report_md = REPORTS / "materials_build_report.md"

    accepted.to_csv(clean_path, index=False)
    rejected.to_csv(rejected_path, index=False)

    manifest = {
        **report,
        "cleaned_csv": str(clean_path),
        "cleaned_csv_sha256": sha256(clean_path),
        "rejected_csv": str(rejected_path),
        "rejected_csv_sha256": sha256(rejected_path),
        "matched_cif_ids": matched_cif_ids,
        "cif_without_accepted_csv_ids": cif_without_csv,
        "source_cif_files": [p.name for p in cif_files],
    }

    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    report_json.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    lines = [
        "# EVA Materials Dataset Build Report",
        "",
        f"- Mode: {report['mode']}",
        f"- Source rows: {original_rows}",
        f"- Accepted unique materials: {len(accepted)}",
        f"- Rejected rows: {len(rejected)}",
        f"- Conflicting material IDs: {len(conflict_ids)}",
        f"- CIF files found: {len(cif_files)}",
        f"- CIF filename matches: {len(matched_cif_ids)}",
        f"- Materials without CIF: {materials_without_cif}",
        "",
        "## Important limitations",
        "- Original numeric values were preserved without unit conversion.",
        "- Physical units and dataset license remain unverified.",
        "- CIF check only compares filenames with material IDs.",
        "- This output is not approved for model training yet.",
    ]

    report_md.write_text("\n".join(lines), encoding="utf-8")

    print("\nOUTPUTS CREATED:")
    print(clean_path)
    print(rejected_path)
    print(manifest_path)
    print(report_json)
    print(report_md)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write derived outputs; never modifies source files."
    )
    args = parser.parse_args()
    build(write=args.write)

