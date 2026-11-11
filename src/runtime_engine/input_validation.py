"""Slice 20.x — PARSE-FIRST INVALID_INPUT detection for the MANUAL code box.

Why this exists and how it relates to slice-6 execution_policy.mark_runnable():
  - mark_runnable(text) gates CHAT answers. It scans for FENCED code blocks and
    accepts iff exactly one block + supported language + within the size cap. It
    makes NO prose-vs-code judgment (the single-fence rule is its gate) and only
    ever sees LLM-fenced text.
  - appears_executable(code, language) gates the NEW manual code box: RAW user-
    typed code + an EXPLICIT language, with NO fences. It is PARSE-FIRST.

  Different inputs, different entry points — they do NOT duplicate or contradict.
  Consistency guarantee: anything that is valid python/js (i.e. real code that
  mark_runnable would meaningfully accept) PARSES here and is accepted at step 2,
  so a block can never pass one gate and be INVALID_INPUT'd by the other for a
  contradictory reason. The heuristic below rejects ONLY pure prose; it never
  rejects code that merely fails to parse — broken code is sent to Piston so the
  user gets the real syntax error (useful feedback), not INVALID_INPUT.

No suggest_fix. No auto-correction. Executes nothing (node --check parses only).
"""

import ast
import os
import re
import shutil
import subprocess
import tempfile

_ALIASES = {"py": "python", "python3": "python", "js": "javascript", "node": "javascript"}

# Signals that UNPARSEABLE text is BROKEN CODE (-> Piston), not prose:
# code punctuation, arrow fn, common keywords, or an indentation block.
_CODE_STRUCTURE = re.compile(
    r"[(){}\[\];=]"
    r"|=>"
    r"|\b(?:def|class|function|const|let|var|import|from|return|for|while|if|elif|else|print|console|lambda|async|await|yield)\b"
    r"|^[ \t]+\S",
    re.MULTILINE,
)


def _normalize_lang(language: str) -> str:
    lang = (language or "").strip().lower()
    return _ALIASES.get(lang, lang)


def _js_parses(code: str) -> bool:
    """node --check (parse only, does NOT execute). Temp file since --check needs a path."""
    node = shutil.which("node")
    if not node:
        return False  # caller falls through to the heuristic
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(code)
            tmp = f.name
        proc = subprocess.run([node, "--check", tmp], capture_output=True, text=True, timeout=5)
        return proc.returncode == 0
    except Exception:
        return False
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def appears_executable(code: str, language: str) -> dict:
    """Return {"executable": bool, "reason": str|None}. Parse-first; heuristic rejects prose only."""
    # 1. empty / whitespace-only
    if not code or not code.strip():
        return {"executable": False, "reason": "empty"}

    lang = _normalize_lang(language)

    # 2. PARSE-FIRST. Parse success -> EXECUTABLE (accept; never run the heuristic).
    node_available = True
    if lang == "python":
        try:
            ast.parse(code)
            return {"executable": True, "reason": None}
        except SyntaxError:
            pass          # -> step 3
        except Exception:
            pass          # unexpected parser error -> step 3 (don't crash)
    elif lang == "javascript":
        node_available = shutil.which("node") is not None
        if node_available:
            if _js_parses(code):
                return {"executable": True, "reason": None}
            # parse failed -> step 3
        # node absent -> skip parse, go straight to step 3 heuristic
    else:
        # Unknown/unsupported language: don't prose-reject here. Let the downstream
        # runtime engine map aliases / reject unsupported languages consistently.
        return {"executable": True, "reason": None}

    # 3. parse FAILED (or JS with no node) -> broken code vs prose
    if _CODE_STRUCTURE.search(code):
        return {"executable": True, "reason": None}      # broken code -> Piston (real SyntaxError)
    return {"executable": False, "reason": "not_code"}   # pure prose -> INVALID_INPUT
