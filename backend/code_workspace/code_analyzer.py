"""
EVA Code Workspace — Code Analyzer
POST /code/analyze  →  explain / review code
"""
from __future__ import annotations
import os, re
from typing import Optional

CHART_SYSTEM_PROMPT = """CHART OUTPUT CONTRACT (HIGH PRIORITY)

When the user asks for a chart, graph, pie chart, bar chart, line chart, or visualization:
MUST include a fenced ```chart block containing valid JSON.
NEVER provide matplotlib code, Python chart code, prose-only chart descriptions, or "imagine a chart" answers.
Allowed: a short explanation after the chart block."""


def _is_chart_request(prompt: str) -> bool:
    text = (prompt or "").lower()
    return any(word in text for word in ("chart", "graph", "pie", "bar", "line", "visualization"))


def _chart_system_prompt(system: str, user: str) -> str:
    if _is_chart_request(user) and CHART_SYSTEM_PROMPT not in system:
        return f"{system}\n\n{CHART_SYSTEM_PROMPT}"
    return system


def _log_raw_model_response(content: str) -> None:
    print("RAW MODEL RESPONSE:")
    print(content)

# ── LLM helper (re-uses whatever client EVA already has) ─────────────────────
def _llm_call(system: str, user: str) -> str:
    """Call OpenAI-compatible endpoint already configured in the project."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is required for EVA Code Workspace. Add it in HF Space secrets.")

    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        resp = client.chat.completions.create(
            model=os.getenv("CODE_MODEL", "openai/gpt-oss-120b"),
            messages=[{"role": "system", "content": _chart_system_prompt(system, user)},
                      {"role": "user",   "content": user}],
            max_tokens=2048,
            temperature=0.2,
        )
        content = resp.choices[0].message.content or ""
        _log_raw_model_response(content)
        return content.strip()
    except Exception as e:
        raise RuntimeError(f"LLM error: {e}")


def detect_language(filename: str) -> str:
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    return {
        "py": "Python", "js": "JavaScript", "jsx": "JavaScript",
        "ts": "TypeScript", "tsx": "TypeScript", "css": "CSS",
        "html": "HTML", "json": "JSON", "md": "Markdown",
        "sh": "Bash", "sql": "SQL", "yml": "YAML", "yaml": "YAML",
    }.get(ext, "code")


def _sanitize(code: str, max_chars: int = 12_000) -> str:
    """Strip potential secret patterns before sending to LLM."""
    # Redact obvious secrets
    code = re.sub(
        r'(api[_-]?key|secret|password|token|auth)\s*[=:]\s*["\']?[\w\-]{8,}["\']?',
        r'\1=<REDACTED>',
        code, flags=re.IGNORECASE
    )
    return code[:max_chars]


def analyze_code(code: str, filename: str = "file.py") -> dict:
    lang = detect_language(filename)
    safe_code = _sanitize(code)

    system = (
        "You are an expert code reviewer. Analyze the provided code and return:\n"
        "1. A brief summary of what the code does\n"
        "2. Identified bugs or issues\n"
        "3. Security concerns (if any)\n"
        "4. Suggestions for improvement\n"
        "Be concise and practical. Use bullet points."
    )
    user = f"Language: {lang}\nFile: {filename}\n\n```{lang.lower()}\n{safe_code}\n```"

    explanation = _llm_call(system, user)
    return {"explanation": explanation, "language": lang, "filename": filename}
