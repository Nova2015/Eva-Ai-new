import csv
import json
import re
import math
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
from fractions import Fraction

import gemmi


ROOT = Path(r"D:\Eva_Ai_brain\archive")
CIF_DIR = ROOT / "cif_files"
CSV_PATH = Path(
    r"D:\Eva_Ai_brain\eva_dataset_agent\workspace\validated\materials_cleaned.csv"
)
REPORT_DIR = Path(r"D:\Eva_Ai_brain\eva_dataset_agent\reports")


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def cif_number(value):
    if value is None:
        raise ValueError("missing numeric value")
    value = str(value).strip().strip("'\"")
    value = re.sub(r"\(\d+\)$", "", value)
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite numeric value")
    return number


def parse_formula(formula):
    if not formula:
        return None

    text = re.sub(r"\s+", "", str(formula))
    tokens = re.findall(r"([A-Z][a-z]?)(\d*(?:\.\d+)?)", text)

    if not tokens:
        return None

    if "".join(el + amount for el, amount in tokens) != text:
        return None

    composition = Counter()

    try:
        for element, amount in tokens:
            composition[element] += Fraction(amount) if amount else Fraction(1)
    except (ValueError, ZeroDivisionError):
        return None

    return {k: v for k, v in composition.items() if v > 0}


def normalized_composition(comp):
    if not comp:
        return None

    values = list(comp.values())
    denominator = 1
    for value in values:
        denominator = math.lcm(denominator, value.denominator)

    integers = [
        int(value * denominator)
        for value in values
    ]

    divisor = math.gcd(*integers)
    return {
        element: amount // divisor
        for element, amount in sorted(comp.items())
    }


def read_csv_index(path):
    index = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            index[row["material_id"].strip()] = row
    return index


def validate_one(path, csv_index):
    result = {
        "file": path.name,
        "material_id": path.stem,
        "parse": "FAIL",
        "checks": {},
        "errors": [],
        "warnings": [],
    }

    try:
        doc = gemmi.cif.read_file(str(path))
        if len(doc) == 0:
            raise ValueError("CIF contains no data blocks")

        block = doc.sole_block()
        result["parse"] = "PASS"
        result["block_name"] = block.name

        # Cell parameters
        cell_tags = [
            "_cell_length_a",
            "_cell_length_b",
            "_cell_length_c",
            "_cell_angle_alpha",
            "_cell_angle_beta",
            "_cell_angle_gamma",
        ]

        cell = {}
        for tag in cell_tags:
            try:
                cell[tag] = cif_number(block.find_value(tag))
            except Exception as exc:
                result["errors"].append(f"{tag}: {exc}")

        if len(cell) == 6:
            lengths_ok = all(
                cell[tag] > 0
                for tag in cell_tags[:3]
            )
            angles_ok = all(
                0 < cell[tag] < 180
                for tag in cell_tags[3:]
            )
            result["checks"]["cell_parameters"] = (
                "PASS" if lengths_ok and angles_ok else "FAIL"
            )
            result["cell"] = cell
        else:
            result["checks"]["cell_parameters"] = "FAIL"

        # Atom-site data
        symbols = list(block.find_values("_atom_site_type_symbol"))
        xs = list(block.find_values("_atom_site_fract_x"))
        ys = list(block.find_values("_atom_site_fract_y"))
        zs = list(block.find_values("_atom_site_fract_z"))

        atom_checks = (
            len(symbols) > 0
            and len(symbols) == len(xs) == len(ys) == len(zs)
        )

        if atom_checks:
            for symbol in symbols:
                if not re.fullmatch(r"[A-Z][a-z]?", str(symbol).strip()):
                    atom_checks = False
                    result["errors"].append(
                        f"Invalid atom element symbol: {symbol}"
                    )

            for values in (xs, ys, zs):
                for value in values:
                    try:
                        cif_number(value)
                    except Exception:
                        atom_checks = False
                        result["errors"].append(
                            f"Invalid fractional coordinate: {value}"
                        )

        result["checks"]["atomic_coordinates"] = (
            "PASS" if atom_checks else "FAIL"
        )
        result["atom_site_rows"] = len(symbols)
        result["elements_in_atom_sites"] = sorted(
            set(str(s).strip() for s in symbols)
        )

        # Formula comparison
        csv_row = csv_index.get(path.stem)

        if csv_row is None:
            result["checks"]["csv_formula_match"] = "NO_CSV_RECORD"
        else:
            csv_formula = csv_row.get("formula_pretty", "")
            cif_formula = (
                block.find_value("_chemical_formula_structural")
                or block.find_value("_chemical_formula_sum")
            )

            csv_comp = parse_formula(csv_formula)
            cif_comp = parse_formula(cif_formula)

            if csv_comp is None or cif_comp is None:
                result["checks"]["csv_formula_match"] = "UNVERIFIED"
                result["warnings"].append(
                    "Formula syntax not supported by simple formula parser"
                )
            else:
                matches = (
                    normalized_composition(csv_comp)
                    == normalized_composition(cif_comp)
                )
                result["checks"]["csv_formula_match"] = (
                    "PASS" if matches else "FAIL"
                )
                result["csv_formula"] = csv_formula
                result["cif_formula"] = cif_formula

        # CIF file-level checks
        result["checks"]["overall_basic"] = (
            "PASS"
            if result["parse"] == "PASS"
            and result["checks"].get("cell_parameters") == "PASS"
            and result["checks"].get("atomic_coordinates") == "PASS"
            and result["checks"].get("csv_formula_match") == "PASS"
            else "REVIEW"
        )

    except Exception as exc:
        result["errors"].append(
            f"{type(exc).__name__}: {exc}"
        )

    return result


