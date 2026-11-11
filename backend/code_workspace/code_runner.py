import os
import subprocess
import sys
import tempfile


BLOCKED_PATTERNS = [
    "os.remove",
    "os.rmdir",
    "shutil.rmtree",
    "subprocess",
    "socket",
    "requests",
    "urllib",
    "open(",
    "eval(",
    "exec(",
    "__import__",
    "input(",
]


def run_python_code(code: str):
    if not code or not code.strip():
        return {
            "stdout": "",
            "stderr": "No code provided.",
            "returncode": 1,
        }

    for pattern in BLOCKED_PATTERNS:
        if pattern in code:
            return {
                "stdout": "",
                "stderr": f"Blocked unsafe code pattern: {pattern}",
                "returncode": 1,
            }

    with tempfile.NamedTemporaryFile(
        delete=False,
        suffix=".py",
        mode="w",
        encoding="utf-8",
    ) as f:
        f.write(code)
        filename = f.name

    try:
        result = subprocess.run(
            [sys.executable, filename],
            capture_output=True,
            text=True,
            timeout=8,
        )

        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": "Code execution timed out.",
            "returncode": 1,
        }

    finally:
        try:
            os.unlink(filename)
        except Exception:
            pass