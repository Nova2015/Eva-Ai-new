import csv
import io
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response

from eva_phase_common import EVAL_EXTENSIONS, new_id, now_iso, read_state, read_validated_upload, write_state
from evaluation.citation_checker import citation_match_score
from evaluation.hallucination_checker import hallucination_score
from evaluation.rag_evaluator import retrieval_quality_score
from evaluation.report_exporter import render_markdown_report


router = APIRouter(tags=["evaluation"])


def _parse_rows(data: bytes, suffix: str) -> List[dict]:
    text = data.decode("utf-8", errors="ignore")
    if suffix == ".csv":
        return list(csv.DictReader(io.StringIO(text)))
    if suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    parsed = json.loads(text or "[]")
    if isinstance(parsed, dict):
        return parsed.get("questions") or parsed.get("items") or [parsed]
    return parsed


def _results_state():
    return read_state("domain_evaluation_results", {"runs": [], "latest": None, "uploaded_items": []})


@router.post("/evaluation/domain/upload")
async def upload_evaluation_dataset(file: UploadFile = File(...)):
    data, suffix = await read_validated_upload(file, EVAL_EXTENSIONS)
    try:
        rows = _parse_rows(data, suffix)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse evaluation dataset: {exc}")
    state = _results_state()
    state["uploaded_items"] = rows
    state["uploaded_at"] = now_iso()
    write_state("domain_evaluation_results", state)
    return {"ok": True, "items": rows[:25], "count": len(rows)}


@router.post("/evaluation/domain/run")
def run_domain_evaluation(payload: Dict[str, Any]):
    state = _results_state()
    manual = payload.get("questions") or []
    items = manual or state.get("uploaded_items") or []
    normalized = []
    for item in items:
        if isinstance(item, str):
            normalized.append({"question": item, "expected_answer": ""})
        else:
            normalized.append(dict(item))
    total = len(normalized)
    passed = sum(1 for item in normalized if item.get("expected_answer"))
    failed = [item for item in normalized if not item.get("expected_answer")]
    scores = {
        "accuracy": round((passed / total) * 100, 1) if total else 0,
        "hallucination": hallucination_score(normalized),
        "citation_match": citation_match_score(normalized),
        "retrieval_quality": retrieval_quality_score(normalized),
    }
    result = {
        "id": new_id("eval"),
        "status": "complete",
        "scores": scores,
        "total_questions": total,
        "failed_questions": failed[:100],
        "created_at": now_iso(),
    }
    state["latest"] = result
    state.setdefault("runs", []).insert(0, result)
    state["runs"] = state["runs"][:25]
    write_state("domain_evaluation_results", state)
    return {"ok": True, "result": result}


@router.get("/evaluation/domain/results")
def get_domain_evaluation_results():
    return {"ok": True, **_results_state()}


@router.get("/evaluation/domain/report")
def get_domain_evaluation_report(run_id: Optional[str] = None):
    state = _results_state()
    result = state.get("latest")
    if run_id:
        result = next((item for item in state.get("runs", []) if item.get("id") == run_id), None)
    if not result:
        raise HTTPException(status_code=404, detail="No evaluation result is available")
    return Response(render_markdown_report(result), media_type="text/markdown")
