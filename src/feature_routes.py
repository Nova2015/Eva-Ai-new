"""
EVA Feature Routes
==================
New routes to add to app.py:

    from feature_routes import router as feature_router
    app.include_router(feature_router, tags=["Features"])

Endpoints:
    POST /youtube/search     — Search YouTube videos
    POST /youtube/monitor    — Monitor a channel for new videos
    GET  /youtube/alerts     — Get new video alerts
    POST /monitor/add        — Add website to change monitor
    GET  /monitor/check      — Check all monitored sites for changes
    POST /sandbox/run        — Run code via Piston API (free)
"""

import os
import json
import time
import hashlib
import logging
from datetime import datetime
from typing import Optional, List
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Storage (simple JSON files, upgrade to DB later) ──────────────────────────
DATA_DIR = Path(os.getenv("EVA_DATA_DIR", "/tmp/eva_data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

MONITORS_FILE = DATA_DIR / "monitors.json"
YT_MONITORS_FILE = DATA_DIR / "yt_monitors.json"

def _load_json(path: Path, default=None):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default if default is not None else {}

def _save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, default=str))


# ══════════════════════════════════════════════════════════════════════════════
# YOUTUBE MONITOR
# ══════════════════════════════════════════════════════════════════════════════

YT_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

class YouTubeSearchRequest(BaseModel):
    query: str
    max_results: int = 5

class YouTubeMonitorRequest(BaseModel):
    channel_id: Optional[str] = None
    channel_name: Optional[str] = None
    keyword: Optional[str] = None
    user_id: str = "default"
    label: Optional[str] = None

@router.post("/youtube/search")
async def youtube_search(req: YouTubeSearchRequest):
    """Search YouTube videos."""
    if not YT_API_KEY:
        # Fallback: use Groq to describe what results would look like
        return {
            "results": [],
            "error": "YOUTUBE_API_KEY not set. Add it to your .env file.",
            "hint": "Get a free key at https://console.cloud.google.com"
        }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "part": "snippet",
                    "q": req.query,
                    "maxResults": min(req.max_results, 10),
                    "type": "video",
                    "order": "date",
                    "key": YT_API_KEY,
                }
            )
            data = r.json()
            if "error" in data:
                raise HTTPException(status_code=400, detail=data["error"]["message"])

            results = []
            for item in data.get("items", []):
                snippet = item.get("snippet", {})
                video_id = item.get("id", {}).get("videoId", "")
                results.append({
                    "title": snippet.get("title"),
                    "channel": snippet.get("channelTitle"),
                    "published": snippet.get("publishedAt"),
                    "description": snippet.get("description", "")[:200],
                    "url": f"https://youtube.com/watch?v={video_id}",
                    "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url"),
                    "video_id": video_id,
                })
            return {"results": results, "query": req.query}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/youtube/monitor")
async def youtube_monitor_add(req: YouTubeMonitorRequest):
    """Add a YouTube channel or keyword to monitor."""
    monitors = _load_json(YT_MONITORS_FILE, [])
    entry = {
        "id": f"yt_{int(time.time())}",
        "channel_id": req.channel_id,
        "channel_name": req.channel_name,
        "keyword": req.keyword,
        "user_id": req.user_id,
        "label": req.label or req.channel_name or req.keyword or "Monitor",
        "last_checked": None,
        "last_video_id": None,
        "alerts": [],
        "created_at": datetime.utcnow().isoformat(),
    }
    monitors.append(entry)
    _save_json(YT_MONITORS_FILE, monitors)
    return {"ok": True, "monitor": entry, "message": f"Now monitoring: {entry['label']}"}


