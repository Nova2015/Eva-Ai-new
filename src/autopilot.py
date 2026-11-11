"""
Update 64 Ã¢â‚¬â€ Autopilot: autonomous multi-step tasks
==================================================
Goal in, researched report out, without step-by-step prompting:

    goal -> plan (LLM) -> execute tools in sequence -> synthesise -> report

Why this is safe to run unattended
----------------------------------
Autonomy is bounded by what the agent CAN do, not by what we ask it not to.
Every tool in the registry is READ-ONLY and side-effect free:

    web_search   read-only browser web research
    read_url     browser-read a public page and extract rendered text
    rag_query    ask EVA's own indexed knowledge base
    think        reason over what has been gathered so far

There is deliberately no tool that writes, sends, deletes, posts, executes
code, or spends money. An autonomous loop that can only read and summarise
cannot do damage if the planner goes wrong Ã¢â‚¬â€ the worst case is a bad report.
Anything with real-world side effects stays behind explicit human approval
(see agents/approval_gate.py) and is out of scope here.

Bounded by construction: max steps, wall-clock deadline, per-tool timeouts,
output truncation, and cooperative cancellation checked between steps.

Storage note: tasks live in the backend's instance-local sqlite, which Render
resets on redeploy. Finished reports are returned in full and can be copied
out; durable storage is the same open item as the review queue.
"""

import asyncio
import base64
import html
import ipaddress
import json
import logging
import os
import re
import socket
import sqlite3
import threading
import xml.etree.ElementTree as ET
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.learning_loop import _db as _loop_db, require_train_admin

try:
    from browser_use import BrowserSession, Tools
    BROWSER_USE_AVAILABLE = True
except Exception as _browser_import_error:
    BrowserSession = None
    Tools = None
    BROWSER_USE_AVAILABLE = False
    logger = logging.getLogger("EVA.autopilot")
    logger.warning(
        "[AUTOPILOT] browser-use unavailable: %s",
        type(_browser_import_error).__name__,
    )

logger = logging.getLogger("EVA.autopilot")
router = APIRouter()

HF_ML_URL = os.getenv("HF_ML_URL", "http://127.0.0.1:7860").rstrip("/")

MAX_STEPS = int(os.getenv("AUTOPILOT_MAX_STEPS", "10"))
DEADLINE_SECONDS = int(os.getenv("AUTOPILOT_DEADLINE_SECONDS", "300"))
TOOL_TIMEOUT = 25
MAX_TOOL_CHARS = 6000
MAX_CONTEXT_CHARS = 18000

STATUS_RUNNING = "RUNNING"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"
STATUS_CANCELLED = "CANCELLED"

_cancelled: set = set()
_lock = threading.Lock()
_tables_ready = False


def _now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _db() -> sqlite3.Connection:
    global _tables_ready
    conn = _loop_db()
    if not _tables_ready:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS autopilot_tasks ("
            " id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,"
            " goal TEXT NOT NULL, status TEXT NOT NULL, progress INTEGER DEFAULT 0,"
            " plan TEXT, steps TEXT, report TEXT, error TEXT)"
        )
        conn.commit()
        _tables_ready = True
    return conn


def _update(task_id: str, **fields: Any) -> None:
    sets, vals = ["updated_at = ?"], [_now()]
    for k, v in fields.items():
        sets.append(f"{k} = ?")
        vals.append(json.dumps(v) if isinstance(v, (dict, list)) else v)
    vals.append(task_id)
    with _lock:
        conn = _db()
        conn.execute(f"UPDATE autopilot_tasks SET {', '.join(sets)} WHERE id = ?", vals)
        conn.commit()


# Ã¢â€â‚¬Ã¢â€â‚¬ Tools (read-only, every one) Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def _is_public_url(url: str) -> bool:
    """Allow only public http(s) URLs; reject localhost/private/link-local targets."""
    try:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return False

        host = parsed.hostname.rstrip(".").lower()
        if host in {"localhost", "localhost.localdomain"}:
            return False

        # Resolve the hostname and reject every resolved address that is not public.
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80),
                                   type=socket.SOCK_STREAM)
        if not infos:
            return False

        resolved_ips = [ipaddress.ip_address(info[4][0]) for info in infos]

        # Reject only when every resolved address is non-global.
        # Some Windows DNS paths can return a reserved IPv6 translation
        # address together with a genuinely public IPv4 address.
        if not any(ip.is_global for ip in resolved_ips):
            return False

        return True
    except Exception:
        return False


