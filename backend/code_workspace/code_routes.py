"""
EVA Code Workspace â€” API Routes

Safe code/project ingestion and AI coding operations.

Mounted by src.app as:
    app.include_router(code_router, prefix="/code", tags=["Code Workspace"])
"""

from __future__ import annotations

import io
import os
import re
import uuid
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .code_analyzer import analyze_code
from .code_generator import fix_code, generate_code, refactor_code
from .patch_builder import build_patch
from .code_runner import run_python_code
from .workspace import (list_tree, read_file, search_files, git_status, git_diff, git_log, WorkspaceSecurityError)


router = APIRouter()


# ============================================================
# Limits
# ============================================================

# These are transport/storage safety limits, NOT AI context limits.
MAX_CODE_CHARS = 5_000_000
MAX_PROMPT_CHARS = 2_000

MAX_ZIP_BYTES = 50 * 1024 * 1024       # 50 MB upload
MAX_FILE_BYTES = 10 * 1024 * 1024     # 10 MB per extracted file
MAX_FILES = 500                       # maximum project files

# AI context chunking.
CHUNK_CHARS = 12_000
CHUNK_OVERLAP = 1_000


# ============================================================
# Security
# ============================================================

BLOCKED_EXTENSIONS = {
    ".exe", ".dll", ".so", ".bin",
    ".bat", ".cmd", ".ps1", ".sh", ".bash",
    ".vbs", ".msi", ".dmg", ".apk",
    ".env", ".pem", ".key", ".pfx", ".p12",
}

CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx",
    ".css", ".scss", ".html", ".htm",
    ".json", ".md", ".txt",
    ".sql", ".yml", ".yaml",
    ".xml", ".toml", ".ini",
    ".java", ".c", ".h", ".cpp", ".hpp",
    ".cs", ".go", ".rs", ".php",
    ".rb", ".swift", ".kt", ".kts",
    ".vue", ".svelte",
}

BLOCKED_PATTERNS = [
    "rm -rf",
    "os.system",
    "subprocess.call",
    "__import__",
    "eval(",
    "exec(",
    "pickle.loads",
]


def _check_code_safety(code: str):
    """Raise if code contains obviously dangerous patterns."""
    lowered = code.lower()

    for pat in BLOCKED_PATTERNS:
        if pat.lower() in lowered:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Blocked pattern detected: '{pat}'. "
                    "Remove it before analysis."
                ),
            )


def _safe_zip_path(name: str) -> str:
    """
    Normalize ZIP paths and reject path traversal.

    The returned path always uses forward slashes and never escapes
    the logical project root.
    """
    name = (name or "").replace("\\", "/")

    # Remove leading slash.
    name = name.lstrip("/")

    parts = []
    for part in name.split("/"):
        if not part or part == ".":
            continue

        if part == "..":
            raise HTTPException(
                status_code=400,
                detail="Unsafe ZIP path detected.",
            )

        parts.append(part)

    if not parts:
        raise HTTPException(
            status_code=400,
            detail="Invalid ZIP file path.",
        )

    return "/".join(parts)


def _extension(name: str) -> str:
    return Path(name).suffix.lower()


def _is_allowed_source(name: str) -> bool:
    ext = _extension(name)

    if ext in BLOCKED_EXTENSIONS:
        return False

    # Explicitly allow known source/text extensions.
    if ext in CODE_EXTENSIONS:
        return True

    # Files without extension can still contain source/configuration.
    return not ext


# ============================================================
# Chunking
# ============================================================

