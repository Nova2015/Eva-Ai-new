"""
eva_local_agent.py
==================
Run this on your Windows machine to enable EVA automation.

Install:
    pip install websockets speechrecognition pyaudio watchdog psutil

Run:
    python eva_local_agent.py

Then in EVA chat say:
    "create file test.txt with hello world"
    "run script main.py"
    "open chrome"
    "move file a.py to folder src"
"""

import asyncio
import json
import os
import subprocess
import shutil
import platform
import websockets
import logging
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('EVA-Agent')

# ── Config ────────────────────────────────────────────────
BACKEND_WS  = os.getenv("EVA_BACKEND_WS", "ws://localhost:8002/agent/ws")
AGENT_TOKEN = os.getenv("EVA_AGENT_TOKEN", "eva_agent_secret_2025")
WORK_DIR    = Path(os.getenv("EVA_WORK_DIR", str(Path.home() / "EVA_workspace")))
WORK_DIR.mkdir(parents=True, exist_ok=True)

# ── File Operations ───────────────────────────────────────
def create_file(filename: str, content: str = "") -> dict:
    path = WORK_DIR / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"status": "success", "message": f"Created {filename}", "path": str(path)}

def read_file(filename: str) -> dict:
    path = WORK_DIR / filename
    if not path.exists():
        return {"status": "error", "message": f"{filename} not found"}
    return {"status": "success", "content": path.read_text(encoding="utf-8"), "path": str(path)}

def delete_file(filename: str) -> dict:
    path = WORK_DIR / filename
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()
    else:
        return {"status": "error", "message": f"{filename} not found"}
    return {"status": "success", "message": f"Deleted {filename}"}

def move_file(source: str, destination: str) -> dict:
    src  = WORK_DIR / source
    dest = WORK_DIR / destination
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return {"status": "success", "message": f"Moved {source} → {destination}"}

def list_files(folder: str = "") -> dict:
    path = WORK_DIR / folder
    if not path.exists():
        return {"status": "error", "message": "Folder not found"}
    files = [str(f.relative_to(WORK_DIR)) for f in path.iterdir()]
    return {"status": "success", "files": files, "count": len(files)}

def create_folder(foldername: str) -> dict:
    path = WORK_DIR / foldername
    path.mkdir(parents=True, exist_ok=True)
    return {"status": "success", "message": f"Created folder {foldername}"}