def _clean_research_text(text: str) -> str:
    """Normalize browser-rendered research text before it reaches the LLM."""
    value = text or ""

    # Remove browser-use DOM/SVG noise while preserving visible article text.
    value = re.sub(r"<!--.*?-->", " ", value, flags=re.S)
    value = re.sub(r"<svg\b[^>]*/\s*>", " ", value, flags=re.I)
    value = re.sub(r"<svg\b.*?</svg\s*>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<(?:div|span|a|button|nav|main|input|section|header|footer)\b[^>]*/\s*>", " ", value, flags=re.I)
    value = re.sub(r"<(?:div|span|a|button|nav|main|input|section|header|footer)\b[^>]*>", " ", value, flags=re.I)
    value = re.sub(r"</(?:div|span|a|button|nav|main|input|section|header|footer)>", " ", value, flags=re.I)
    value = re.sub(r"\[\d+\]\s*", "", value)
    value = re.sub(r"<[^>]+>", " ", value)

    lines = []
    for raw_line in value.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if line.lower() in {"read blog", "read more"}:
            continue
        if re.search(r"cookies?\b|privacy policy|cookie policy|manage settings|reject optional|accept all|for more information on our privacy practices", line, re.I):
            continue
        lines.append(line)

    value = "\n".join(lines)
    value = re.sub(r"\n{3,}", "\n\n", value).strip()
    return value


def _normalize_research_query(query: str) -> str:
    """Convert a natural-language research request into a concise web-search query."""
    q = re.sub(r"\s+", " ", (query or "").strip())
    if not q:
        return ""

    # Remove conversational question framing while preserving the subject and intent.
    q = re.sub(
        r"^(what is|what's|what|tell me|show me|give me|can you tell me|"
        r"please tell me|i want to know)\s+",
        "",
        q,
        flags=re.I,
    )
    q = re.sub(r"\b(are|is)\s+there\s+", "", q, flags=re.I)
    q = re.sub(r"^(are|is)\s+the\s+", "", q, flags=re.I)
    q = re.sub(r"\b(about|regarding|concerning)\b", " ", q, flags=re.I)
    q = re.sub(r"\b(updates?|information|details?)\b", " ", q, flags=re.I)
    q = re.sub(r"[?!.]+$", "", q).strip()
    q = re.sub(r"\s+", " ", q)

    # Keep explicit freshness intent and the actual subject.
    if re.search(r"\b(latest|current|today|recent|newest|news)\b", q, re.I):
        subject = re.sub(
            r"\b(latest|current|today|recent|newest)(?:[\u0027\u2019]s)?\b",
            "",
            q,
            flags=re.I,
        )
        subject = re.sub(r"\s+", " ", subject).strip()
        if "news" not in subject.lower():
            subject = f"{subject} latest news"
        else:
            subject = re.sub(r"\bnews\b", "latest news", subject, count=1, flags=re.I)
        return subject.strip()

    return q

def _research_relevance_score(query: str, title: str, url: str) -> int:
    """Rank search candidates for evidence quality without using an LLM."""
    q = (query or "").lower()
    text = f"{title or ''} {url or ''}".lower()
    tokens = {
        token for token in re.findall(r"[a-z0-9][a-z0-9._-]{2,}", q)
        if token not in {"the", "and", "for", "with", "from", "latest", "current", "today", "recent"}
    }

    score = 0

    # Query-term relevance.
    for token in tokens:
        if token in (title or "").lower():
            score += 8
        if token in text:
            score += 3

    # Freshness/news intent.
    freshness_intent = bool(
        re.search(r"\\b(latest|current|today|recent|news|newest|up[- ]to[- ]date)\\b", q, re.I)
    )
    host = (urlparse(url).hostname or "").lower()
    base_host = host[4:] if host.startswith("www.") else host

    if freshness_intent:
        if base_host in {
            "nvidianews.nvidia.com",
            "reuters.com",
            "apnews.com",
            "bloomberg.com",
            "cnbc.com",
            "finance.yahoo.com",
        }:
            score += 35
        if "news" in (title or "").lower():
            score += 10

    # Strong first-party evidence.
    if base_host == "nvidia.com" or base_host.endswith(".nvidia.com"):
        score += 28
    if base_host == "nvidianews.nvidia.com":
        score += 45
    if base_host == "investor.nvidia.com":
        score += 32

    # Penalize generic/support/store/reference pages for news-style questions.
    if freshness_intent:
        if base_host in {"wikipedia.org", "apps.microsoft.com"}:
            score -= 25
        if re.search(r"\\b(driver|download|store|wiki)\\b", text, re.I):
            score -= 12

    return score


