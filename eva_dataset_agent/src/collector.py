from pathlib import Path
from collections import Counter
import hashlib
import json
import csv
import argparse
from datetime import datetime, timezone

AGENT_ROOT = Path(__file__).resolve().parents[1]
INCOMING = AGENT_ROOT / "workspace" / "incoming"
REPORTS = AGENT_ROOT / "reports"

SUPPORTED = {".jsonl", ".json", ".csv", ".parquet", ".txt", ".md"}

SCHEMAS = [
    {"instruction", "input", "output"},
    {"instruction", "output"},
    {"prompt", "completion"},
    {"question", "answer"},
    {"messages"},
    {"text"},
    {"anchor", "positive", "negative"},
]

def sha256_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def classify(row):
    if not isinstance(row, dict):
        return "unrecognized"
    keys = set(row.keys())
    for schema in SCHEMAS:
        if schema.issubset(keys):
            if schema == {"anchor", "positive", "negative"}:
                return "contrastive_triplets"
            return "instruction_or_text"
    return "unrecognized"

def inspect_rows(rows):
    total = valid = malformed = 0
    duplicates = 0
    seen = set()
    schemas = Counter()
    samples = []

    for row in rows:
        total += 1
        if not isinstance(row, dict):
            malformed += 1
            continue

        kind = classify(row)
        schemas[kind] += 1

        if kind == "unrecognized":
            continue

        values = [str(v).strip() for v in row.values() if v is not None]
        if not values or not any(values):
            malformed += 1
            continue

        valid += 1
        fingerprint = sha256_text(
            json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
        )

        if fingerprint in seen:
            duplicates += 1
        seen.add(fingerprint)

        if len(samples) < 2:
            samples.append({
                "type": kind,
                "keys": list(row.keys())[:20]
            })

    return {
        "records": total,
        "valid_records": valid,
        "malformed_records": malformed,
        "duplicate_records": duplicates,
        "schema_counts": dict(schemas),
        "samples": samples,
    }

def read_jsonl(path):
    def generate():
        with path.open("r", encoding="utf-8-sig") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except Exception:
                    yield None
    return inspect_rows(generate())

def read_json(path):
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(obj, list):
        rows = obj
    elif isinstance(obj, dict):
        rows = None
        for key in ("data", "records", "examples", "items"):
            if isinstance(obj.get(key), list):
                rows = obj[key]
                break
        if rows is None:
            rows = [obj]
    else:
        rows = [obj]
    return inspect_rows(rows)

def read_csv(path):
    def generate():
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            yield from reader
    return inspect_rows(generate())

def read_parquet(path):
    import pyarrow.parquet as pq
    parquet = pq.ParquetFile(path)

    def generate():
        for batch in parquet.iter_batches(batch_size=4096):
            for row in batch.to_pylist():
                yield row

    result = inspect_rows(generate())
    result["columns"] = parquet.schema.names
    result["row_groups"] = parquet.num_row_groups
    return result

def read_text(path):
    content = path.read_text(encoding="utf-8-sig", errors="replace")
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    hashes = [sha256_text(p) for p in paragraphs]
    return {
        "records": len(paragraphs),
        "valid_records": sum(bool(p.strip()) for p in paragraphs),
        "malformed_records": 0,
        "duplicate_records": len(hashes) - len(set(hashes)),
        "schema_counts": {"document_paragraphs": len(paragraphs)},
        "samples": [{"preview": p[:160]} for p in paragraphs[:2]],
        "characters": len(content),
    }

def inspect_file(path):
    ext = path.suffix.lower()
    result = {
        "file": str(path.relative_to(INCOMING)),
        "extension": ext,
        "size_bytes": path.stat().st_size,
        "status": "SCANNED",
    }

    try:
        if ext == ".jsonl":
            details = read_jsonl(path)
        elif ext == ".json":
            details = read_json(path)
        elif ext == ".csv":
            details = read_csv(path)
        elif ext == ".parquet":
            details = read_parquet(path)
        elif ext in {".txt", ".md"}:
            details = read_text(path)
        else:
            return result

        result.update(details)

        if details.get("valid_records", 0) > 0:
            result["decision"] = "CANDIDATE"
        elif ext in {".txt", ".md"} and details.get("records", 0) > 0:
            result["decision"] = "DOCUMENT_CANDIDATE"
        else:
            result["decision"] = "REVIEW_REQUIRED"

    except Exception as exc:
        result["status"] = "ERROR"
        result["decision"] = "REVIEW_REQUIRED"
        result["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"

    return result

def main():
    parser = argparse.ArgumentParser(
        description="EVA Dataset Agent - incoming-only read-only collector"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not INCOMING.exists():
        raise SystemExit(f"Incoming folder not found: {INCOMING}")

    files = sorted(
        p for p in INCOMING.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED
    )

    results = [inspect_file(p) for p in files]

    report = {
        "agent": "EVA Dataset Agent",
        "version": "1.0.0",
        "mode": "DRY_RUN" if args.dry_run else "SCAN_ONLY",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_scope": "workspace/incoming ONLY",
        "source_root": str(INCOMING),
        "source_files_found": len(files),
        "files": results,
        "summary": {
            "candidate_files": sum(
                r.get("decision") in {"CANDIDATE", "DOCUMENT_CANDIDATE"}
                for r in results
            ),
            "review_required": sum(
                r.get("decision") == "REVIEW_REQUIRED" for r in results
            ),
            "errors": sum(r.get("status") == "ERROR" for r in results),
            "records": sum(r.get("records", 0) for r in results),
            "valid_records": sum(r.get("valid_records", 0) for r in results),
        },
    }

    REPORTS.mkdir(parents=True, exist_ok=True)
    output = REPORTS / "incoming_scan_report.json"
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("\n===== EVA DATASET AGENT =====")
    print("Mode:", report["mode"])
    print("Scope: incoming folder ONLY")
    print("Files found:", len(files))
    print("Candidate files:", report["summary"]["candidate_files"])
    print("Review required:", report["summary"]["review_required"])
    print("Errors:", report["summary"]["errors"])
    print("Records:", report["summary"]["records"])
    print("Valid records:", report["summary"]["valid_records"])

    for item in results:
        print(
            f'{item["decision"]:18} '
            f'{item["file"]} '
            f'records={item.get("records", 0)}'
        )

    print("\nReport:", output)
    print("Original incoming files were not modified.")

if __name__ == "__main__":
    main()