def chunk_code(
    code: str,
    chunk_chars: int = CHUNK_CHARS,
    overlap: int = CHUNK_OVERLAP,
) -> list[dict]:
    """
    Split source into overlapping chunks.

    IMPORTANT:
    This never modifies the original source.
    Chunking exists only for AI context.
    """
    if not code:
        return []

    if chunk_chars <= 0:
        raise ValueError("chunk_chars must be positive")

    overlap = max(0, min(overlap, chunk_chars // 2))

    chunks = []
    start = 0
    length = len(code)
    index = 0

    while start < length:
        end = min(length, start + chunk_chars)

        # Prefer a line boundary where possible.
        if end < length:
            newline = code.rfind("\n", start, end)
            if newline > start + chunk_chars // 2:
                end = newline + 1

        text = code[start:end]

        chunks.append({
            "index": index,
            "start_char": start,
            "end_char": end,
            "chars": len(text),
            "content": text,
        })

        if end >= length:
            break

        next_start = end - overlap

        if next_start <= start:
            next_start = end

        start = next_start
        index += 1

    return chunks


# ============================================================
# Request models
# ============================================================

class AnalyzeRequest(BaseModel):
    code: str = Field(..., max_length=MAX_CODE_CHARS)
    filename: str = Field("file.py", max_length=500)


class GenerateRequest(BaseModel):
    prompt: str = Field(..., max_length=MAX_PROMPT_CHARS)
    language: str = Field("python", max_length=40)


class FixRequest(BaseModel):
    code: str = Field(..., max_length=MAX_CODE_CHARS)
    filename: str = Field("file.py", max_length=500)


class RefactorRequest(BaseModel):
    code: str = Field(..., max_length=MAX_CODE_CHARS)
    filename: str = Field("file.py", max_length=500)
    instructions: Optional[str] = Field("", max_length=MAX_PROMPT_CHARS)


class PatchRequest(BaseModel):
    original: str = Field(..., max_length=MAX_CODE_CHARS)
    filename: str = Field("file.py", max_length=500)
    instructions: str = Field(..., max_length=MAX_PROMPT_CHARS)


class RunRequest(BaseModel):
    code: str
    language: str = "python"


class ChunkRequest(BaseModel):
    code: str = Field(..., max_length=MAX_CODE_CHARS)
    filename: str = Field("file.py", max_length=500)
    chunk_chars: int = Field(CHUNK_CHARS, ge=1000, le=50000)


# ============================================================
# AI routes
# ============================================================

@router.post("/analyze")
async def route_analyze(req: AnalyzeRequest):
    """Explain / review provided code."""
    _check_code_safety(req.code)

    try:
        result = analyze_code(req.code, req.filename)
        return JSONResponse(result)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate")
async def route_generate(req: GenerateRequest):
    """Generate code from a natural-language prompt."""
    try:
        result = generate_code(req.prompt, req.language)
        return JSONResponse(result)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/fix")
async def route_fix(req: FixRequest):
    """Fix bugs in provided code."""
    _check_code_safety(req.code)

    try:
        result = fix_code(req.code, req.filename)
        return JSONResponse(result)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/refactor")
async def route_refactor(req: RefactorRequest):
    """Refactor code with optional instructions."""
    _check_code_safety(req.code)

    try:
        result = refactor_code(
            req.code,
            req.filename,
            req.instructions or "",
        )
        return JSONResponse(result)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/patch")
async def route_patch(req: PatchRequest):
    """Generate a unified diff patch."""
    _check_code_safety(req.original)

    try:
        result = build_patch(
            req.original,
            req.filename,
            req.instructions,
        )
        return JSONResponse(result)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Chunk inspection endpoint
# ============================================================

@router.post("/chunks")
async def route_chunks(req: ChunkRequest):
    """
    Return chunk metadata/content for a source file.

    This is an internal context-preparation endpoint.
    It does not execute the uploaded code.
    """
    _check_code_safety(req.code)

    chunks = chunk_code(
        req.code,
        chunk_chars=req.chunk_chars,
        overlap=CHUNK_OVERLAP,
    )

    return JSONResponse({
        "filename": req.filename,
        "total_chars": len(req.code),
        "chunk_count": len(chunks),
        "chunks": chunks,
    })


# ============================================================
# ZIP / Project ingestion
# ============================================================

@router.post("/upload-zip")
async def route_upload_zip(file: UploadFile = File(...)):
    """
    Accept a ZIP project and extract safe source/text files.

    IMPORTANT:
    - Never executes uploaded code.
    - Preserves relative project paths.
    - Does not truncate source files.
    - Does not discard files merely because they exceed the old 500 KB limit.
    - Chunking is performed separately for AI context.
    """
    filename = file.filename or ""

    if not filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=400,
            detail="Only .zip files accepted",
        )

    contents = await file.read()

    if len(contents) > MAX_ZIP_BYTES:
        raise HTTPException(
            status_code=413,
            detail="ZIP too large (max 50 MB)",
        )

    extracted = []
    skipped = []

    try:
        with zipfile.ZipFile(io.BytesIO(contents)) as zf:
            infos = zf.infolist()

            if len(infos) > MAX_FILES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Project contains too many entries (max {MAX_FILES})",
                )

            for info in infos:
                if info.is_dir():
                    continue

                try:
                    name = _safe_zip_path(info.filename)
                except HTTPException:
                    skipped.append({
                        "name": info.filename,
                        "reason": "unsafe path",
                    })
                    continue

                # Skip common repository/system metadata.
                if (
                    "__MACOSX/" in name
                    or name.startswith(".git/")
                    or "/.git/" in name
                    or name.endswith(".DS_Store")
                ):
                    skipped.append({
                        "name": name,
                        "reason": "repository/system metadata",
                    })
                    continue

                ext = _extension(name)

                if ext in BLOCKED_EXTENSIONS:
                    skipped.append({
                        "name": name,
                        "reason": "blocked extension",
                    })
                    continue

                if not _is_allowed_source(name):
                    skipped.append({
                        "name": name,
                        "reason": "unsupported binary/non-text file",
                    })
                    continue

                if info.file_size > MAX_FILE_BYTES:
                    skipped.append({
                        "name": name,
                        "reason": "file too large",
                    })
                    continue

                try:
                    raw = zf.read(info)

                    # Decode as text without modifying stored source semantics.
                    text = raw.decode("utf-8", errors="replace")

                    extracted.append({
                        "name": name,
                        "content": text,
                        "type": "file",
                        "size": len(raw),
                        "chars": len(text),
                    })

                except Exception:
                    skipped.append({
                        "name": name,
                        "reason": "could not decode/read",
                    })

    except zipfile.BadZipFile:
        raise HTTPException(
            status_code=400,
            detail="Invalid or corrupt ZIP file",
        )

    if not extracted:
        raise HTTPException(
            status_code=400,
            detail="No readable source/text files found in ZIP",
        )

    workspace_id = uuid.uuid4().hex

    total_chars = sum(item["chars"] for item in extracted)

    return JSONResponse({
        "workspace_id": workspace_id,
        "files": extracted,
        "count": len(extracted),
        "total_chars": total_chars,
        "skipped": skipped,
        "chunking": {
            "enabled": True,
            "chunk_chars": CHUNK_CHARS,
            "overlap": CHUNK_OVERLAP,
        },
    })