def _decode_bing_result_url(href: str) -> Optional[str]:
    """Decode Bing's /ck/a wrapper into the actual destination URL."""
    try:
        parsed = urlparse(href)
        if parsed.netloc.lower() not in {"www.bing.com", "bing.com"}:
            return href if href.startswith(("http://", "https://")) else None

        encoded = parse_qs(parsed.query).get("u", [""])[0]
        if not encoded:
            return None

        encoded = unquote(encoded)
        if encoded.startswith("a1"):
            encoded = encoded[2:]

        padding = "=" * ((4 - len(encoded) % 4) % 4)
        decoded = base64.urlsafe_b64decode(encoded + padding).decode("utf-8", "ignore")
        if decoded.startswith(("http://", "https://")):
            return decoded
    except Exception:
        pass
    return None


def _run_browser_sync(coro_factory):
    """Run browser-use from EVA's synchronous tool adapter without blocking its event loop."""
    result: Dict[str, Any] = {}
    finished = threading.Event()

    def worker() -> None:
        try:
            result["value"] = asyncio.run(coro_factory())
        except BaseException as exc:
            result["error"] = exc
        finally:
            finished.set()

    thread = threading.Thread(
        target=worker,
        name="eva-browser-worker",
        daemon=True,
    )
    thread.start()

    if not finished.wait(timeout=TOOL_TIMEOUT + 10):
        raise TimeoutError("browser research timed out")

    if "error" in result:
        raise result["error"]
    return result.get("value")


async def _browser_search(query: str) -> str:
    session = BrowserSession(headless=True)
    tools = Tools()
    await session.start()

    try:
        research_query = _normalize_research_query(query)
        await tools.registry.execute_action(
            "search",
            {"query": research_query or query, "engine": "bing"},
            browser_session=session,
        )

        result = await tools.registry.execute_action(
            "find_elements",
            {
                "selector": "a",
                "attributes": ["href"],
                "max_results": 100,
                "include_text": True,
            },
            browser_session=session,
        )

        raw = getattr(result, "extracted_content", "") or ""
        candidates: List[tuple[str, str]] = []
        seen = set()

        for match in re.finditer(
            r'\[\d+\]\s*<a>(.*?)\{href="([^"]+)"\}',
            raw,
            flags=re.S,
        ):
            title = re.sub(r"\s+", " ", match.group(1)).strip()
            href = match.group(2)
            url = _decode_bing_result_url(href)

            if not url or not _is_public_url(url):
                continue

            host = (urlparse(url).hostname or "").lower()
            if not host or host.endswith("bing.com"):
                continue

            key = url.split("#", 1)[0]
            if key in seen:
                continue

            seen.add(key)
            candidates.append((title or host, key))

        # Rank candidates before reading pages so evidence quality follows
        # the user's intent rather than raw search-result order.
        candidates.sort(
            key=lambda item: _research_relevance_score(query, item[0], item[1]),
            reverse=True,
        )

        # Read a small, diverse set of real result pages.
        sources: List[str] = []
        domains = set()

        for title, url in candidates:
            host = (urlparse(url).hostname or "").lower()
            base_host = host[4:] if host.startswith("www.") else host

            if base_host in domains:
                continue

            try:
                await tools.registry.execute_action(
                    "navigate",
                    {"url": url, "new_tab": False},
                    browser_session=session,
                )

                final_url = await session.get_current_page_url()
                if not final_url or not _is_public_url(final_url):
                    continue

                final_host = (urlparse(final_url).hostname or "").lower()
                final_base = final_host[4:] if final_host.startswith("www.") else final_host
                if final_base in domains:
                    continue

                page_title = await session.get_current_page_title()
                state = await session.get_state_as_text()
                state = _clean_research_text(state)

                if len(state) < 120:
                    continue

                domains.add(final_base)
                sources.append(
                    f"RESEARCH SOURCE {len(sources) + 1}\n"
                    f"Title: {page_title or title}\n"
                    f"URL: {final_url}\n"
                    f"Content:\n{state[:2200]}"
                )

                if len(sources) >= 3:
                    break
            except Exception as exc:
                logger.warning(
                    "[AUTOPILOT] browser source failed %s: %s",
                    url,
                    type(exc).__name__,
                )

        if not sources:
            return "No readable public sources were retrieved from Bing."

        return "\n\n".join(sources)[:MAX_TOOL_CHARS]
    finally:
        await session.stop()


