from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import csv
import re
import argparse

ROOT = Path(__file__).resolve().parents[1]
INCOMING = ROOT / "workspace" / "incoming"
REPORTS = ROOT / "reports"

SUPPORTED = {".jsonl", ".json", ".csv", ".parquet", ".txt", ".md"}

TEXT_KEYS = (
    "instruction", "input", "output", "prompt", "completion",
    "question", "answer", "text", "content", "anchor",
    "positive", "negative"
)

def fingerprint(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def extract_text(row):
    if isinstance(row, str):
        return row
    if not isinstance(row, dict):
        return ""
    parts = []
    for key in TEXT_KEYS:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
        elif isinstance(value, list):
            parts.extend(
                str(x) for x in value
                if isinstance(x, (str, int, float)) and str(x).strip()
            )
    if isinstance(row.get("messages"), list):
        for msg in row["messages"]:
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str):
                    parts.append(content.strip())
    return "\n".join(parts)

def detect_language(text):
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "unknown"
    devanagari = sum("\u0900" <= c <= "\u097F" for c in letters)
    latin = sum(("a" <= c.lower() <= "z") for c in letters)
    total = len(letters)
    if devanagari / total >= 0.30:
        return "devanagari"
    if latin / total >= 0.60:
        return "latin"
    return "mixed_or_other"

def read_rows(path):
    ext = path.suffix.lower()

    if ext == ".jsonl":
        with path.open("r", encoding="utf-8-sig") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except Exception:
                    yield None

    elif ext == ".json":
        obj = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(obj, list):
            yield from obj
        elif isinstance(obj, dict):
            rows = next(
                (obj[k] for k in ("data", "records", "examples", "items")
                 if isinstance(obj.get(k), list)),
                None
            )
            if rows is None:
                yield obj
            else:
                yield from rows
        else:
            yield obj

    elif ext == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            yield from csv.DictReader(f)

    elif ext == ".parquet":
        import pyarrow.parquet as pq
        pf = pq.ParquetFile(path)
        for batch in pf.iter_batches(batch_size=2048):
            yield from batch.to_pylist()

    elif ext in {".txt", ".md"}:
        content = path.read_text(encoding="utf-8-sig", errors="replace")
        for paragraph in re.split(r"\n\s*\n", content):
            if paragraph.strip():
                yield paragraph.strip()

def inspect_file(path, global_hashes, split_hashes):
    stats = {
        "file": str(path.relative_to(INCOMING)),
        "extension": path.suffix.lower(),
        "size_bytes": path.stat().st_size,
        "records": 0,
        "valid_records": 0,
        "malformed_records": 0,
        "empty_records": 0,
        "duplicate_records": 0,
        "cross_file_duplicates": 0,
        "short_records_under_20_chars": 0,
        "long_records_over_12000_chars": 0,
        "total_characters": 0,
        "language_estimates": Counter(),
        "schema_counts": Counter(),
        "missing_metadata": [],
        "status": "SCANNED",
    }

    name = path.stem.lower()
    split = (
        "train" if "train" in name else
        "validation" if "validation" in name or "valid" in name else
        "test" if "test" in name else
        None
    )

    local_hashes = set()
    local_split_hashes = set()

    try:
        for row in read_rows(path):
            stats["records"] += 1

            if row is None or not isinstance(row, (dict, str)):
                stats["malformed_records"] += 1
                continue

            text = extract_text(row)
            if not text.strip():
                stats["empty_records"] += 1
                continue

            stats["valid_records"] += 1
            length = len(text)
            stats["total_characters"] += length

            if length < 20:
                stats["short_records_under_20_chars"] += 1
            if length > 12000:
                stats["long_records_over_12000_chars"] += 1

            stats["language_estimates"][detect_language(text)] += 1

            if isinstance(row, dict):
                keys = set(row)
                if "messages" in keys:
                    schema = "messages"
                elif {"prompt", "completion"}.issubset(keys):
                    schema = "prompt_completion"
                elif {"question", "answer"}.issubset(keys):
                    schema = "question_answer"
                elif {"instruction", "output"}.issubset(keys):
                    schema = "instruction_output"
                elif {"anchor", "positive", "negative"}.issubset(keys):
                    schema = "contrastive_triplets"
                elif "text" in keys:
                    schema = "text"
                else:
                    schema = "unrecognized"
                stats["schema_counts"][schema] += 1

                if not any(k in keys for k in ("license", "licence")):
                    stats["missing_metadata"].append("license field absent")
                if not any(k in keys for k in ("source", "source_url", "origin")):
                    stats["missing_metadata"].append("source field absent")

            digest = fingerprint(text)
            if digest in local_hashes:
                stats["duplicate_records"] += 1
            local_hashes.add(digest)

            if digest in global_hashes:
                stats["cross_file_duplicates"] += 1
            global_hashes.add(digest)

            if split:
                local_split_hashes.add(digest)
                split_hashes.setdefault(split, set()).add(digest)

    except Exception as exc:
        stats["status"] = "ERROR"
        stats["error"] = f"{type(exc).__name__}: {str(exc)[:250]}"

    stats["average_characters"] = round(
        stats["total_characters"] / max(stats["valid_records"], 1), 2
    )
    stats["language_estimates"] = dict(stats["language_estimates"])
    stats["schema_counts"] = dict(stats["schema_counts"])
    stats["missing_metadata"] = sorted(set(stats["missing_metadata"]))
    return stats

