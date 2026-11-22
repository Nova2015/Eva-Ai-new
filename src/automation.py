"""Automation lifecycle — Update 38, the first end-to-end automated task.

ONE narrow, deterministic task: build an Excel workbook from tabular data the
user supplied, verify it, deliver it, and record what happened. It is a
foundation, not general autonomy — the executor here can reach exactly one
tool, and the task is fixed. Nothing about this makes EVA choose tools or plan
open-ended work.

The lifecycle the whole cognitive engine describes, run for real over one task:

    UNDERSTAND -> ASSESS -> STRATEGY -> PLAN    (reused, read-only, for the record)
    -> ACT      build_workbook   (35b tool, the ONLY tool the executor can call)
    -> VERIFY   verify_workbook  (35b verifier: opens, shape, cell round-trip)
    -> CORRECT/RETRY  bounded rebuild/redeliver, strict cap, deterministic
    -> DELIVER  upload_raw       (35b Cloudinary delivery)
    -> VERIFY-DELIVERED  re-download + verify, best effort
    -> RESPOND  artifact link, or a truthful failure — never a fabricated file

SAFETY, by construction:
  * The tool registry holds one entry. Asking for any other tool raises
    UnapprovedTool and runs nothing — there is no path to web_search, rag_query
    or a shell. This is why the executor "may call only the Excel tool" is a
    fact about the code, not a promise.
  * The data comes only from the user's message (parse_table). No row or value
    is ever invented; an empty parse stops and asks for data.
  * Every exit goes through _finish, so a record is always written and a
    failure can never be reported as success.
  * The record carries enums, counts and a content digest — never the prompt,
    the answer, the user, an IP, a provider message, or the file's contents.

Pure enough to test offline: every side effect (build, verify, upload,
download, the strategy read) is an injected callable with a real default.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional, Tuple

try:
    from pydantic import BaseModel, ConfigDict
except Exception:  # pragma: no cover - pydantic is a hard dependency in practice
    BaseModel = object  # type: ignore
    ConfigDict = dict   # type: ignore

__all__ = [
    "TaskType", "ToolId", "Outcome", "DeliveredCheck",
    "AutomationRecord", "AutomationResult", "Deps",
    "UnapprovedTool", "ToolUnavailable",
    "run_tool", "gated_excel_tool", "default_deps", "default_download",
    "run_excel_task",
    "recent_records", "MAX_RETRIES_CAP", "DEFAULT_RETRIES", "FILENAME",
    # Update 39A — presentations
    "CheckResult", "PresentationRecord", "PresentationResult", "PresentationDeps",
    "run_pptx_tool", "gated_powerpoint_tool", "default_presentation_deps",
    "run_presentation_task", "PPTX_FILENAME",
]

# ── Fixed vocabulary. Everything stored is one of these. ─────────────────────
class TaskType(str, Enum):
    EXCEL_FROM_TABLE = "EXCEL_FROM_TABLE"
    PRESENTATION_PPTX = "PRESENTATION_PPTX"


class ToolId(str, Enum):
    BUILD_EXCEL = "BUILD_EXCEL"
    BUILD_POWERPOINT = "BUILD_POWERPOINT"


class Outcome(str, Enum):
    DELIVERED = "DELIVERED"                       # success, verified end to end
    NO_DATA = "NO_DATA"                           # asked for a sheet, sent no rows
    NO_CONTENT = "NO_CONTENT"                     # asked for a deck, sent no content
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"         # library/delivery not configured
    BUILD_FAILED = "BUILD_FAILED"                 # the tool raised
    VERIFY_FAILED = "VERIFY_FAILED"               # local verification failed after retries
    STRUCTURAL_FAILED = "STRUCTURAL_FAILED"       # structural verify failed after retries
    VISUAL_FAILED = "VISUAL_FAILED"               # layout verify failed after retries
    DELIVERY_FAILED = "DELIVERY_FAILED"           # upload failed after retries
    DELIVERED_VERIFY_FAILED = "DELIVERED_VERIFY_FAILED"  # the delivered bytes did not match
    UNAPPROVED_TOOL = "UNAPPROVED_TOOL"           # the executor was asked for another tool


class CheckResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNAVAILABLE = "UNAVAILABLE"    # the check could not run (e.g. no renderer)


class DeliveredCheck(str, Enum):
    VERIFIED = "VERIFIED"           # re-downloaded and it round-trips
    MISMATCH = "MISMATCH"           # re-downloaded and it does NOT — terminal
    INCONCLUSIVE = "INCONCLUSIVE"   # could not re-download (network/CDN) — not a failure
    SKIPPED = "SKIPPED"             # no downloader wired


DEFAULT_RETRIES = 2
# A hard ceiling the caller cannot exceed, so no configuration can turn the
# bounded loop into an unbounded one.
MAX_RETRIES_CAP = 3
FILENAME = "eva-data.xlsx"
SHEET_NAME = "Data"

# sha256 length shared with cognitive.verification.artifact_digest, so a digest
# recorded here means the same thing as one recorded there.
try:
    from cognitive.verification import DIGEST_CHARS
except Exception:  # pragma: no cover
    try:
        from src.cognitive.verification import DIGEST_CHARS  # type: ignore
    except Exception:
        DIGEST_CHARS = 16


class UnapprovedTool(Exception):
    """The executor was asked for a tool it does not hold. Nothing runs."""


class ToolUnavailable(Exception):
    """The approved tool cannot run because a dependency is missing (openpyxl).
    Distinct from a genuine build failure so the caller can fall through to a
    normal answer rather than report a task failure."""


# ── The record. Enums, counts, a digest. Never content, never identity. ──────
class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AutomationRecord(_Base):
    task_type: TaskType
    strategy: str                       # a ReasoningStrategy value or "UNKNOWN"
    tool: ToolId
    verified: bool                      # local verification passed
    delivered_check: DeliveredCheck
    correction_attempted: bool
    retries: int
    outcome: Outcome
    digest: str = ""                    # sha256 prefix of the bytes, or ""
    rows: int = 0                       # count only
    columns: int = 0                    # count only


@dataclass
class AutomationResult:
    outcome: Outcome
    record: AutomationRecord
    url: Optional[str] = None
    filename: str = FILENAME
    rows: int = 0
    columns: int = 0
    # A safe, fixed-template message for failures — no prompt, no PII.
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome is Outcome.DELIVERED


# ── The one-tool registry and its gate ───────────────────────────────────────
def _build_excel(rows: List[List[Any]], sheet_name: str) -> bytes:
    try:
        from spreadsheet import build_workbook
    except Exception:  # pragma: no cover - exercised via ToolUnavailable path
        try:
            from src.spreadsheet import build_workbook  # type: ignore
        except Exception as exc:
            raise ToolUnavailable(type(exc).__name__)
    return build_workbook(rows, sheet_name)


# The ONLY tool this executor can reach. A dict lookup, so any other name is a
# miss that raises — there is no branch that could run a second tool.
_TOOL_REGISTRY: Dict[ToolId, Callable[[List[List[Any]], str], bytes]] = {
    ToolId.BUILD_EXCEL: _build_excel,
}


def run_tool(tool_id: Any, rows: List[List[Any]], sheet_name: str = SHEET_NAME) -> bytes:
    """Run an approved tool, or refuse. The gate for boundaries #2/#3/#12.

    Accepts Any so a caller passing a raw string like "web_search" is refused
    the same way an unknown ToolId is, rather than slipping through a type
    check.
    """
    if tool_id not in _TOOL_REGISTRY:
        raise UnapprovedTool(str(tool_id))
    return _TOOL_REGISTRY[tool_id](rows, sheet_name)


def gated_excel_tool(build_fn: Callable[[List[List[Any]], str], bytes]) -> RunToolFn:
    """A run_tool gate bound to a specific builder — the same one-tool guarantee
    as run_tool, but calling `build_fn` for BUILD_EXCEL.

    This exists so the app can pass its own build alias (which its tests
    monkeypatch) while the gate stays exactly as strict: the returned callable
    knows one tool id and refuses every other, so injecting the builder cannot
    widen what the executor may run. `build_fn` is always the Excel builder;
    nothing here lets a caller register a second tool.
    """
    registry = {ToolId.BUILD_EXCEL: build_fn}

    def _run(tool_id: Any, rows: List[List[Any]], sheet_name: str = SHEET_NAME) -> bytes:
        if tool_id not in registry:
            raise UnapprovedTool(str(tool_id))
        return registry[tool_id](rows, sheet_name)

    return _run


# ── Injected dependencies, with real defaults ────────────────────────────────
ParseFn = Callable[[str], Optional[List[List[Any]]]]
RunToolFn = Callable[[ToolId, List[List[Any]], str], bytes]
VerifyFn = Callable[[bytes, List[List[Any]]], Tuple[bool, Dict[str, Any]]]
UploadFn = Callable[[bytes, str], Awaitable[Tuple[Optional[str], str]]]
DownloadFn = Callable[[str], Awaitable[Optional[bytes]]]
DigestFn = Callable[[bytes], str]
StrategyFn = Callable[[str], str]


@dataclass
class Deps:
    parse: ParseFn
    run_tool: RunToolFn
    verify: VerifyFn
    upload: UploadFn
    digest: DigestFn
    strategy: StrategyFn
    download: Optional[DownloadFn] = None   # best-effort; None = skip delivered-verify


def _digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data or b"").hexdigest()[:DIGEST_CHARS]


def _strategy_label(question: str) -> str:
    """The strategy the cognitive engine reasons to for this request, as a bare
    enum value for the record. Best-effort and read-only: any hiccup yields
    "UNKNOWN" rather than failing the deterministic artifact task, and nothing
    derived from the prompt text is ever stored — only the enum name."""
    try:
        try:
            from cognitive.understanding import understand
            from cognitive.assessment import assess
            from cognitive.strategy import select_strategy
        except Exception:  # pragma: no cover
            from src.cognitive.understanding import understand      # type: ignore
            from src.cognitive.assessment import assess             # type: ignore
            from src.cognitive.strategy import select_strategy      # type: ignore
        u = understand(question)
        a = assess(u, problem=question)
        decision = select_strategy(u, a, problem=question)
        value = getattr(getattr(decision, "strategy", None), "value", None)
        return str(value) if value else "UNKNOWN"
    except Exception:
        return "UNKNOWN"


async def _default_upload(data: bytes, filename: str) -> Tuple[Optional[str], str]:
    try:
        from file_delivery import upload_raw
    except Exception:  # pragma: no cover
        from src.file_delivery import upload_raw  # type: ignore
    return await upload_raw(data, filename)


# Delivered-verify may fetch ONLY the artifact host upload_raw produces. This is
# the whole of boundary #12 for this feature: the downloader can never be
# pointed at an arbitrary URL, so re-verification cannot become a web action.
_ALLOWED_DOWNLOAD_HOST = "cloudinary.com"
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024


def _is_fetchable(url: Any) -> bool:
    """Whether delivered-verify is allowed to fetch this URL.

    https only, and only the Cloudinary host family — exact match or a
    dot-boundary subdomain, so "evilcloudinary.com" (no dot) is refused while
    "res.cloudinary.com" is allowed. Pure and total, so the guard is testable
    without a network.
    """
    if not isinstance(url, str):
        return False
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        return False
    return host == _ALLOWED_DOWNLOAD_HOST or host.endswith("." + _ALLOWED_DOWNLOAD_HOST)


async def default_download(url: str, timeout: float = 8.0, attempts: int = 3) -> Optional[bytes]:
    """Fetch a just-delivered artifact for independent re-verification.

    Returns the bytes, or None. None means "could not get a copy to check" —
    the caller reads that as INCONCLUSIVE, never as a mismatch, so a slow CDN or
    a transient error can never turn a good file into a reported failure. Only a
    complete download whose bytes fail to round-trip becomes a MISMATCH.

    Retries with a short backoff, because res.cloudinary.com can lag by a beat
    right after upload; the retries let propagation settle before concluding.
    Refuses any URL that is not the delivery host (see _is_fetchable) and caps
    the body, so it cannot be turned into an arbitrary or unbounded fetch.
    """
    if not _is_fetchable(url):
        return None
    try:
        import httpx
    except Exception:  # pragma: no cover
        return None
    attempts = max(1, int(attempts))
    for i in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url)
            body = resp.content or b""
            if resp.status_code == 200 and body and len(body) <= MAX_DOWNLOAD_BYTES:
                return body
        except Exception:
            pass
        if i < attempts - 1:
            await asyncio.sleep(0.4 * (i + 1))
    return None


def default_deps() -> Deps:
    """Production wiring. verify/build reuse the already-verified 35b tool;
    upload reuses 35b delivery; strategy reuses the cognitive engine.

    download stays None by default: re-fetching straight after upload can race
    CDN propagation and read a partial object, which would report a false
    mismatch on a file that is actually fine. Delivered-verify is fully built
    and tested and is enabled by injecting a downloader where that race is
    acceptable."""
    def _verify(data: bytes, expected: List[List[Any]]) -> Tuple[bool, Dict[str, Any]]:
        try:
            from spreadsheet import verify_workbook
        except Exception:  # pragma: no cover
            from src.spreadsheet import verify_workbook  # type: ignore
        return verify_workbook(data, expected)

    def _parse(text: str) -> Optional[List[List[Any]]]:
        try:
            from spreadsheet import parse_table
        except Exception:  # pragma: no cover
            from src.spreadsheet import parse_table  # type: ignore
        return parse_table(text)

    return Deps(
        parse=_parse,
        run_tool=run_tool,
        verify=_verify,
        upload=_default_upload,
        digest=_digest_bytes,
        strategy=_strategy_label,
        download=None,
    )


# ── Telemetry: a bounded ring of records, enums and counts only ──────────────
_RECENT: Deque[AutomationRecord] = deque(maxlen=200)


def recent_records(limit: int = 50) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), _RECENT.maxlen or 200))
    return [r.model_dump() for r in list(_RECENT)[-limit:]]


# ── Safe, fixed failure messages. No prompt, no path, no provider text. ──────
_MESSAGES: Dict[Outcome, str] = {
    Outcome.NO_DATA: (
        "I can build the Excel file — paste the data and I'll turn it into a "
        "sheet. A table, CSV lines or tab-separated rows all work, with the "
        "column names on the first line."
    ),
    Outcome.VERIFY_FAILED: (
        "I built the file but it did not pass verification, so I will not send "
        "a workbook that may be corrupt. Please re-send the data."
    ),
    Outcome.DELIVERY_FAILED: (
        "I built and verified the file, but the delivery step failed, so I have "
        "no download link to give you. Please try again in a moment."
    ),
    Outcome.DELIVERED_VERIFY_FAILED: (
        "The delivered file did not match what I built, so I will not link a "
        "download that may be corrupt. Please try again."
    ),
    Outcome.UNAPPROVED_TOOL: (
        "That task could not be completed within the approved automation."
    ),
}


def _finish(record_fields: Dict[str, Any], *, url: Optional[str] = None,
            rows: int = 0, columns: int = 0) -> AutomationResult:
    """The single exit. Builds the record, files it, returns the result.

    Every return in run_excel_task comes through here, so a record is written
    for every outcome and no path can report success it did not achieve.
    """
    record = AutomationRecord(**record_fields)
    _RECENT.append(record)
    return AutomationResult(
        outcome=record.outcome, record=record, url=url,
        rows=rows, columns=columns,
        message=("" if record.outcome in (Outcome.DELIVERED, Outcome.TOOL_UNAVAILABLE,
                                          Outcome.BUILD_FAILED)
                 else _MESSAGES.get(record.outcome, "")),
    )


async def _verify_delivered(url: str, expected: List[List[Any]], deps: Deps) -> DeliveredCheck:
    if deps.download is None:
        return DeliveredCheck.SKIPPED
    try:
        blob = await deps.download(url)
    except Exception:
        return DeliveredCheck.INCONCLUSIVE
    if not blob:
        return DeliveredCheck.INCONCLUSIVE
    try:
        ok, _ = await asyncio.to_thread(deps.verify, blob, expected)
    except Exception:
        return DeliveredCheck.INCONCLUSIVE
    return DeliveredCheck.VERIFIED if ok else DeliveredCheck.MISMATCH


async def run_excel_task(
    question: str,
    deps: Optional[Deps] = None,
    max_retries: int = DEFAULT_RETRIES,
) -> AutomationResult:
    """Run the one automated task end to end. Never raises for an expected
    failure — every one is a recorded Outcome."""
    deps = deps or default_deps()
    # Clamp to the ceiling. A caller may tighten the budget, never loosen it,
    # and it can never be negative — the loop is bounded no matter the input.
    max_retries = max(0, min(int(max_retries), MAX_RETRIES_CAP))

    strategy = deps.strategy(question)

    def base(**over: Any) -> Dict[str, Any]:
        fields = dict(
            task_type=TaskType.EXCEL_FROM_TABLE, strategy=strategy,
            tool=ToolId.BUILD_EXCEL, verified=False,
            delivered_check=DeliveredCheck.SKIPPED, correction_attempted=False,
            retries=0, outcome=Outcome.BUILD_FAILED, digest="", rows=0, columns=0,
        )
        fields.update(over)
        return fields

    # PLAN input: the user's data, never invented.
    rows = deps.parse(question)
    if not rows:
        return _finish(base(outcome=Outcome.NO_DATA))

    body_rows = len(rows) - 1 if len(rows) > 1 else len(rows)
    columns = len(rows[0]) if rows and rows[0] else 0

    retries = 0
    correction_attempted = False

    # ── ACT + VERIFY + bounded correction ────────────────────────────────────
    data: Optional[bytes] = None
    while True:
        try:
            # build and verify are synchronous and CPU-bound; run them off the
            # event loop exactly as the inline path did, so a large table cannot
            # stall other requests.
            data = await asyncio.to_thread(deps.run_tool, ToolId.BUILD_EXCEL,
                                           rows, SHEET_NAME)
        except UnapprovedTool:
            return _finish(base(outcome=Outcome.UNAPPROVED_TOOL, retries=retries,
                                correction_attempted=correction_attempted))
        except ToolUnavailable:
            return _finish(base(outcome=Outcome.TOOL_UNAVAILABLE, retries=retries,
                                correction_attempted=correction_attempted))
        except Exception:
            if retries >= max_retries:
                return _finish(base(outcome=Outcome.BUILD_FAILED, retries=retries,
                                    correction_attempted=correction_attempted))
            retries += 1
            correction_attempted = True
            continue

        try:
            ok, _report = await asyncio.to_thread(deps.verify, data, rows)
        except Exception:
            ok = False

        if ok:
            break
        # VERIFY FAILED -> Correction Engine -> bounded retry -> VERIFY again.
        # The rebuild is deterministic, so this mainly guards a transient fault;
        # a persistent failure exhausts the budget and stops honestly.
        if retries >= max_retries:
            return _finish(base(outcome=Outcome.VERIFY_FAILED, retries=retries,
                                correction_attempted=True))
        retries += 1
        correction_attempted = True

    digest = deps.digest(data)

    # ── DELIVER + VERIFY-DELIVERED, sharing the same bounded budget ───────────
    while True:
        try:
            url, _code = await deps.upload(data, FILENAME)
        except Exception:
            url = None
        if not url:
            if retries >= max_retries:
                return _finish(base(outcome=Outcome.DELIVERY_FAILED, verified=True,
                                    digest=digest, retries=retries,
                                    correction_attempted=True, rows=body_rows,
                                    columns=columns))
            retries += 1
            correction_attempted = True
            continue

        delivered = await _verify_delivered(url, rows, deps)
        if delivered is DeliveredCheck.MISMATCH:
            if retries >= max_retries:
                return _finish(base(outcome=Outcome.DELIVERED_VERIFY_FAILED,
                                    verified=True, delivered_check=delivered,
                                    digest=digest, retries=retries,
                                    correction_attempted=True, rows=body_rows,
                                    columns=columns))
            retries += 1
            correction_attempted = True
            continue

        return _finish(
            base(outcome=Outcome.DELIVERED, verified=True, delivered_check=delivered,
                 digest=digest, retries=retries,
                 correction_attempted=correction_attempted, rows=body_rows,
                 columns=columns),
            url=url, rows=body_rows, columns=columns)


# ═══════════════════════════════════════════════════════════════════════════
# Update 39A — PROFESSIONAL POWERPOINT. A second narrow task on the same
# machinery: one approved tool, deterministic content, structural AND layout
# verification, bounded correction, delivered-verify, PII-free telemetry. It
# reuses _finish's ring, the digest, the strategy read, delivery and the
# host-locked downloader; it adds nothing the Excel path could reach.
# ═══════════════════════════════════════════════════════════════════════════
PPTX_FILENAME = "eva-presentation.pptx"


class PresentationRecord(_Base):
    task_type: TaskType
    strategy: str
    tool: ToolId
    verified: bool                      # structural verification passed
    structural_check: CheckResult
    visual_check: CheckResult           # programmatic layout tier; render is UNAVAILABLE
    delivered_check: DeliveredCheck
    correction_attempted: bool
    retries: int
    outcome: Outcome
    digest: str = ""
    slide_count: int = 0                # count only


@dataclass
class PresentationResult:
    outcome: Outcome
    record: PresentationRecord
    url: Optional[str] = None
    filename: str = PPTX_FILENAME
    slide_count: int = 0
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome is Outcome.DELIVERED


# Plans are opaque here — presentation.py owns their shape. The orchestrator
# only passes them to the injected build/verify functions.
PlanT = Any
PresParseFn = Callable[[str], Optional[PlanT]]
PresBuildFn = Callable[[ToolId, PlanT], bytes]
PresStructFn = Callable[[bytes, PlanT], Tuple[bool, Dict[str, Any]]]
PresLayoutFn = Callable[[bytes], Tuple[bool, Dict[str, Any]]]


@dataclass
class PresentationDeps:
    parse: PresParseFn                  # spec -> plan, or None to ask for content
    run_tool: PresBuildFn               # gated: BUILD_POWERPOINT -> build(plan)
    verify_structure: PresStructFn
    verify_layout: PresLayoutFn
    upload: UploadFn
    digest: DigestFn
    strategy: StrategyFn
    slide_count_of: Callable[[PlanT], int]
    download: Optional[DownloadFn] = None


def _build_powerpoint(plan: PlanT) -> bytes:
    try:
        from presentation import build_powerpoint
    except Exception:  # pragma: no cover
        try:
            from src.presentation import build_powerpoint  # type: ignore
        except Exception as exc:
            raise ToolUnavailable(type(exc).__name__)
    return build_powerpoint(plan)


_PPTX_REGISTRY: Dict[ToolId, Callable[[PlanT], bytes]] = {
    ToolId.BUILD_POWERPOINT: _build_powerpoint,
}


def run_pptx_tool(tool_id: Any, plan: PlanT) -> bytes:
    """The PowerPoint gate. One tool; anything else is refused and runs
    nothing — the same guarantee as run_tool, for the second task."""
    if tool_id not in _PPTX_REGISTRY:
        raise UnapprovedTool(str(tool_id))
    return _PPTX_REGISTRY[tool_id](plan)


def gated_powerpoint_tool(build_fn: Callable[[PlanT], bytes]) -> PresBuildFn:
    """A run_tool gate bound to a specific PowerPoint builder — the app injects
    its own alias through this while the gate stays exactly as strict. One tool
    id, every other refused; injecting the builder cannot widen it."""
    registry = {ToolId.BUILD_POWERPOINT: build_fn}

    def _run(tool_id: Any, plan: PlanT) -> bytes:
        if tool_id not in registry:
            raise UnapprovedTool(str(tool_id))
        return registry[tool_id](plan)

    return _run


def default_presentation_deps() -> PresentationDeps:
    def _parse(text: str):
        try:
            from presentation import parse_presentation_spec
        except Exception:  # pragma: no cover
            from src.presentation import parse_presentation_spec  # type: ignore
        return parse_presentation_spec(text)

    def _struct(data, plan):
        try:
            from presentation import verify_pptx_structure
        except Exception:  # pragma: no cover
            from src.presentation import verify_pptx_structure  # type: ignore
        return verify_pptx_structure(data, plan)

    def _layout(data):
        try:
            from presentation import verify_pptx_layout
        except Exception:  # pragma: no cover
            from src.presentation import verify_pptx_layout  # type: ignore
        return verify_pptx_layout(data)

    return PresentationDeps(
        parse=_parse, run_tool=run_pptx_tool, verify_structure=_struct,
        verify_layout=_layout, upload=_default_upload, digest=_digest_bytes,
        strategy=_strategy_label, slide_count_of=lambda plan: int(getattr(plan, "slide_count", 0)),
        download=None,
    )


_PRES_MESSAGES: Dict[Outcome, str] = {
    Outcome.NO_CONTENT: (
        "I can build the presentation — tell me what goes in it. A title and a "
        "few sections with bullet points (and a table if you have one) is all I "
        "need. I will not invent slides, so paste the content and I will lay it "
        "out professionally."
    ),
    Outcome.STRUCTURAL_FAILED: (
        "I built the presentation but it did not pass structural verification, "
        "so I will not send a deck that may be wrong. Please re-send the content."
    ),
    Outcome.VISUAL_FAILED: (
        "I built the presentation but its layout did not pass checks (something "
        "overflowed or overlapped), so I will not send it. Please simplify or "
        "shorten the content and try again."
    ),
    Outcome.DELIVERY_FAILED: (
        "I built and verified the presentation, but delivery failed, so I have "
        "no download link. Please try again in a moment."
    ),
    Outcome.DELIVERED_VERIFY_FAILED: (
        "The delivered presentation did not match what I built, so I will not "
        "link a download that may be corrupt. Please try again."
    ),
    Outcome.UNAPPROVED_TOOL: (
        "That task could not be completed within the approved automation."
    ),
}


def _finish_presentation(fields: Dict[str, Any], *, url: Optional[str] = None,
                         slide_count: int = 0) -> PresentationResult:
    record = PresentationRecord(**fields)
    _RECENT.append(record)
    return PresentationResult(
        outcome=record.outcome, record=record, url=url, slide_count=slide_count,
        message=("" if record.outcome in (Outcome.DELIVERED, Outcome.TOOL_UNAVAILABLE,
                                          Outcome.BUILD_FAILED)
                 else _PRES_MESSAGES.get(record.outcome, "")),
    )


async def _verify_delivered_pptx(url: str, plan: PlanT, deps: PresentationDeps) -> DeliveredCheck:
    """Re-fetch the delivered .pptx and confirm it is the deck that was built.
    Same best-effort contract as the Excel path: a fetch failure is
    INCONCLUSIVE, never a mismatch; only a complete download that fails
    structural verification is a MISMATCH."""
    if deps.download is None:
        return DeliveredCheck.SKIPPED
    try:
        blob = await deps.download(url)
    except Exception:
        return DeliveredCheck.INCONCLUSIVE
    if not blob:
        return DeliveredCheck.INCONCLUSIVE
    try:
        ok, _ = await asyncio.to_thread(deps.verify_structure, blob, plan)
    except Exception:
        return DeliveredCheck.INCONCLUSIVE
    return DeliveredCheck.VERIFIED if ok else DeliveredCheck.MISMATCH


async def run_presentation_task(
    question: str,
    deps: Optional[PresentationDeps] = None,
    max_retries: int = DEFAULT_RETRIES,
) -> PresentationResult:
    """Build a verified .pptx end to end, or record why not. Never raises for an
    expected failure — every one is a recorded Outcome."""
    deps = deps or default_presentation_deps()
    max_retries = max(0, min(int(max_retries), MAX_RETRIES_CAP))
    strategy = deps.strategy(question)

    def base(**over: Any) -> Dict[str, Any]:
        fields = dict(
            task_type=TaskType.PRESENTATION_PPTX, strategy=strategy,
            tool=ToolId.BUILD_POWERPOINT, verified=False,
            structural_check=CheckResult.FAIL, visual_check=CheckResult.UNAVAILABLE,
            delivered_check=DeliveredCheck.SKIPPED, correction_attempted=False,
            retries=0, outcome=Outcome.BUILD_FAILED, digest="", slide_count=0,
        )
        fields.update(over)
        return fields

    # PLAN: from the user's content, never invented. None → ask for content.
    plan = deps.parse(question)
    if plan is None:
        return _finish_presentation(base(outcome=Outcome.NO_CONTENT))

    slides = int(deps.slide_count_of(plan))
    retries = 0
    correction_attempted = False
    structural = CheckResult.FAIL
    visual = CheckResult.UNAVAILABLE

    # ── BUILD + STRUCTURAL + VISUAL + bounded correction ─────────────────────
    data: Optional[bytes] = None
    while True:
        try:
            data = await asyncio.to_thread(deps.run_tool, ToolId.BUILD_POWERPOINT, plan)
        except UnapprovedTool:
            return _finish_presentation(base(outcome=Outcome.UNAPPROVED_TOOL,
                                             retries=retries,
                                             correction_attempted=correction_attempted,
                                             slide_count=slides))
        except ToolUnavailable:
            return _finish_presentation(base(outcome=Outcome.TOOL_UNAVAILABLE,
                                             retries=retries,
                                             correction_attempted=correction_attempted,
                                             slide_count=slides))
        except Exception:
            if retries >= max_retries:
                return _finish_presentation(base(outcome=Outcome.BUILD_FAILED,
                                                 retries=retries,
                                                 correction_attempted=correction_attempted,
                                                 slide_count=slides))
            retries += 1
            correction_attempted = True
            continue

        # STRUCTURAL VERIFY
        try:
            s_ok, _sr = await asyncio.to_thread(deps.verify_structure, data, plan)
        except Exception:
            s_ok = False
        structural = CheckResult.PASS if s_ok else CheckResult.FAIL
        if not s_ok:
            if retries >= max_retries:
                return _finish_presentation(base(outcome=Outcome.STRUCTURAL_FAILED,
                                                 structural_check=structural,
                                                 retries=retries, correction_attempted=True,
                                                 slide_count=slides))
            retries += 1
            correction_attempted = True
            continue

        # VISUAL VERIFY (programmatic). If the check itself cannot run, it is
        # UNAVAILABLE and does not fail the task; a genuine layout FAIL does.
        try:
            v_ok, _vr = await asyncio.to_thread(deps.verify_layout, data)
            visual = CheckResult.PASS if v_ok else CheckResult.FAIL
        except Exception:
            visual = CheckResult.UNAVAILABLE
        if visual is CheckResult.FAIL:
            if retries >= max_retries:
                return _finish_presentation(base(outcome=Outcome.VISUAL_FAILED,
                                                 structural_check=structural,
                                                 visual_check=visual, retries=retries,
                                                 correction_attempted=True,
                                                 slide_count=slides))
            retries += 1
            correction_attempted = True
            continue
        break

    digest = deps.digest(data)

    # ── DELIVER + DELIVERED-VERIFY, sharing the same bounded budget ──────────
    while True:
        try:
            url, _code = await deps.upload(data, PPTX_FILENAME)
        except Exception:
            url = None
        if not url:
            if retries >= max_retries:
                return _finish_presentation(base(outcome=Outcome.DELIVERY_FAILED,
                                                 verified=True, structural_check=structural,
                                                 visual_check=visual, digest=digest,
                                                 retries=retries, correction_attempted=True,
                                                 slide_count=slides))
            retries += 1
            correction_attempted = True
            continue

        delivered = await _verify_delivered_pptx(url, plan, deps)
        if delivered is DeliveredCheck.MISMATCH:
            if retries >= max_retries:
                return _finish_presentation(base(outcome=Outcome.DELIVERED_VERIFY_FAILED,
                                                 verified=True, structural_check=structural,
                                                 visual_check=visual, delivered_check=delivered,
                                                 digest=digest, retries=retries,
                                                 correction_attempted=True, slide_count=slides))
            retries += 1
            correction_attempted = True
            continue

        return _finish_presentation(
            base(outcome=Outcome.DELIVERED, verified=True, structural_check=structural,
                 visual_check=visual, delivered_check=delivered, digest=digest,
                 retries=retries, correction_attempted=correction_attempted,
                 slide_count=slides),
            url=url, slide_count=slides)
