import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"

# Load simple KEY=VALUE entries without printing secrets.
if ENV_FILE.exists():
    for raw in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith(("'", '"')) and value.endswith(("'", '"')):
            value = value[1:-1]
        if key:
            os.environ[key] = value

# Configure the guard BEFORE importing any service.
os.environ["EVA_LOCAL_ONLY"] = "1"
os.environ["EVA_LOCAL_GUARD_MODE"] = "log"
os.environ["EVA_LOCAL_ALLOW_LAN"] = "1"
os.environ["EVA_LOCAL_GUARD_LOG"] = str(ROOT / "eva_blocked_hosts.log")

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import src.eva_local_guard

import uvicorn

service = sys.argv[1].lower() if len(sys.argv) > 1 else ""

if service == "backend":
    os.chdir(ROOT)
    print("Starting EVA Backend on 127.0.0.1:8000")
    uvicorn.run("src.app:app", host="127.0.0.1", port=8000)

elif service == "ml":
    ml_dir = ROOT / "eva-ml-service"
    os.chdir(ml_dir)

    # ML app.py must take priority over src/app.py.
    sys.path.insert(0, str(ml_dir))

    import importlib
    ml_app = importlib.import_module("app")

    print("Starting EVA ML + RAG on 127.0.0.1:7860")
    print("Loaded ML app from:", ml_app.__file__)

    uvicorn.run(ml_app.app, host="127.0.0.1", port=7860)
elif service == "agent":
    required = ["AGENT_API_KEY", "AGENT_MODEL", "GEMINI_API_KEY"]
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise RuntimeError("Agent missing environment variables: " + ", ".join(missing))

    os.environ.setdefault("AGENT_WORKSPACE", r"D:\eva_agent_workspace")
    os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"
    os.chdir(ROOT / "src")
    print("Starting EVA Agent on 127.0.0.1:8100")
    uvicorn.run("agent_service:app", host="127.0.0.1", port=8100)

else:
    raise SystemExit("Usage: eva_local_bootstrap.py backend|ml|agent")