from __future__ import annotations

import ast
import re
from pathlib import Path

from backend.code_workspace.workspace import (
    WorkspaceSecurityError,
    git_status,
    search_files,
    read_file,
)

MAX_SEARCH_RESULTS = 20
MAX_FILES_TO_READ = 5
MAX_CONTEXT_CHARS = 12000
MAX_SYMBOL_CHARS = 9000


def _candidate_paths(question: str, root: Path) -> list[str]:
    """Extract explicit relative file paths from a natural-language question."""
    candidates = []

    # Examples: src/app.py, frontend/src/App.js, backend/code_workspace/workspace.py
    path_matches = re.findall(
        r'(?<![\w.-])(?:[\w.-]+/)+[\w.-]+',
        question or "",
    )

    for value in path_matches:
        value = value.strip().strip(".,:;()[]{}\"'")
        candidate = Path(value)

        if candidate.suffix:
            try:
                resolved = (root / candidate).resolve()
                resolved.relative_to(root.resolve())
                if resolved.is_file():
                    rel = resolved.relative_to(root.resolve()).as_posix()
                    if rel not in candidates:
                        candidates.append(rel)
            except (OSError, ValueError):
                continue

    return candidates


def _search_identifiers(question: str, root: Path) -> list[dict]:
    """Search useful code identifiers instead of the whole natural-language question."""
    results = []

    tokens = re.findall(
        r'(?<![\w])(?:[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*|[A-Za-z_][A-Za-z0-9_]{2,})(?![\w])',
        question or "",
    )

    ignored = {
        "the", "and", "what", "does", "tell", "about", "exact",
        "current", "used", "inside", "explain", "from", "file",
        "this", "that", "with", "call", "provider",
    }

    for token in tokens:
        token_lower = token.lower()

        if token_lower in ignored:
            continue

        # File names/paths are handled separately by _candidate_paths().
        # Do not let tokens such as "app.py" consume the identifier search
        # budget before real symbols such as "ask_groq" are searched.
        if "/" in token or "\\" in token or token.lower().endswith(
            (".py", ".js", ".jsx", ".ts", ".tsx", ".css", ".json", ".yaml", ".yml")
        ):
            continue

        # Search only code-like identifiers. Avoid generic natural-language
        # words such as "src", "app", "explain", "provider", etc.
        if "_" not in token and "." not in token and token not in {"complete", "dispatch"}:
            continue

        try:
            search_term = ("def " + token) if token in {"complete", "dispatch"} else token
            matches = search_files(root, search_term, max_results=MAX_SEARCH_RESULTS)
        except WorkspaceSecurityError:
            continue

        for item in matches:
            if item not in results:
                results.append(item)
            if len(results) >= MAX_SEARCH_RESULTS:
                return results

    return results


def _extract_function_source(content: str, names: set[str]) -> str:
    """Extract exact Python function/class definitions for requested symbols."""
    # read_file() may preserve a leading UTF-8 BOM; ast.parse() rejects it.
    content = content.lstrip("\ufeff")
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return ""

    lines = content.splitlines()
    chunks = []

    for node in ast.walk(tree):
        if not isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
        ):
            continue

        if node.name not in names:
            continue

        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None)

        if not start or not end:
            continue

        source = "\n".join(lines[start - 1:end])
        if source and source not in chunks:
            chunks.append(source)

    return "\n\n".join(chunks)


def _requested_symbols(question: str) -> set[str]:
    """Extract code symbols explicitly named in the question."""
    symbols = set()

    for token in re.findall(
        r'(?<![\w])(?:[A-Za-z_][A-Za-z0-9_]*\.)?'
        r'[A-Za-z_][A-Za-z0-9_]*(?![\w])',
        question or "",
    ):
        clean = token.split(".")[-1]
        if "_" in clean or clean in {"complete", "dispatch"}:
            symbols.add(clean)

    return symbols


