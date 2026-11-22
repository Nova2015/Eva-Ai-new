import csv
import re
import json
import math
import shlex
import hashlib
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path(r"D:\Eva_Ai_brain\archive")
CSV_FILE = ROOT / "lithium_battery_materials.csv"
CIF_DIR = ROOT / "cif_files"
REPORT_DIR = Path(r"D:\Eva_Ai_brain\eva_dataset_agent\reports")

NUMERIC = [
    "formation_energy_per_atom",
    "energy_per_atom",
    "band_gap",
    "density",
    "volume",
]

REQUIRED_CIF_FIELDS = [
    "_cell_length_a", "_cell_length_b", "_cell_length_c",
    "_cell_angle_alpha", "_cell_angle_beta", "_cell_angle_gamma",
]

def formula_composition(value):
    if not value:
        return None

    value = str(value).strip().strip("'\"")
    matches = re.findall(r"([A-Z][a-z]?)(\d*(?:\.\d+)?)", value)

    if not matches:
        return None

    compact = re.sub(r"\s+", "", value)
    if "".join(a + b for a, b in matches) != compact:
        return None

    result = defaultdict(float)
    for element, count in matches:
        result[element] += float(count or 1)

    total = sum(result.values())
    if total <= 0:
        return None

    return {k: round(v / total, 6) for k, v in result.items()}

def formulas_match(a, b):
    x = formula_composition(a)
    y = formula_composition(b)
    return x is not None and y is not None and x == y

def parse_cif(path):
    result = {
        "file": path.name,
        "valid": True,
        "errors": [],
        "warnings": [],
        "atom_sites": 0,
        "formula": None,
        "cell": {},
        "volume": None,
        "fractional_coordinates_valid": False,
    }

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        result["valid"] = False
        result["errors"].append(f"Read error: {exc}")
        return result

    scalars = {}
    loops = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        if not line or line.startswith("#"):
            i += 1
            continue

        if line.lower() == "loop_":
            i += 1
            headers = []

            while i < len(lines) and lines[i].strip().startswith("_"):
                headers.append(lines[i].strip().split()[0])
                i += 1

            tokens = []
            while i < len(lines):
                current = lines[i].strip()

                if (
                    not current or current.startswith("#")
                    or current.lower() == "loop_"
                    or current.startswith("_")
                    or current.lower().startswith("data_")
                    or current.lower() == "stop_"
                ):
                    break

                try:
                    tokens.extend(shlex.split(current, comments=False))
                except ValueError:
                    result["warnings"].append("Could not tokenize a CIF loop line.")

                i += 1

            if headers:
                width = len(headers)
                if len(tokens) % width != 0:
                    result["warnings"].append(
                        f"Loop token count mismatch: {headers[0]}"
                    )

                rows = [
                    tokens[j:j + width]
                    for j in range(0, len(tokens) - width + 1, width)
                ]
                loops.append((headers, rows))
            continue

        if line.startswith("_"):
            try:
                parts = shlex.split(line, comments=False)
                if len(parts) >= 2:
                    scalars[parts[0]] = parts[1]
            except ValueError:
                result["warnings"].append("Could not parse scalar: " + line[:100])

        i += 1

    result["formula"] = (
        scalars.get("_chemical_formula_sum")
        or scalars.get("_chemical_formula_structural")
    )

    for field in REQUIRED_CIF_FIELDS:
        raw = scalars.get(field)
        try:
            value = float(raw)
            if not math.isfinite(value):
                raise ValueError("Non-finite")
            result["cell"][field] = value
        except (ValueError, TypeError):
            result["errors"].append(f"Missing/invalid {field}")

    for field in REQUIRED_CIF_FIELDS[:3]:
        if field in result["cell"] and result["cell"][field] <= 0:
            result["errors"].append(f"Non-positive {field}")

    for field in REQUIRED_CIF_FIELDS[3:]:
        if field in result["cell"]:
            value = result["cell"][field]
            if not 0 < value < 180:
                result["errors"].append(f"Invalid angle {field}")

    try:
        result["volume"] = float(scalars["_cell_volume"])
        if not math.isfinite(result["volume"]) or result["volume"] <= 0:
            result["errors"].append("Invalid cell volume")
    except (KeyError, ValueError, TypeError):
        result["warnings"].append("Cell volume missing or invalid")

    required_atoms = {
        "_atom_site_fract_x",
        "_atom_site_fract_y",
        "_atom_site_fract_z",
        "_atom_site_type_symbol",
    }

    atom_loop_found = False
    coordinate_errors = 0
    coordinate_outside = 0

    for headers, rows in loops:
        if required_atoms.issubset(set(headers)):
            atom_loop_found = True
            indexes = {name: headers.index(name) for name in required_atoms}

            for row in rows:
                try:
                    x = float(row[indexes["_atom_site_fract_x"]])
                    y = float(row[indexes["_atom_site_fract_y"]])
                    z = float(row[indexes["_atom_site_fract_z"]])

                    if not all(math.isfinite(v) for v in (x, y, z)):
                        raise ValueError("Non-finite coordinate")

                    if any(v < -1e-6 or v >= 1 + 1e-6 for v in (x, y, z)):
                        coordinate_outside += 1

                    result["atom_sites"] += 1
                except (ValueError, IndexError):
                    coordinate_errors += 1

    if not atom_loop_found:
        result["errors"].append("Required atom-site coordinate loop missing")

    if coordinate_errors:
        result["errors"].append(
            f"{coordinate_errors} invalid atom coordinates"
        )

    if coordinate_outside:
        result["warnings"].append(
            f"{coordinate_outside} coordinates outside [0,1); review periodic wrapping"
        )

    result["fractional_coordinates_valid"] = (
        atom_loop_found and result["atom_sites"] > 0 and coordinate_errors == 0
    )

    if result["atom_sites"] == 0:
        result["errors"].append("No valid atom sites found")

    result["valid"] = len(result["errors"]) == 0
    return result