# ── Code Runner ───────────────────────────────────────────
def run_script(filename: str, args: list = []) -> dict:
    path = WORK_DIR / filename
    if not path.exists():
        return {"status": "error", "message": f"{filename} not found"}
    ext = path.suffix.lower()
    cmd_map = {
        ".py":  ["python", str(path)] + args,
        ".js":  ["node", str(path)] + args,
        ".sh":  ["bash", str(path)] + args,
        ".bat": [str(path)] + args,
        ".ps1": ["powershell", "-File", str(path)] + args,
    }
    cmd = cmd_map.get(ext)
    if not cmd:
        return {"status": "error", "message": f"Unsupported file type: {ext}"}
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=WORK_DIR)
        return {
            "status": "success" if result.returncode == 0 else "error",
            "stdout": result.stdout[:2000],
            "stderr": result.stderr[:500],
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Script timed out after 30s"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def run_command(command: str) -> dict:
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=15, cwd=WORK_DIR)
        return {
            "status": "success",
            "stdout": result.stdout[:2000],
            "stderr": result.stderr[:500],
            "returncode": result.returncode
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ── App Launcher ──────────────────────────────────────────
def open_app(app_name: str) -> dict:
    apps = {
        "chrome":    "start chrome",
        "firefox":   "start firefox",
        "notepad":   "notepad",
        "vscode":    "code",
        "explorer":  f"explorer {WORK_DIR}",
        "terminal":  "start cmd",
        "powershell":"start powershell",
    }
    cmd = apps.get(app_name.lower(), f"start {app_name}")
    try:
        subprocess.Popen(cmd, shell=True)
        return {"status": "success", "message": f"Opened {app_name}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def open_url(url: str) -> dict:
    import webbrowser
    webbrowser.open(url)
    return {"status": "success", "message": f"Opened {url}"}

# ── System Info ───────────────────────────────────────────
def system_info() -> dict:
    import psutil
    return {
        "status": "success",
        "os": platform.system(),
        "cpu_percent": psutil.cpu_percent(interval=1),
        "memory_percent": psutil.virtual_memory().percent,
        "disk_percent": psutil.disk_usage('/').percent,
        "work_dir": str(WORK_DIR),
        "timestamp": datetime.now().isoformat()
    }

# ── Task Router ───────────────────────────────────────────
def execute_task(task: dict) -> dict:
    action = task.get("action", "")
    params = task.get("params", {})
    logger.info(f"Executing: {action} | params: {params}")

    routes = {
        "create_file":    lambda: create_file(params.get("filename",""), params.get("content","")),
        "read_file":      lambda: read_file(params.get("filename","")),
        "delete_file":    lambda: delete_file(params.get("filename","")),
        "move_file":      lambda: move_file(params.get("source",""), params.get("destination","")),
        "list_files":     lambda: list_files(params.get("folder","")),
        "create_folder":  lambda: create_folder(params.get("foldername","")),
        "run_script":     lambda: run_script(params.get("filename",""), params.get("args",[])),
        "run_command":    lambda: run_command(params.get("command","")),
        "open_app":       lambda: open_app(params.get("app","")),
        "open_url":       lambda: open_url(params.get("url","")),
        "system_info":    lambda: system_info(),
    }

    handler = routes.get(action)
    if handler:
        try:
            return handler()
        except Exception as e:
            return {"status": "error", "message": str(e)}
    return {"status": "error", "message": f"Unknown action: {action}"}

# ── WebSocket Client ──────────────────────────────────────
async def connect_to_backend():
    logger.info(f"Connecting to EVA backend: {BACKEND_WS}")
    while True:
        try:
            uri = f"{BACKEND_WS}?token={AGENT_TOKEN}"
            async with websockets.connect(
                uri,
                additional_headers={"X-Agent-Token": AGENT_TOKEN},
                ping_interval=30,
                ping_timeout=10,
            ) as ws:
                logger.info("✅ Connected to EVA backend!")
                await ws.send(json.dumps({"type": "register", "agent": "windows_local", "platform": platform.system()}))
                async for message in ws:
                    try:
                        data = json.loads(message)
                        if data.get("type") == "task":
                            result = execute_task(data)
                            await ws.send(json.dumps({"type": "result", "task_id": data.get("task_id"), "result": result}))
                    except Exception as e:
                        logger.error(f"Task error: {e}")
        except Exception as e:
            logger.warning(f"Disconnected: {e} — retrying in 5s...")
            await asyncio.sleep(5)

# ── Voice Activation ──────────────────────────────────────
async def voice_listener():
    try:
        import speech_recognition as sr
        r  = sr.Recognizer()
        mic = sr.Microphone()
        logger.info("🎙️ Voice activation ready — say 'Hey EVA'")
        with mic as source:
            r.adjust_for_ambient_noise(source)
        while True:
            with mic as source:
                audio = await asyncio.get_event_loop().run_in_executor(None, lambda: r.listen(source, timeout=3, phrase_time_limit=5))
            try:
                text = r.recognize_google(audio).lower()
                if "hey eva" in text or "eva" in text:
                    command = text.replace("hey eva", "").replace("eva", "").strip()
                    logger.info(f"🎙️ Voice command: {command}")
                    # Parse and execute basic voice commands
                    if "create file" in command:
                        filename = command.replace("create file", "").strip().split()[0]
                        result = create_file(filename)
                        logger.info(f"Voice result: {result}")
                    elif "open" in command:
                        app = command.replace("open", "").strip()
                        open_app(app)
            except Exception:
                pass
    except ImportError:
        logger.info("Voice activation disabled — install: pip install SpeechRecognition pyaudio")

# ── Main ──────────────────────────────────────────────────
async def main():
    logger.info("=" * 50)
    logger.info("EVA Local Agent Starting")
    logger.info(f"Work directory: {WORK_DIR}")
    logger.info(f"Backend: {BACKEND_WS}")
    logger.info("=" * 50)
    await asyncio.gather(
        connect_to_backend(),
        voice_listener(),
    )

if __name__ == "__main__":
    asyncio.run(main())
