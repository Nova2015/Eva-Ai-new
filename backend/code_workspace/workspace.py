from __future__ import annotations

import os
import subprocess
from pathlib import Path

SKIP_DIRS = {
    ".git", ".hg", ".svn", ".claude",
    "__pycache__", ".pytest_cache",
    ".venv", "venv", "env",
    "node_modules", "dist", "build",
}

BLOCKED_NAMES = {
    ".env", ".env.local", ".env.production",
}

SEARCH_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx",
    ".java", ".c", ".cpp", ".h", ".hpp", ".cs",
    ".go", ".rs", ".php", ".rb", ".swift",
    ".kt", ".kts", ".html", ".css", ".scss",
    ".sql", ".json", ".yaml", ".yml", ".toml",
}

BLOCKED_EXTENSIONS = {
    ".pem", ".key", ".p12", ".pfx",
    ".crt", ".cer", ".der",
    ".exe", ".dll", ".so", ".bin",
}

MAX_READ_BYTES = 2 * 1024 * 1024


class WorkspaceSecurityError(Exception):
    pass


def normalize_root(root: str | Path) -> Path:
    path = Path(root).expanduser().resolve()

    if not path.exists() or not path.is_dir():
        raise WorkspaceSecurityError(f"Workspace root not found: {path}")

    return path


def safe_path(root: str | Path, relative_path: str = "") -> Path:
    root_path = normalize_root(root)

    candidate = (root_path / relative_path).resolve()

    try:
        candidate.relative_to(root_path)
    except ValueError:
        raise WorkspaceSecurityError("Path escapes workspace root.")

    if candidate.name in BLOCKED_NAMES:
        raise WorkspaceSecurityError("Access to protected file is blocked.")

    if candidate.suffix.lower() in BLOCKED_EXTENSIONS:
        raise WorkspaceSecurityError("Access to protected/binary file is blocked.")

    return candidate


def is_skipped_dir(path: Path) -> bool:
    return path.name in SKIP_DIRS


def _run_git(root: str | Path, args: list[str], max_output: int = 20000) -> dict:
    root_path = normalize_root(root)
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(root_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkspaceSecurityError(f"Git command failed: {exc}")

    return {
        "returncode": result.returncode,
        "stdout": result.stdout[:max_output],
        "stderr": result.stderr[:max_output],
    }


def git_status(root: str | Path) -> dict:
    return _run_git(root, ["status", "--short", "--branch"])


def git_diff(root: str | Path, staged: bool = False) -> dict:
    args = ["diff", "--no-ext-diff"]
    if staged:
        args.append("--cached")
    return _run_git(root, args)


def git_log(root: str | Path, limit: int = 20) -> dict:
    limit = max(1, min(int(limit), 100))
    return _run_git(
        root,
        ["log", f"-{limit}", "--oneline", "--decorate"],
    )


def list_tree(root: str | Path, max_entries: int = 2000) -> list[dict]:
    root_path = normalize_root(root)
    results = []

    for dirpath, dirnames, filenames in os.walk(root_path):
        current = Path(dirpath)

        dirnames[:] = [
            name for name in dirnames
            if name not in SKIP_DIRS
        ]

        for filename in filenames:
            if len(results) >= max_entries:
                return results

            path = current / filename

            if filename in BLOCKED_NAMES:
                continue

            if path.suffix.lower() in BLOCKED_EXTENSIONS:
                continue

            try:
                relative = path.relative_to(root_path).as_posix()
                size = path.stat().st_size
            except OSError:
                continue

            results.append({
                "path": relative,
                "size": size,
                "extension": path.suffix.lower(),
            })

    return results


def read_file(
    root: str | Path,
    relative_path: str,
    max_bytes: int = MAX_READ_BYTES,
) -> dict:
    path = safe_path(root, relative_path)

    if not path.exists():
        raise WorkspaceSecurityError(
            f"File not found: {relative_path}"
        )

    if not path.is_file():
        raise WorkspaceSecurityError(
            f"Not a file: {relative_path}"
        )

    size = path.stat().st_size

    if size > max_bytes:
        raise WorkspaceSecurityError(
            f"File is too large to read ({size} bytes)."
        )

    try:
        content = path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise WorkspaceSecurityError(
            f"Unable to read file: {exc}"
        )

    return {
        "path": path.relative_to(normalize_root(root)).as_posix(),
        "size": size,
        "chars": len(content),
        "content": content,
    }


def search_files(
    root: str | Path,
    query: str,
    max_results: int = 1000,
) -> list[dict]:
    root_path = normalize_root(root)

    if not query.strip():
        return []

    needle = query.lower()
    results = []

    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [
            name for name in dirnames
            if name not in SKIP_DIRS
        ]

        for filename in filenames:
            if filename in BLOCKED_NAMES:
                continue

            path = Path(dirpath) / filename

            if path.suffix.lower() not in SEARCH_EXTENSIONS:
                continue

            if path.suffix.lower() in BLOCKED_EXTENSIONS:
                continue

            try:
                if path.stat().st_size > MAX_READ_BYTES:
                    continue

                text = path.read_text(
                    encoding="utf-8",
                    errors="ignore",
                )
            except OSError:
                continue

            for line_number, line in enumerate(
                text.splitlines(),
                start=1,
            ):
                if needle in line.lower():
                    results.append({
                        "path": path.relative_to(root_path).as_posix(),
                        "line": line_number,
                        "text": line[:1000],
                    })

                    if len(results) >= max_results:
                        return results

    return results