def _http_news_search(query: str) -> str:
    """Read current news through Google News RSS with freshness filtering."""
    try:
        from datetime import datetime, timedelta, timezone
        from email.utils import parsedate_to_datetime
        from zoneinfo import ZoneInfo

        search_query = _normalize_research_query(query) or query
        params = {
            "q": search_query,
            "hl": "en-IN",
            "gl": "IN",
            "ceid": "IN:en",
        }

        with httpx.Client(
            timeout=TOOL_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "EVA-Autopilot/1.0"},
        ) as client:
            r = client.get(
                "https://news.google.com/rss/search",
                params=params,
            )
            r.raise_for_status()

        root = ET.fromstring(r.content)
        items = root.findall("./channel/item")

        if not items:
            return "No sufficiently fresh public news sources were retrieved."

        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        query_lower = (query or "").lower()

        today_only = bool(re.search(r"\btoday\b", query_lower))
        cutoff = now if today_only else now - timedelta(days=7)

        sources = []
        seen = set()

        for item in items[:12]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            description = (item.findtext("description") or "").strip()

            source_el = item.find("source")
            publisher = (
                (source_el.text or "").strip()
                if source_el is not None and source_el.text
                else ""
            )
            publisher_url = (
                (source_el.get("url") or "").strip()
                if source_el is not None
                else ""
            )

            if not title or not link or not pub_date:
                continue
            if link in seen or not _is_public_url(link):
                continue

            try:
                published = parsedate_to_datetime(pub_date)
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                published = published.astimezone(ZoneInfo("Asia/Kolkata"))
            except (TypeError, ValueError, OverflowError):
                continue

            if published > now + timedelta(minutes=5):
                continue

            if today_only:
                if published.date() != now.date():
                    continue
            elif published < cutoff:
                continue

            seen.add(link)

            description = html.unescape(description)
            description = re.sub(r"<[^>]+>", " ", description)
            description = re.sub(r"\s+", " ", description).strip()

            content_parts = []

            # Extract only outcomes explicitly stated in the publisher headline.
            # This helps small local models use headline-level facts without
            # inventing scores, margins, or statistics.
            headline_outcome = None

            match = re.search(
                r"\b([A-Z][A-Za-z-]+)(?:['\u2019]s)\b.*?\b(?:win|victory)\b.*?\bover\s+([A-Z][A-Za-z-]+)\b",
                title,
                flags=re.I,
            )
            if match:
                headline_outcome = (
                    f"{match.group(1)} won against {match.group(2)}"
                )
            else:
                match = re.search(
                    r"\b([A-Z][A-Za-z-]+)\s+(?:won|defeated)\s+([A-Z][A-Za-z-]+)\b",
                    title,
                    flags=re.I,
                )
                if match:
                    headline_outcome = (
                        f"{match.group(1)} won against {match.group(2)}"
                    )
                else:
                    match = re.search(
                        r"\b([A-Z][A-Za-z-]+)\s+lost\s+to\s+([A-Z][A-Za-z-]+)\b",
                        title,
                        flags=re.I,
                    )
                    if match:
                        headline_outcome = (
                            f"{match.group(1)} lost to {match.group(2)}"
                        )

            if headline_outcome:
                content_parts.append(
                    f"Explicit source-supported outcome: {headline_outcome}."
                )
            if publisher:
                content_parts.append(f"Publisher: {publisher}")

            content_parts.append(
                f"Published: {published.strftime('%a, %d %b %Y %H:%M:%S %z')}"
            )

            if publisher_url and _is_public_url(publisher_url):
                content_parts.append(f"Publisher URL: {publisher_url}")

            if description:
                content_parts.append(f"Summary: {description[:1200]}")

            sources.append(
                f"RESEARCH SOURCE {len(sources) + 1}\n"
                f"Title: {title}\n"
                f"URL: {link}\n"
                f"Content:\n" + "\n".join(content_parts)
            )

            if len(sources) >= 3:
                break

        if sources:
            return "\n\n".join(sources)[:MAX_TOOL_CHARS]

        return "No sufficiently fresh public news sources were retrieved."

    except Exception as exc:
        return f"News search unavailable: {type(exc).__name__}"