def main():
    if not CSV_FILE.is_file():
        raise FileNotFoundError(CSV_FILE)
    if not CIF_DIR.is_dir():
        raise FileNotFoundError(CIF_DIR)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    with CSV_FILE.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        columns = reader.fieldnames or []

    ids = [r.get("material_id", "").strip() for r in rows]
    counts = Counter(ids)
    unique_ids = set(ids)
    exact_hashes = Counter(
        hashlib.sha256(
            json.dumps(r, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        for r in rows
    )

    repeated_groups = sum(1 for n in counts.values() if n > 1)
    exact_duplicate_rows = sum(n - 1 for n in exact_hashes.values() if n > 1)

    numeric_stats = {}
    for col in NUMERIC:
        values = []
        missing = 0

        for row in rows:
            try:
                v = float(row.get(col, ""))
                if not math.isfinite(v):
                    raise ValueError()
                values.append(v)
            except (ValueError, TypeError):
                missing += 1

        if values:
            mean = sum(values) / len(values)
            variance = sum((v - mean) ** 2 for v in values) / len(values)
            numeric_stats[col] = {
                "count": len(values),
                "missing_or_invalid": missing,
                "min": min(values),
                "max": max(values),
                "mean": mean,
                "std": math.sqrt(variance),
            }

    csv_formula = {}
    for row in rows:
        mid = row.get("material_id", "").strip()
        if mid and mid not in csv_formula:
            csv_formula[mid] = row.get("formula_pretty", "")

    cif_files = sorted(CIF_DIR.glob("*.cif"))
    cif_results = []
    cif_ids = set()
    formula_mismatches = []
    structures = {}

    for path in cif_files:
        mid = path.stem
        cif_ids.add(mid)
        info = parse_cif(path)
        info["material_id"] = mid

        if mid in csv_formula:
            info["csv_formula"] = csv_formula[mid]
            info["formula_matches_csv"] = formulas_match(
                csv_formula[mid], info["formula"]
            )

            if info["formula_matches_csv"] is False:
                formula_mismatches.append({
                    "material_id": mid,
                    "csv_formula": csv_formula[mid],
                    "cif_formula": info["formula"],
                })

        cif_results.append(info)
        structures[mid] = info

    matched = unique_ids & cif_ids
    csv_only = unique_ids - cif_ids
    cif_only = cif_ids - unique_ids

    license_columns = [
        c for c in columns
        if any(k in c.lower() for k in ("license", "licence", "source", "url"))
    ]

    report = {
        "dataset": str(CSV_FILE),
        "read_only": True,
        "csv": {
            "records": len(rows),
            "unique_material_ids": len(unique_ids),
            "missing_material_ids": sum(not x for x in ids),
            "repeated_id_groups": repeated_groups,
            "exact_duplicate_rows": exact_duplicate_rows,
            "numeric_statistics": numeric_stats,
            "columns": columns,
        },
        "cif": {
            "files": len(cif_files),
            "valid_structures": sum(x["valid"] for x in cif_results),
            "invalid_structures": sum(not x["valid"] for x in cif_results),
            "formula_mismatches": formula_mismatches,
            "matched_ids": len(matched),
            "csv_only_ids": len(csv_only),
            "cif_only_ids": len(cif_only),
            "results": cif_results,
        },
        "provenance": {
            "license_or_source_columns": license_columns,
            "license_status": (
                "Metadata columns found; values still require verification"
                if license_columns else
                "No source/license columns found; permission is unverified"
            ),
        },
        "limitations": [
            "This is a basic CIF text integrity check, not a full crystallographic validation.",
            "No bond, symmetry, oxidation-state, or physical-property validation is performed.",
            "Formula comparison is a simple composition comparison.",
            "CSV values appear standardized; original physical units and scaler parameters are not established here.",
            "This report does not establish dataset licensing or scientific correctness.",
        ],
    }

    json_path = REPORT_DIR / "scientific_quality_report.json"
    md_path = REPORT_DIR / "scientific_quality_report.md"

    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    lines = [
        "# Scientific Dataset Quality Report",
        "",
        "## CSV",
        f"- Records: {len(rows)}",
        f"- Unique material IDs: {len(unique_ids)}",
        f"- Repeated ID groups: {repeated_groups}",
        f"- Exact duplicate rows: {exact_duplicate_rows}",
        "",
        "## CIF",
        f"- Files: {len(cif_files)}",
        f"- Valid by basic checks: {report['cif']['valid_structures']}",
        f"- Invalid by basic checks: {report['cif']['invalid_structures']}",
        f"- CSV/CIF matched IDs: {len(matched)}",
        f"- CSV-only IDs: {len(csv_only)}",
        f"- CIF-only IDs: {len(cif_only)}",
        f"- Formula mismatches: {len(formula_mismatches)}",
        "",
        "## Provenance",
        f"- {report['provenance']['license_status']}",
        "",
        "## Limitations",
    ]
    lines.extend("- " + x for x in report["limitations"])
    lines += ["", "## CIF errors and warnings"]

    for item in cif_results:
        if item["errors"] or item["warnings"]:
            lines.append(f"- **{item['file']}**")
            lines.extend("  - ERROR: " + x for x in item["errors"])
            lines.extend("  - WARNING: " + x for x in item["warnings"])

    if formula_mismatches:
        lines += ["", "## Formula mismatches"]
        lines.extend(
            f"- {x['material_id']}: CSV={x['csv_formula']}, CIF={x['cif_formula']}"
            for x in formula_mismatches
        )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("===== SCIENTIFIC DATASET REPORT =====")
    print("CSV records:", len(rows))
    print("Unique IDs:", len(unique_ids))
    print("Repeated ID groups:", repeated_groups)
    print("Exact duplicate rows:", exact_duplicate_rows)
    print("CIF files:", len(cif_files))
    print("Valid CIF basic checks:", report["cif"]["valid_structures"])
    print("Invalid CIF basic checks:", report["cif"]["invalid_structures"])
    print("CSV/CIF matched IDs:", len(matched))
    print("Formula mismatches:", len(formula_mismatches))
    print("License:", report["provenance"]["license_status"])
    print("JSON report:", json_path)
    print("Markdown report:", md_path)
    print("Source CSV and CIF files were not modified.")

if __name__ == "__main__":
    main()
