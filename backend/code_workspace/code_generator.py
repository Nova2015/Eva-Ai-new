"""
EVA Code Workspace — Code Generator & Fixer & Refactorer
POST /code/generate  →  generate code from prompt
POST /code/fix       →  fix bugs in provided code
POST /code/refactor  →  refactor code
"""
from __future__ import annotations
import os, re
from .code_analyzer import _llm_call, detect_language, _sanitize


def generate_code(prompt: str, language: str = "python") -> dict:
    if not prompt.strip():
        raise ValueError("Prompt cannot be empty")

    system = (
        f"You are an expert {language} developer. Generate clean, well-commented, "
        "production-ready code based on the user's description. "
        "Return ONLY the code — no markdown fences, no explanations outside comments."
    )
    user = f"Generate {language} code for: {prompt}"
    code = _llm_call(system, user)

    # Strip accidental markdown fences
    code = re.sub(r'^```[\w]*\n?', '', code.strip())
    code = re.sub(r'\n?```$', '', code)

    return {"code": code.strip(), "language": language}


def fix_code(code: str, filename: str = "file.py") -> dict:
    lang = detect_language(filename)
    safe_code = _sanitize(code)

    system = (
        f"You are an expert {lang} debugger. Fix all bugs, syntax errors, and logic issues "
        "in the provided code. Return ONLY the corrected code — no markdown fences, "
        "no explanations. Preserve the original structure and comments."
    )
    user = f"Fix this {lang} code:\n\n{safe_code}"
    fixed = _llm_call(system, user)

    fixed = re.sub(r'^```[\w]*\n?', '', fixed.strip())
    fixed = re.sub(r'\n?```$', '', fixed)

    return {"fixed_code": fixed.strip(), "language": lang}


def refactor_code(code: str, filename: str = "file.py", instructions: str = "") -> dict:
    lang = detect_language(filename)
    safe_code = _sanitize(code)

    directive = instructions.strip() or (
        "Improve readability, reduce duplication, use modern idioms, "
        "add type hints where appropriate, and improve naming."
    )

    system = (
        f"You are an expert {lang} engineer. Refactor the provided code following the instructions. "
        "Return ONLY the refactored code — no markdown fences."
    )
    user = f"Instructions: {directive}\n\nCode to refactor:\n\n{safe_code}"
    refactored = _llm_call(system, user)

    refactored = re.sub(r'^```[\w]*\n?', '', refactored.strip())
    refactored = re.sub(r'\n?```$', '', refactored)

    return {"refactored_code": refactored.strip(), "language": lang}