def _tool_web_search(query: str) -> str:
    if not query.strip():
        return "No search query provided."

    # News/current/latest requests use Bing News directly because the normal
    # Bing page can contain navigation/driver links rather than article results.
    if re.search(
        r"\b(latest|current|today|recent|newest|news)\b",
        query,
        re.I,
    ):
        try:
            result = _http_news_search(query)
            if result and not result.startswith("No readable public news sources"):
                return result
        except Exception as exc:
            logger.warning(
                "[AUTOPILOT] direct news search failed: %s",
                type(exc).__name__,
            )

    if BROWSER_USE_AVAILABLE:
        try:
            return _run_browser_sync(lambda: _browser_search(query))
        except Exception as exc:
            logger.warning(
                "[AUTOPILOT] browser search failed; using HTTP fallback: %s",
                type(exc).__name__,
            )

    # Safe HTTP fallback for ordinary web research.
    try:
        with httpx.Client(
            timeout=TOOL_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "EVA-Autopilot/1.0"},
        ) as client:
            r = client.get(
                "https://www.bing.com/search",
                params={"q": query},
            )
            r.raise_for_status()

            links = re.findall(
                r'<a[^>]+href=["'']([^"'']+)["''][^>]*>(.*?)</a>',
                r.text,
                flags=re.S | re.I,
            )
            candidates = []
            seen = set()

            for href, title_html in links:
                href = html.unescape(href)
                url = _decode_bing_result_url(href)
                if not url or not _is_public_url(url):
                    continue

                host = (urlparse(url).hostname or "").lower()
                if not host or host.endswith("bing.com"):
                    continue

                key = url.split("#", 1)[0]
                if key in seen:
                    continue

                title = re.sub(r"<[^>]+>", " ", html.unescape(title_html))
                title = re.sub(r"\s+", " ", title).strip()
                if not title:
                    continue

                if title.lower() in {
                    "web", "images", "videos", "maps", "news",
                    "shopping", "flights",
                }:
                    continue

                seen.add(key)
                candidates.append((title, key))

            candidates.sort(
                key=lambda item: _research_relevance_score(
                    query, item[0], item[1]
                ),
                reverse=True,
            )

            sources = []
            for title, url in candidates[:5]:
                try:
                    page = client.get(url)
                    page.raise_for_status()
                    body = page.text

                    page_title_match = re.search(
                        r"<title[^>]*>(.*?)</title>",
                        body,
                        flags=re.S | re.I,
                    )
                    page_title = (
                        re.sub(
                            r"\s+",
                            " ",
                            html.unescape(page_title_match.group(1)),
                        ).strip()
                        if page_title_match
                        else title
                    )

                    text = re.sub(
                        r"<(script|style|noscript|svg)\b[^>]*>.*?</\1>",
                        " ",
                        body,
                        flags=re.S | re.I,
                    )
                    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
                    text = re.sub(r"<[^>]+>", " ", text)
                    text = html.unescape(text)
                    text = _clean_research_text(text)

                    if len(text) < 120:
                        continue

                    sources.append(
                        f"RESEARCH SOURCE {len(sources) + 1}\n"
                        f"Title: {page_title or title}\n"
                        f"URL: {url}\n"
                        f"Content:\n{text[:2200]}"
                    )
                    if len(sources) >= 3:
                        break
                except Exception as exc:
                    logger.debug(
                        "[AUTOPILOT] HTTP result fetch failed %s: %s",
                        url,
                        type(exc).__name__,
                    )

            if sources:
                return "\n\n".join(sources)[:MAX_TOOL_CHARS]

            if candidates:
                return "\n".join(
                    f"{title} [{url}]"
                    for title, url in candidates[:8]
                )

            return "No results."
    except Exception as exc:
        return f"Web search unavailable: {type(exc).__name__}"