def score_file(item):
    if item["status"] == "ERROR" or item["records"] == 0:
        return 0

    score = 100.0
    total = item["records"]
    valid = item["valid_records"]

    score -= 30 * (item["malformed_records"] / total)
    score -= 20 * (item["empty_records"] / total)
    score -= 20 * (item["duplicate_records"] / total)
    score -= 10 * (item["short_records_under_20_chars"] / max(valid, 1))
    score -= 10 * (item["long_records_over_12000_chars"] / max(valid, 1))

    if item["cross_file_duplicates"]:
        score -= min(15, 15 * item["cross_file_duplicates"] / max(valid, 1))

    if item["valid_records"] and item["schema_counts"].get("unrecognized", 0) == valid:
        score -= 15

    return round(max(0, min(100, score)), 1)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not INCOMING.exists():
        raise SystemExit(f"Incoming folder not found: {INCOMING}")

    files = sorted(
        p for p in INCOMING.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED
    )

    REPORTS.mkdir(parents=True, exist_ok=True)

    global_hashes = set()
    split_hashes = {}
    results = [
        inspect_file(p, global_hashes, split_hashes)
        for p in files
    ]

    for item in results:
        item["quality_score"] = score_file(item)
        score = item["quality_score"]

        if item["status"] == "ERROR":
            item["recommendation"] = "REVIEW_REQUIRED"
        elif score >= 85 and item["valid_records"] > 0:
            item["recommendation"] = "QUALITY_CANDIDATE"
        elif score >= 65 and item["valid_records"] > 0:
            item["recommendation"] = "MANUAL_REVIEW"
        else:
            item["recommendation"] = "QUARANTINE_RECOMMENDED"

    split_overlap = {}
    split_names = list(split_hashes)
    for i, first in enumerate(split_names):
        for second in split_names[i + 1:]:
            overlap = split_hashes[first] & split_hashes[second]
            if overlap:
                split_overlap[f"{first}_vs_{second}"] = len(overlap)

    total_records = sum(x["records"] for x in results)
    total_valid = sum(x["valid_records"] for x in results)

    report = {
        "agent": "EVA Dataset Quality Analyzer",
        "version": "1.0.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "DRY_RUN" if args.dry_run else "READ_ONLY_ANALYSIS",
        "scope": "workspace/incoming ONLY",
        "files_scanned": len(results),
        "total_records": total_records,
        "valid_records": total_valid,
        "malformed_records": sum(x["malformed_records"] for x in results),
        "duplicate_records": sum(x["duplicate_records"] for x in results),
        "cross_file_duplicates": sum(x["cross_file_duplicates"] for x in results),
        "split_overlap": split_overlap,
        "files": results,
        "limitations": [
            "Language identification is a rough script-based estimate, not full language detection.",
            "A quality score is a heuristic, not proof of factual correctness.",
            "License and source metadata must be independently verified.",
            "Split overlap detection relies on filenames containing train, validation, or test.",
            "No files are cleaned, moved, deleted, or used for training."
        ]
    }

    json_path = REPORTS / "quality_report.json"
    md_path = REPORTS / "quality_report.md"

    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    lines = [
        "# EVA Dataset Quality Report",
        "",
        f"- Created: {report['created_at']}",
        f"- Scope: `{report['scope']}`",
        f"- Files scanned: {len(results)}",
        f"- Total records: {total_records}",
        f"- Valid records: {total_valid}",
        f"- Malformed records: {report['malformed_records']}",
        f"- Duplicate records: {report['duplicate_records']}",
        f"- Cross-file duplicates: {report['cross_file_duplicates']}",
        "",
        "## File results",
        "",
        "| File | Records | Valid | Score | Recommendation |",
        "|---|---:|---:|---:|---|"
    ]

    for item in results:
        lines.append(
            f"| {item['file']} | {item['records']} | "
            f"{item['valid_records']} | {item['quality_score']} | "
            f"{item['recommendation']} |"
        )

    lines += ["", "## Train/validation/test overlap", ""]
    if split_overlap:
        for key, value in split_overlap.items():
            lines.append(f"- {key}: {value} duplicate records")
    else:
        lines.append("- No exact overlap detected among recognized split filenames.")

    lines += ["", "## Limitations", ""]
    lines.extend(f"- {x}" for x in report["limitations"])
    lines += [
        "",
        "> Quality scores are heuristic indicators, not proof of correctness or permission to train."
    ]

    md_path.write_text("\n".join(lines), encoding="utf-8")

    print("\n===== EVA DATASET QUALITY REPORT =====")
    print("Files scanned:", len(results))
    print("Total records:", total_records)
    print("Valid records:", total_valid)
    print("Malformed:", report["malformed_records"])
    print("Duplicates:", report["duplicate_records"])
    print("Cross-file duplicates:", report["cross_file_duplicates"])
    print("Split overlap:", split_overlap)
    for item in results:
        print(
            f"{item['quality_score']:5.1f} | "
            f"{item['recommendation']:25} | {item['file']}"
        )
    print("\nJSON:", json_path)
    print("Markdown:", md_path)
    print("Read-only analysis completed. No training was started.")

if __name__ == "__main__":
    main()