def build_code_workspace_context(
    question: str,
    workspace_root: str | None = None,
) -> dict:
    """
    Build a small, read-only coding context for EVA Code Agent.

    Resolves explicit file paths and code identifiers from natural-language
    questions. No files are modified and no arbitrary shell commands execute.
    """
    if not workspace_root:
        return {
            "enabled": False,
            "context": "",
            "files": [],
            "git_status": None,
        }

    root = Path(workspace_root).expanduser()

    if not root.exists() or not root.is_dir():
        return {
            "enabled": False,
            "context": "",
            "files": [],
            "git_status": None,
            "error": f"Workspace root not found: {workspace_root}",
        }

    try:
        selected_paths = _candidate_paths(question, root)
        matches = []

        # First priority: explicit files named in the question.
        for path in selected_paths:
            matches.append({
                "path": path,
                "line": 1,
                "text": "Explicit file path from user question",
            })

        # Second priority: exact definitions of explicitly requested symbols.
        # Prefer the file containing `def <symbol>` before broad identifier matches.
        requested_symbols = _requested_symbols(question)
        exact_definition_matches = []
        for symbol in requested_symbols:
            try:
                exact_definition_matches.extend(
                    search_files(root, f"def {symbol}", max_results=MAX_SEARCH_RESULTS)
                )
            except WorkspaceSecurityError:
                continue

        identifier_matches = exact_definition_matches + _search_identifiers(question, root)

        for item in identifier_matches:
            if item["path"] not in selected_paths:
                selected_paths.append(item["path"])
            if len(selected_paths) >= MAX_FILES_TO_READ:
                break

        for item in identifier_matches:
            if item not in matches:
                matches.append(item)

        selected_paths = selected_paths[:MAX_FILES_TO_READ]

        sections = []
        authoritative_sources = []

        for path in selected_paths:
            try:
                result = read_file(root, path)
            except WorkspaceSecurityError:
                continue

            content = result.get("content", "")
            if not content:
                continue

            path_matches = [
                item for item in matches
                if item.get("path") == path
                and isinstance(item.get("line"), int)
                and item.get("line", 0) > 1
            ]

            # Prefer exact Python symbol extraction for Code Agent questions.
            # This gives small local models the complete requested function
            # instead of noisy line windows.
            requested_symbols = _requested_symbols(question)
            exact_source = ""

            if path.lower().endswith(".py") and requested_symbols:
                exact_source = _extract_function_source(
                    result.get("content", ""),
                    requested_symbols,
                )

            if exact_source:
                bounded_exact_source = exact_source[:MAX_SYMBOL_CHARS]
                content = bounded_exact_source
                authoritative_sources.append(
                    f"FILE: {path} — EXACT REQUESTED SYMBOL SOURCE\n{bounded_exact_source}"
                )
            # For symbol searches, keep useful source around the matching
            # lines instead of injecting an entire large source file.
            elif path_matches:
                lines = content.splitlines()
                ranges = []

                # Only a small number of the strongest matches per file.
                # This prevents repeated references to the same symbol from
                # flooding a small local model's context.
                for item in path_matches[:2]:
                    line_no = item["line"]

                    # Skip the synthetic explicit-file marker.
                    if line_no <= 1 and item.get("text", "").startswith(
                        "Explicit file path"
                    ):
                        continue

                    start = max(1, line_no - 20)
                    end = min(len(lines), line_no + 35)
                    ranges.append((start, end))

                merged = []
                for start, end in sorted(ranges):
                    if merged and start <= merged[-1][1] + 1:
                        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
                    else:
                        merged.append((start, end))

                snippet_parts = []
                for start, end in merged:
                    snippet_parts.append(
                        f"# Lines {start}-{end}\n"
                        + "\n".join(lines[start - 1:end])
                    )

                content = "\n\n".join(snippet_parts)
            else:
                # Explicit file path with no symbol match: provide a bounded
                # beginning of the file rather than the entire file.
                content = content[:12000]

            sections.append(
                f"FILE: {path}\n"
                f"```text\n{content}\n```"
            )

        try:
            status = git_status(root)
        except WorkspaceSecurityError:
            status = None

        context = "\n\n".join(sections)

        if authoritative_sources:
            authoritative_context = (
                "AUTHORITATIVE EXACT SYMBOL SOURCE:\n"
                "Use this exact source for the explicitly requested symbol. "
                "Do not reconstruct or simplify its signature or function call.\n\n"
                + "\n\n".join(authoritative_sources)
            )
        else:
            authoritative_context = ""

        if context:
            context = (
                "GROUNDING RULES:\n"
                "1. Treat the following source code as authoritative evidence.\n"
                "2. Answer only from the supplied code when the question is about this workspace.\n"
                "3. Do not invent APIs, URLs, function signatures, provider behavior, or code.\n"
                "4. If the code contradicts your prior knowledge, trust the code.\n"
                "5. If the requested detail is not present in the supplied code, say that it "
                "was not found instead of guessing.\n\n"
                + context
            )

        if authoritative_context:
            base_limit = max(0, MAX_CONTEXT_CHARS - len(authoritative_context) - 2)
            context = context[:base_limit] + "\n\n" + authoritative_context
        elif len(context) > MAX_CONTEXT_CHARS:
            context = context[:MAX_CONTEXT_CHARS] + "\n...[context truncated]"

        return {
            "enabled": True,
            "context": context,
            "exact_sources": authoritative_sources,
            "files": selected_paths,
            "matches": matches[:MAX_SEARCH_RESULTS],
            "git_status": status,
        }

    except WorkspaceSecurityError as exc:
        return {
            "enabled": False,
            "context": "",
            "files": [],
            "git_status": None,
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "enabled": False,
            "context": "",
            "files": [],
            "git_status": None,
            "error": f"Workspace resolver failed: {exc}",
        }