async def _browser_read_url(url: str) -> str:
    session = BrowserSession(headless=True)
    tools = Tools()
    await session.start()

    try:
        await tools.registry.execute_action(
            "navigate",
            {"url": url, "new_tab": False},
            browser_session=session,
        )

        final_url = await session.get_current_page_url()
        if not final_url or not _is_public_url(final_url):
            return "Refused: navigation resolved to a non-public address."

        title = await session.get_current_page_title()
        state = await session.get_state_as_text()
        state = re.sub(r"\n{3,}", "\n\n", state or "").strip()

        if not state:
            return "No readable page content was extracted."

        return (
            f"Title: {title or 'Untitled'}\n"
            f"URL: {final_url}\n"
            f"Content:\n{state[:MAX_TOOL_CHARS]}"
        )
    finally:
        await session.stop()


def _tool_read_url(url: str) -> str:
    if not _is_public_url(url):
        return "Refused: only public http(s) URLs are allowed."

    if BROWSER_USE_AVAILABLE:
        try:
            return _run_browser_sync(lambda: _browser_read_url(url))
        except Exception as exc:
            logger.warning(
                "[AUTOPILOT] browser URL read failed; using HTTP fallback: %s",
                type(exc).__name__,
            )

    try:
        with httpx.Client(
            timeout=TOOL_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "EVA-Autopilot/1.0"},
        ) as client:
            r = client.get(url)
            r.raise_for_status()

            final_url = str(r.url)
            if not _is_public_url(final_url):
                return "Refused: redirect resolved to a non-public address."

            if "text/html" not in r.headers.get("content-type", "text/html"):
                return r.text[:MAX_TOOL_CHARS]

            text = re.sub(r"<script[^>]*>.*?</script>", " ", r.text, flags=re.S | re.I)
            text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"&[a-zA-Z#0-9]+;", " ", text)
            text = re.sub(r"\s{2,}", " ", text).strip()

            return (
                f"Title: {r.url}\n"
                f"URL: {final_url}\n"
                f"Content:\n{text[:MAX_TOOL_CHARS]}"
            )
    except Exception as exc:
        return f"URL read failed: {type(exc).__name__}"

def _tool_rag_query(
    question: str,
    workspace_id: str = "default-org",
    source_filter=None,
) -> str:
    payload = {
        "message": question,
        "workspace_id": workspace_id or "default-org",
    }
    if source_filter:
        payload["source_filter"] = os.path.basename(str(source_filter).strip())

    with httpx.Client(timeout=60) as client:
        r = client.post(f"{HF_ML_URL}/rag/chat", json=payload)
        r.raise_for_status()
        d = r.json()

    srcs = ", ".join(d.get("sources") or []) or "none"
    return f"{(d.get('answer') or '')[:MAX_TOOL_CHARS]}\n(sources: {srcs})"


def _llm(prompt: str, max_tokens: int = 900, attempts: int = 3) -> str:
    """Run Autopilot through EVA's centralized provider contract.

    Autopilot must not use the admin-training provider registry because that
    registry intentionally exposes optional cloud providers for prompt testing.
    The shared providers.complete() path owns local-first routing and failover.
    """
    from src.providers import complete

    messages = [{"role": "user", "content": prompt}]

    last_error = "unknown error"

    for attempt in range(attempts):
        try:
            result = complete(
                messages,
                max_tokens=max_tokens,
            )

            if result.ok and (result.text or "").strip():
                logger.info(
                    "[AUTOPILOT] provider=%s model=%s attempt=%d",
                    result.provider,
                    result.model,
                    attempt + 1,
                )
                return result.text

            last_error = ", ".join(result.errors or ["provider unavailable"])
            logger.warning(
                "[AUTOPILOT] provider chain failed (attempt %d): %s",
                attempt + 1,
                last_error,
            )

        except Exception as e:
            last_error = f"{type(e).__name__}: {str(e)[:160]}"
            logger.warning(
                "[AUTOPILOT] provider execution failed (attempt %d): %s",
                attempt + 1,
                last_error,
            )

        if attempt < attempts - 1:
            time.sleep(8 * (attempt + 1))

    raise RuntimeError(
        f"all EVA providers failed after {attempts} attempts ({last_error})"
    )