# ============================================================
# Local Workspace — read-only
# ============================================================

class WorkspaceRequest(BaseModel):
    workspace_root: str = Field(..., max_length=1000)


class WorkspaceFileRequest(BaseModel):
    workspace_root: str = Field(..., max_length=1000)
    path: str = Field(..., max_length=2000)


class WorkspaceSearchRequest(BaseModel):
    workspace_root: str = Field(..., max_length=1000)
    query: str = Field(..., min_length=1, max_length=500)
    max_results: int = Field(100, ge=1, le=500)


@router.post("/workspace/tree")
async def route_workspace_tree(req: WorkspaceRequest):
    try:
        return JSONResponse({
            "workspace_root": req.workspace_root,
            "files": list_tree(req.workspace_root),
        })
    except WorkspaceSecurityError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/workspace/read")
async def route_workspace_read(req: WorkspaceFileRequest):
    try:
        return JSONResponse(
            read_file(req.workspace_root, req.path)
        )
    except WorkspaceSecurityError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/workspace/search")
async def route_workspace_search(req: WorkspaceSearchRequest):
    try:
        return JSONResponse({
            "workspace_root": req.workspace_root,
            "query": req.query,
            "results": search_files(
                req.workspace_root,
                req.query,
                req.max_results,
            ),
        })
    except WorkspaceSecurityError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# Git Workspace ? read-only
# ============================================================

class WorkspaceGitRequest(BaseModel):
    workspace_root: str = Field(..., max_length=1000)


class WorkspaceGitDiffRequest(BaseModel):
    workspace_root: str = Field(..., max_length=1000)
    staged: bool = False


class WorkspaceGitLogRequest(BaseModel):
    workspace_root: str = Field(..., max_length=1000)
    limit: int = Field(20, ge=1, le=100)


@router.post("/workspace/git/status")
async def route_workspace_git_status(req: WorkspaceGitRequest):
    try:
        return JSONResponse(git_status(req.workspace_root))
    except WorkspaceSecurityError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/workspace/git/diff")
async def route_workspace_git_diff(req: WorkspaceGitDiffRequest):
    try:
        return JSONResponse(
            git_diff(req.workspace_root, staged=req.staged)
        )
    except WorkspaceSecurityError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/workspace/git/log")
async def route_workspace_git_log(req: WorkspaceGitLogRequest):
    try:
        return JSONResponse(
            git_log(req.workspace_root, limit=req.limit)
        )
    except WorkspaceSecurityError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Code execution
# ============================================================

@router.post("/run")
async def route_run(req: RunRequest):
    if req.language.lower() != "python":
        raise HTTPException(
            status_code=400,
            detail="Only Python execution is supported right now.",
        )

    return JSONResponse(run_python_code(req.code))

