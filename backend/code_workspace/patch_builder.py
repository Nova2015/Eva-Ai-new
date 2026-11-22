"""
EVA Code Workspace — Patch Builder
POST /code/patch  →  generate unified diff patch
"""
from __future__ import annotations
import os, re, difflib
from .code_analyzer import _llm_call, detect_language, _sanitize


def build_patch(original: str, filename: str = "file.py", instructions: str = "") -> dict:
    lang = detect_language(filename)
    safe_original = _sanitize(original)

    if not instructions.strip():
        raise ValueError("Instructions required to build a patch")

    system = (
        f"You are an expert {lang} engineer. Apply the requested changes to the code and "
        "return ONLY the complete modified file — no markdown fences, no explanations."
    )
    user = f"Instructions: {instructions}\n\nOriginal code:\n\n{safe_original}"
    modified = _llm_call(system, user)

    modified = re.sub(r'^```[\w]*\n?', '', modified.strip())
    modified = re.sub(r'\n?```$', '', modified)
    modified = modified.strip()

    # Generate unified diff
    original_lines = original.splitlines(keepends=True)
    modified_lines = modified.splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        original_lines, modified_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        lineterm="",
    ))
    patch = "\n".join(diff)

    # Summary of changes
    added   = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
    explanation = (
        f"Patch generated: +{added} lines added, -{removed} lines removed.\n"
        f"Instructions applied: {instructions}"
    )

    return {
        "patch": patch,
        "modified_code": modified,
        "explanation": explanation,
        "stats": {"added": added, "removed": removed},
    }