def _tool_think(instruction: str, context: str) -> str:
    return _llm(f"{instruction}\n\nMaterial gathered so far:\n{context[:MAX_CONTEXT_CHARS]}")


TOOLS = {
    "web_search": "Research the public web through a read-only browser. Input: the search query.",
    "read_url":   "Fetch one public page and extract its text. Input: an absolute URL.",
    "rag_query":  "Ask EVA's own indexed document knowledge base. Input: a question.",
    "think":      "Reason over everything gathered so far. Input: what to work out.",
}


def _run_tool(tool: str, arg: str, context: str) -> str:
    if tool == "web_search":
        return _tool_web_search(arg)
    if tool == "read_url":
        return _tool_read_url(arg)
    if tool == "rag_query":
        return _tool_rag_query(arg)
    if tool == "think":
        return _tool_think(arg, context)
    raise ValueError(f"unknown tool {tool}")


# Ã¢â€â‚¬Ã¢â€â‚¬ Planner + executor Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def _make_plan(goal: str) -> List[Dict[str, str]]:
    tool_doc = "\n".join(f"- {k}: {v}" for k, v in TOOLS.items())
    prompt = (
        "You are a research planner. Break the goal into at most "
        f"{MAX_STEPS - 1} concrete steps using ONLY these tools:\n{tool_doc}\n\n"
        "Rules: start by gathering information before reasoning about it; "
        "use read_url only for URLs a previous search actually returned; "
        "the last step should be a `think` step that assembles the findings.\n"
        'Return ONLY a JSON array like [{"tool":"web_search","input":"...","why":"..."}]\n\n'
        f"GOAL: {goal}"
    )
    raw = _llm(prompt)
    match = re.search(r"\[.*\]", raw, re.S)
    if not match:
        raise RuntimeError("planner returned no JSON array")
    plan = json.loads(match.group(0))
    clean: List[Dict[str, str]] = []
    for step in plan[:MAX_STEPS - 1]:
        tool = str(step.get("tool", "")).strip()
        if tool in TOOLS:
            clean.append({"tool": tool,
                          "input": str(step.get("input", ""))[:500],
                          "why": str(step.get("why", ""))[:200]})
    if not clean:
        raise RuntimeError("planner produced no usable steps")
    return clean


def _run_task(task_id: str, goal: str) -> None:
    started = time.time()
    steps: List[Dict[str, Any]] = []
    context_parts: List[str] = []
    try:
        plan = _make_plan(goal)
        _update(task_id, plan=json.dumps(plan), progress=10)

        for i, step in enumerate(plan, 1):
            if task_id in _cancelled:
                _update(task_id, status=STATUS_CANCELLED, progress=100,
                        steps=json.dumps(steps))
                return
            if time.time() - started > DEADLINE_SECONDS:
                steps.append({"n": i, "tool": "-", "input": "",
                              "output": "Deadline reached; stopping and reporting early.",
                              "ok": False, "seconds": 0})
                break

            t0 = time.time()
            entry = {"n": i, "tool": step["tool"], "input": step["input"],
                     "why": step.get("why", "")}
            try:
                out = _run_tool(step["tool"], step["input"], "\n\n".join(context_parts))
                entry.update(ok=True, output=str(out)[:MAX_TOOL_CHARS])
                context_parts.append(f"[step {i} Ã‚Â· {step['tool']}({step['input']})]\n{out}")
            except Exception as e:
                entry.update(ok=False, output=f"{type(e).__name__}: {str(e)[:200]}")
            entry["seconds"] = round(time.time() - t0, 2)
            steps.append(entry)
            _update(task_id, steps=json.dumps(steps),
                    progress=10 + int(75 * i / max(1, len(plan))))

        material = "\n\n".join(context_parts)[:MAX_CONTEXT_CHARS]
        try:
            report = _llm(
                "Write the final deliverable for this goal using ONLY the material "
                "gathered below. Use markdown with clear headings. Cite source URLs "
                "inline where the material provides them. If the material is thin, "
                "say so plainly instead of padding.\n\n"
                f"GOAL: {goal}\n\nMATERIAL:\n{material}",
                max_tokens=1400,
            )
            degraded = False
        except Exception as e:
            # Synthesis is the last step, but the research before it is the
            # expensive part. Losing a completed multi-step crawl because the
            # final call hit a rate limit is unacceptable, so the gathered
            # material is returned raw with an explicit notice.
            logger.warning("[AUTOPILOT] %s synthesis unavailable: %s", task_id, e)
            report = (
                f"# {goal}\n\n"
                f"> **Synthesis unavailable** ({type(e).__name__}). Every research step below "
                "completed; only the final write-up could not be generated. The raw findings "
                "are preserved here Ã¢â‚¬â€ re-run the task to get the written briefing.\n\n"
                "## Raw findings\n\n" + material
            )
            degraded = True

        _update(task_id, status=STATUS_COMPLETED, progress=100,
                steps=json.dumps(steps), report=report,
                error="synthesis_unavailable" if degraded else None)
        logger.info("[AUTOPILOT] %s completed in %ds (%d steps, degraded=%s)",
                    task_id, int(time.time() - started), len(steps), degraded)
    except Exception as e:
        logger.error("[AUTOPILOT] %s failed: %s", task_id, e)
        _update(task_id, status=STATUS_FAILED, progress=100,
                steps=json.dumps(steps), error=f"{type(e).__name__}: {str(e)[:300]}")
    finally:
        _cancelled.discard(task_id)