def main():
    if not CIF_DIR.is_dir():
        raise FileNotFoundError(CIF_DIR)
    if not CSV_PATH.is_file():
        raise FileNotFoundError(CSV_PATH)

    csv_index = read_csv_index(CSV_PATH)
    cif_files = sorted(CIF_DIR.glob("*.cif"))

    results = [
        validate_one(path, csv_index)
        for path in cif_files
    ]

    counts = Counter(
        item["checks"].get("overall_basic", "FAIL")
        for item in results
    )

    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "gemmi_version": gemmi.__version__,
        "csv_path": str(CSV_PATH),
        "csv_sha256": sha256(CSV_PATH),
        "cif_directory": str(CIF_DIR),
        "cif_file_count": len(cif_files),
        "csv_material_count": len(csv_index),
        "overall_counts": dict(counts),
        "passed": sum(
            r["checks"].get("overall_basic") == "PASS"
            for r in results
        ),
        "review": sum(
            r["checks"].get("overall_basic") == "REVIEW"
            for r in results
        ),
        "results": results,
        "limitations": [
            "This is basic CIF parsing and consistency validation.",
            "It does not prove physical correctness or experimental validity.",
            "It does not perform full symmetry expansion or bonding validation.",
            "Formula comparison supports simple element-count formulas only.",
            "A PASS is not approval for model training."
        ],
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "gemmi_crystal_validation.json"
    summary = REPORT_DIR / "gemmi_crystal_validation_summary.md"

    out.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    lines = [
        "# EVA Gemmi Crystal Validation",
        "",
        f"- Gemmi: {gemmi.__version__}",
        f"- CIF files: {len(cif_files)}",
        f"- PASS: {report['passed']}",
        f"- REVIEW: {report['review']}",
        "",
        "## Per-file results",
    ]

    for item in results:
        lines.append(
            f"- {item['file']}: "
            f"{item['checks'].get('overall_basic', 'FAIL')} "
            f"(parse={item['parse']}, "
            f"cell={item['checks'].get('cell_parameters')}, "
            f"atoms={item['checks'].get('atomic_coordinates')}, "
            f"formula={item['checks'].get('csv_formula_match')})"
        )

    lines.extend([
        "",
        "## Limitations",
        *[f"- {x}" for x in report["limitations"]],
    ])

    summary.write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps({
        "cif_files": len(cif_files),
        "passed": report["passed"],
        "review": report["review"],
        "report": str(out),
        "summary": str(summary),
    }, indent=2))

    print("\nPER-FILE RESULTS")
    for item in results:
        print(
            item["file"],
            item["checks"].get("overall_basic", "FAIL"),
            item["checks"]
        )


if __name__ == "__main__":
    main()