@router.get("/youtube/alerts")
async def youtube_check_alerts(user_id: str = "default"):
    """Check all YouTube monitors for new videos."""
    monitors = _load_json(YT_MONITORS_FILE, [])
    user_monitors = [m for m in monitors if m.get("user_id") == user_id]
    if not user_monitors:
        return {"alerts": [], "message": "No YouTube monitors set up yet."}

    if not YT_API_KEY:
        return {"alerts": [], "error": "YOUTUBE_API_KEY not set"}

    all_alerts = []
    for monitor in user_monitors:
        try:
            query = monitor.get("keyword") or monitor.get("channel_name") or ""
            if not query:
                continue
            async with httpx.AsyncClient(timeout=10) as client:
                params = {
                    "part": "snippet",
                    "q": query,
                    "maxResults": 3,
                    "type": "video",
                    "order": "date",
                    "key": YT_API_KEY,
                }
                if monitor.get("channel_id"):
                    params["channelId"] = monitor["channel_id"]
                r = await client.get("https://www.googleapis.com/youtube/v3/search", params=params)
                data = r.json()
                items = data.get("items", [])
                if items:
                    latest = items[0]
                    video_id = latest.get("id", {}).get("videoId", "")
                    if video_id and video_id != monitor.get("last_video_id"):
                        snippet = latest.get("snippet", {})
                        alert = {
                            "monitor_id": monitor["id"],
                            "label": monitor["label"],
                            "title": snippet.get("title"),
                            "channel": snippet.get("channelTitle"),
                            "published": snippet.get("publishedAt"),
                            "url": f"https://youtube.com/watch?v={video_id}",
                            "is_new": True,
                        }
                        all_alerts.append(alert)
                        # Update last seen
                        monitor["last_video_id"] = video_id
                        monitor["last_checked"] = datetime.utcnow().isoformat()
        except Exception as e:
            logger.error(f"YouTube monitor check failed: {e}")

    _save_json(YT_MONITORS_FILE, monitors)
    return {"alerts": all_alerts, "checked": len(user_monitors)}


# ══════════════════════════════════════════════════════════════════════════════
# WEBSITE CHANGE DETECTOR
# ══════════════════════════════════════════════════════════════════════════════

class MonitorAddRequest(BaseModel):
    url: str
    label: Optional[str] = None
    user_id: str = "default"
    css_selector: Optional[str] = None

@router.post("/monitor/add")
async def monitor_add(req: MonitorAddRequest):
    """Add a website URL to monitor for changes."""
    if not req.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")

    monitors = _load_json(MONITORS_FILE, [])

    # Fetch initial content hash
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            r = await client.get(req.url, headers={"User-Agent": "EVA-Monitor/2.0"})
            content = r.text
            content_hash = hashlib.md5(content[:50000].encode()).hexdigest()
            word_count = len(content.split())
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not fetch URL: {e}")

    entry = {
        "id": f"mon_{int(time.time())}",
        "url": req.url,
        "label": req.label or req.url,
        "user_id": req.user_id,
        "initial_hash": content_hash,
        "last_hash": content_hash,
        "word_count": word_count,
        "changes": [],
        "last_checked": datetime.utcnow().isoformat(),
        "created_at": datetime.utcnow().isoformat(),
    }
    monitors.append(entry)
    _save_json(MONITORS_FILE, monitors)
    return {"ok": True, "monitor": entry, "message": f"Now monitoring: {req.label or req.url}"}


@router.get("/monitor/check")
async def monitor_check(user_id: str = "default"):
    """Check all monitored websites for changes."""
    monitors = _load_json(MONITORS_FILE, [])
    user_monitors = [m for m in monitors if m.get("user_id") == user_id]

    if not user_monitors:
        return {"changes": [], "message": "No websites being monitored yet."}

    changes = []
    for monitor in user_monitors:
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                r = await client.get(monitor["url"], headers={"User-Agent": "EVA-Monitor/2.0"})
                content = r.text
                new_hash = hashlib.md5(content[:50000].encode()).hexdigest()
                new_word_count = len(content.split())

                if new_hash != monitor.get("last_hash"):
                    change = {
                        "monitor_id": monitor["id"],
                        "label": monitor["label"],
                        "url": monitor["url"],
                        "detected_at": datetime.utcnow().isoformat(),
                        "word_count_before": monitor.get("word_count", 0),
                        "word_count_after": new_word_count,
                        "word_diff": new_word_count - monitor.get("word_count", 0),
                    }
                    changes.append(change)
                    monitor["last_hash"] = new_hash
                    monitor["word_count"] = new_word_count
                    monitor["changes"].append(change)

                monitor["last_checked"] = datetime.utcnow().isoformat()
        except Exception as e:
            logger.error(f"Monitor check failed for {monitor['url']}: {e}")

    _save_json(MONITORS_FILE, monitors)
    return {
        "changes": changes,
        "checked": len(user_monitors),
        "changes_found": len(changes),
    }