# Ã¢â€â‚¬Ã¢â€â‚¬ API Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

class RunBody(BaseModel):
    goal: str


@router.post("/run")
async def autopilot_run(body: RunBody, _: bool = Depends(require_train_admin)):
    goal = (body.goal or "").strip()
    if len(goal) < 8:
        raise HTTPException(status_code=400, detail="Give the task a real goal (8+ characters)")
    task_id = uuid.uuid4().hex[:12]
    with _lock:
        conn = _db()
        conn.execute(
            "INSERT INTO autopilot_tasks (id, created_at, updated_at, goal, status, progress)"
            " VALUES (?, ?, ?, ?, ?, 0)",
            (task_id, _now(), _now(), goal[:500], STATUS_RUNNING),
        )
        conn.commit()
    threading.Thread(target=_run_task, args=(task_id, goal), daemon=True).start()
    return {"ok": True, "id": task_id, "status": STATUS_RUNNING,
            "limits": {"max_steps": MAX_STEPS, "deadline_seconds": DEADLINE_SECONDS}}


@router.get("/tasks")
async def autopilot_tasks(limit: int = Query(20, ge=1, le=100),
                          _: bool = Depends(require_train_admin)):
    rows = _db().execute(
        "SELECT id, created_at, goal, status, progress FROM autopilot_tasks"
        " ORDER BY created_at DESC LIMIT ?", (limit,),
    ).fetchall()
    return {"tasks": [{"id": r[0], "created_at": r[1], "goal": r[2],
                       "status": r[3], "progress": r[4]} for r in rows]}


@router.get("/tasks/{task_id}")
async def autopilot_task(task_id: str, _: bool = Depends(require_train_admin)):
    r = _db().execute(
        "SELECT id, created_at, updated_at, goal, status, progress, plan, steps, report, error"
        " FROM autopilot_tasks WHERE id = ?", (task_id,),
    ).fetchone()
    if r is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"id": r[0], "created_at": r[1], "updated_at": r[2], "goal": r[3],
            "status": r[4], "progress": r[5],
            "plan": json.loads(r[6]) if r[6] else [],
            "steps": json.loads(r[7]) if r[7] else [],
            "report": r[8], "error": r[9]}


@router.post("/tasks/{task_id}/cancel")
async def autopilot_cancel(task_id: str, _: bool = Depends(require_train_admin)):
    r = _db().execute("SELECT status FROM autopilot_tasks WHERE id = ?", (task_id,)).fetchone()
    if r is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if r[0] != STATUS_RUNNING:
        raise HTTPException(status_code=409, detail=f"Task already {r[0]}")
    _cancelled.add(task_id)
    return {"ok": True, "id": task_id, "status": "CANCELLING",
            "detail": "Stops before the next step."}


@router.get("/tools")
async def autopilot_tools():
    """Every tool Autopilot can use. All read-only by design."""
    return {"tools": [{"name": k, "description": v, "side_effects": "none"}
                      for k, v in TOOLS.items()],
            "max_steps": MAX_STEPS, "deadline_seconds": DEADLINE_SECONDS}
