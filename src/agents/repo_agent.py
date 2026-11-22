import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
CODE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".css"}
SKIP_DIRS = {".git", "node_modules", "build", "__pycache__", ".venv", "venv"}


def _iter_code_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        base = Path(dirpath)
        for filename in filenames:
            path = base / filename
            if path.suffix in CODE_SUFFIXES:
                yield path


def run_repo_task(instruction="", payload=None):
    payload = payload or {}
    repo_path = Path(payload.get("repo_path") or ROOT_DIR)
    if not repo_path.exists():
        return {
            "status": "failed",
            "summary": f"Repository path not found: {repo_path}",
            "findings": [],
            "next_actions": ["Provide a valid local repo path or use GitHub PR Mode with a repository URL."],
        }

    files = list(_iter_code_files(repo_path))
    findings = []
    risky_terms = ("TODO", "FIXME", "password", "secret", "api_key", "return outside")
    for path in files[:250]:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for term in risky_terms:
            if term.lower() in text.lower():
                findings.append({
                    "file": str(path.relative_to(repo_path)),
                    "issue": f"Contains marker or risky term: {term}",
                })
                break

    return {
        "status": "completed",
        "summary": f"Repo Agent scanned {len(files)} source files for: {instruction or 'general review'}.",
        "findings": findings[:20],
        "next_actions": [
            "Open Code Assistant for patch generation.",
            "Use GitHub PR Mode when ready to create a branch and pull request.",
            "Run frontend and backend tests after patching.",
        ],
    }
