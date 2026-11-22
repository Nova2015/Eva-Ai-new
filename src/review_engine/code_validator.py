"""Deterministic code-fence validator for EVA responses.

Languages handled:
- python/py : real parse via ast.parse(); SyntaxError reported with lineno.
- json      : real parse via json.loads().
- javascript/js/jsx : HEURISTIC ONLY — bracket balance and unterminated-string
  detection while skipping strings, template literals, and comments. This is
  NOT real parsing (no grammar, no semantics). If `node` is on PATH, plain
  js/javascript blocks are additionally checked with `node --check` and that
  result is preferred; jsx never uses node (node --check does not speak JSX).
- Fences tagged chart/mermaid are the chart/mermaid validators' job — skipped.
- Untagged fences make no language claim — skipped.

Text-level check: an odd number of ``` fences means an unclosed fence.

No LLM, no network. The optional `node --check` is a local subprocess only.
"""

import ast
import json
import os
import re
import shutil
import subprocess
import tempfile

_FENCE_RE = re.compile(r"```(\w*)[ \t]*\n?(.*?)```", re.S)

_PY_TAGS = {"python", "py", "python3"}
_JSON_TAGS = {"json"}
_JS_TAGS = {"javascript", "js"}
_JSX_TAGS = {"jsx", "tsx"}
_SKIP_TAGS = {"chart", "mermaid", ""}


def _js_heuristic(code):
    """Bracket/string sanity scan. Returns error string or None. HEURISTIC."""
    stack = []
    pairs = {")": "(", "]": "[", "}": "{"}
    i, n = 0, len(code)
    line = 1
    while i < n:
        c = code[i]
        if c == "\n":
            line += 1
        if c == "/" and i + 1 < n:
            nxt = code[i + 1]
            if nxt == "/":                      # line comment
                j = code.find("\n", i)
                i = n if j == -1 else j
                continue
            if nxt == "*":                      # block comment
                j = code.find("*/", i + 2)
                if j == -1:
                    return "unterminated block comment"
                line += code.count("\n", i, j)
                i = j + 2
                continue
        if c in ("'", '"', "`"):
            j = i + 1
            while j < n:
                if code[j] == "\\":
                    j += 2
                    continue
                if code[j] == c:
                    break
                if code[j] == "\n" and c != "`":
                    return f"unterminated string starting on line {line}"
                j += 1
            else:
                return f"unterminated string starting on line {line}"
            line += code.count("\n", i, j)
            i = j + 1
            continue
        if c in "([{":
            stack.append(c)
        elif c in ")]}":
            if not stack or stack[-1] != pairs[c]:
                return f"unbalanced '{c}' on line {line}"
            stack.pop()
        i += 1
    if stack:
        return f"unclosed '{stack[-1]}'"
    return None


def _node_check(code):
    """Return (used, error_or_None). Uses `node --check` when available."""
    node = shutil.which("node")
    if not node:
        return False, None
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(code)
            tmp = f.name
        proc = subprocess.run(
            [node, "--check", tmp],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0:
            return True, None
        err = (proc.stderr or proc.stdout or "syntax error").strip().splitlines()
        return True, err[-1][:200] if err else "syntax error"
    except Exception:
        return False, None
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def validate_code(text: str) -> dict:
    """Validate fenced code blocks. Returns {"passed", "issues", "applicable"}."""
    text = text or ""
    issues = []
    checked_any = False

    if text.count("```") % 2 == 1:
        issues.append({
            "code": "unclosed_fence",
            "detail": "odd number of ``` fences — a code fence is never closed",
        })
        checked_any = True

    for lang, body in _FENCE_RE.findall(text):
        lc = (lang or "").lower()
        body = body.strip()
        if lc in _SKIP_TAGS or not body:
            continue

        if lc in _PY_TAGS:
            checked_any = True
            try:
                ast.parse(body)
            except SyntaxError as e:
                issues.append({
                    "code": "python_syntax_error",
                    "detail": f"python block line {e.lineno}: {e.msg}",
                })

        elif lc in _JSON_TAGS:
            checked_any = True
            try:
                json.loads(body)
            except ValueError as e:
                issues.append({
                    "code": "json_parse_error",
                    "detail": f"json block does not parse: {e}",
                })

        elif lc in _JS_TAGS or lc in _JSX_TAGS:
            checked_any = True
            if lc in _JS_TAGS:
                used_node, node_err = _node_check(body)
                if used_node:
                    if node_err:
                        issues.append({
                            "code": "js_syntax_error",
                            "detail": f"node --check: {node_err}",
                        })
                    continue
            err = _js_heuristic(body)
            if err:
                issues.append({
                    "code": "js_syntax_error",
                    "detail": f"heuristic check: {err}",
                })

    return {"passed": not issues, "issues": issues, "applicable": checked_any}