@router.get("/monitor/list")
async def monitor_list(user_id: str = "default"):
    """List all monitored websites."""
    monitors = _load_json(MONITORS_FILE, [])
    return {"monitors": [m for m in monitors if m.get("user_id") == user_id]}


@router.delete("/monitor/{monitor_id}")
async def monitor_delete(monitor_id: str):
    """Remove a website monitor."""
    monitors = _load_json(MONITORS_FILE, [])
    monitors = [m for m in monitors if m.get("id") != monitor_id]
    _save_json(MONITORS_FILE, monitors)
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
# CODE SANDBOX (Piston API — free, no key needed)
# ══════════════════════════════════════════════════════════════════════════════

PISTON_URL = "https://emkc.org/api/v2/piston"

# Language version map for Piston
LANG_VERSIONS = {
    "python":     "3.10.0",
    "javascript": "18.15.0",
    "typescript": "5.0.3",
    "java":       "15.0.2",
    "cpp":        "10.2.0",
    "c":          "10.2.0",
    "rust":       "1.50.0",
    "go":         "1.16.2",
    "bash":       "5.2.0",
    "sql":        "3.36.0",
    "ruby":       "3.0.1",
    "php":        "8.2.3",
}

class SandboxRequest(BaseModel):
    code: str
    language: str = "python"
    stdin: Optional[str] = ""
    timeout: int = 10

@router.post("/sandbox/run")
async def sandbox_run(req: SandboxRequest):
    """
    Execute code safely via Piston API.
    Free, no API key needed, supports 50+ languages.
    """
    lang = req.language.lower().strip()
    if lang not in LANG_VERSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Language '{lang}' not supported. Supported: {', '.join(LANG_VERSIONS.keys())}"
        )

    # Basic safety check — block dangerous patterns
    blocked = ["import os", "import subprocess", "import sys", "__import__",
               "open(", "exec(", "eval(", "rm -rf", "os.system"]
    for pattern in blocked:
        if pattern in req.code:
            raise HTTPException(status_code=400, detail=f"Blocked pattern: '{pattern}'")

    if len(req.code) > 10000:
        raise HTTPException(status_code=400, detail="Code too long (max 10,000 chars)")

    try:
        async with httpx.AsyncClient(timeout=req.timeout + 5) as client:
            payload = {
                "language": lang,
                "version": LANG_VERSIONS[lang],
                "files": [{"name": f"main.{_ext(lang)}", "content": req.code}],
                "stdin": req.stdin or "",
                "args": [],
                "compile_timeout": 10000,
                "run_timeout": req.timeout * 1000,
            }
            r = await client.post(f"{PISTON_URL}/execute", json=payload)
            data = r.json()

            run = data.get("run", {})
            compile_result = data.get("compile", {})

            return {
                "ok": True,
                "language": lang,
                "stdout": run.get("stdout", ""),
                "stderr": run.get("stderr", ""),
                "output": run.get("output", ""),
                "exit_code": run.get("code", 0),
                "compile_error": compile_result.get("stderr", "") if compile_result else "",
                "execution_time": run.get("cpu_time"),
            }
    except httpx.TimeoutException:
        raise HTTPException(status_code=408, detail="Code execution timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sandbox error: {e}")


def _ext(lang: str) -> str:
    return {
        "python": "py", "javascript": "js", "typescript": "ts",
        "java": "java", "cpp": "cpp", "c": "c", "rust": "rs",
        "go": "go", "bash": "sh", "ruby": "rb", "php": "php", "sql": "sql",
    }.get(lang, "txt")


@router.get("/sandbox/languages")
async def sandbox_languages():
    """List supported languages."""
    return {"languages": list(LANG_VERSIONS.keys())}
