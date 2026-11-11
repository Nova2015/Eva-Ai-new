# EVA AI — Bug Fix Changelog

Strategy: **Stability first.** Phase 1 (backend startup / API crashes) only. No new features added.

---

## Session 2026-07-08 — Phase 1: API-crash bugs in `src/app.py`

### Method
Runtime deps and the Windows-specific stack can't be reproduced in the analysis
sandbox, so bugs were found by static analysis instead of by booting:

- `python -m py_compile` on every `.py` in `src/` and `backend/` → **no syntax errors**.
- `pyflakes` across `src/` + `backend/` + `eva-ml-service/` → surfaced **6 undefined-name
  references, all in `src/app.py`**. Every other module is clean on this check.

An undefined name at module (import) scope crashes startup; inside a function it
crashes only when that endpoint is called. **None of these were at import scope**, so
the backend was already importing — these were latent per-endpoint `NameError` crashes
(Phase 1 "API crashes" category, not "backend won't start").

### Fixes

**1. `POST /chat/stream` — endpoint crashed on every call.** (`chat_stream`, ~line 8050)
Root cause: the handler referenced names that were never defined and read fields that
don't exist on its `ChatReq` model (`question`, `user_id`, `stream` only).

- `GROQ_KEY` (undefined) → crashed on `if not GROQ_KEY:` before streaming began.
  Fixed: `groq_key = os.getenv("GROQ_API_KEY", "")` — the pattern used everywhere else
  in the file.
- `SYSTEM` (undefined) → replaced with `BASE_SYSTEM_PROMPT` (the module's real prompt).
- `req.history`, `req.model`, `req.max_tokens`, `req.temperature` (not on `ChatReq`) →
  read via `getattr(req, ..., None) or <default>`.
- `memory` (undefined, and wrongly used as a `dict`) → replaced with the canonical
  `get_memory().add_message(user_id, role, content)` used by the working `/chat`
  endpoint, wrapped in try/except so a memory failure can't break the SSE stream.

Effect: the endpoint went from *always* 500/erroring to functional.

**2. `GET /analytics/dashboard` and `GET /analytics/health` — both crashed on call.**
(~lines 2381 / 2389)
Root cause: `rag_ready = _rag is not None and _rag.vectorstore is not None`, but there is
**no `_rag` global** — RAG is served per-user via `multi_user_rag` and the external ML
service. Left over from an earlier single-RAG design.
Fixed: added `_global_rag_ready()` helper that safely reports readiness from
`MULTI_USER_RAG_AVAILABLE`/`_get_user_rag`, and used it in both endpoints.

### Reviewed — NOT bugs (guarded false positives)
- `firewall` (~line 3516): inside `if 'firewall' in globals():`, wrapped in try/except. Dead/defensive; never executes. Left as-is.
- `rag_instance` (~line 8459): inside `... if "rag_instance" in dir() else None`. Guarded. Left as-is.

### Verification status — HONEST
- **Verified here:** all three fixes read back correct on the real file; the full file
  is syntactically complete through EOF (line 8700), incl. `serve_react` + `code_run_test`.
- **NOT verified here:** a full `py_compile` / import / boot. The sandbox Linux mount
  could not serve the tail of this 8,700-line file (it kept returning a truncated
  snapshot ending ~line 8667), and the Windows runtime deps can't be reproduced here.
  **You must run the checks below on your machine.**

### Verify on Windows (PowerShell, from repo root)
```powershell
# 1. Syntax — must print nothing / exit 0
.\.venv\Scripts\python -m py_compile src\app.py

# 2. Undefined names — should report ONLY 'firewall' and 'rag_instance' (the guarded ones)
.\.venv\Scripts\python -m pyflakes src\app.py | Select-String "undefined name"

# 3. Import the app (catches import-time errors)
.\.venv\Scripts\python -c "import src.app; print('import OK')"

# 4. Boot + health check
.\.venv\Scripts\python -m uvicorn src.app:app --host 127.0.0.1 --port 3000
#    then in another terminal:  curl http://127.0.0.1:3000/health
```

---

## Session 2026-07-12 — Code Workspace & Learning Hub silently disabled

### Symptom
Status board showed **Code Workspace ⚠ Disabled** and **Learning Hub ⚠ Disabled**
while backend import/startup passed. These were NOT intentional feature flags — the
routers were throwing on import and the `except` in `app.py` swallowed the error, so
every endpoint under `/code/*` and the learning routes returned 404.

### Root cause
Broken intra-package imports. The modules used bare/absolute imports of their siblings
(e.g. `from code_analyzer import ...`, `from course_manager import ...`), but `app.py`
loads them as `backend.code_workspace.*` / `backend.learning.*`. Those package folders
are not on `sys.path` (app.py only adds repo-root and `src/`), so Python raised
`ModuleNotFoundError` and the whole router was dropped.

### Fix — bare imports → relative imports (6 files)
- `backend/code_workspace/code_routes.py` — `.code_analyzer`, `.code_generator`, `.patch_builder`, `.code_runner`
- `backend/code_workspace/code_generator.py` — `.code_analyzer`
- `backend/learning/learning_routes.py` — `.course_manager`, `.interview_prep`, `.progress_tracker`, `.quiz_manager`
- `backend/learning/interview_prep.py` — `.course_manager`
- `backend/learning/quiz_manager.py` — `.course_manager`

Relative imports resolve within the package regardless of `sys.path`, and are safe here
because both routers are only ever imported via their dotted package path.

### Verified here
`backend.learning.interview_prep` and `backend.learning.learning_routes` import cleanly
in-sandbox after the fix (learning_routes' only remaining error is `fastapi` not being
installed in the analysis sandbox — expected, not a code issue). All 6 files confirmed
to carry the relative imports on disk.

### The other 3 "Disabled" rows are BY DESIGN (not bugs)
- **TensorFlow features** — `import tensorflow` not installed → `TF_AVAILABLE=False`.
- **LoRA training** — `import unsloth` not installed → `LORA_AVAILABLE=False`.
  (LoRA *inference* is unaffected — it runs via the HuggingFace Inference API.)
- **Voice output** — `import gtts` not installed → `TTS_AVAILABLE=False`.
These are clean `try/except ImportError` guards. To enable, install the dependency;
there is nothing to fix.

### Verify on Windows
```powershell
.\.venv\Scripts\python -c "from backend.code_workspace.code_routes import router; print('code OK')"
.\.venv\Scripts\python -c "from backend.learning.learning_routes import router; print('learning OK')"
# Then boot and confirm the status board flips both to enabled.
```

---

## Known issues flagged this session (NOT yet fixed)

- **Stuck `.git/index.lock`** (dated today) blocks git operations — matches the symptom
  in `HEAD_lock_and_logo_error_powershell.txt`. Remove with:
  `Remove-Item .git\index.lock` (only when no git process is running).
- **Five `patch*.py` files in `src/`** (`patch.py`, `patch2.py`, `patch_agent.py`,
  `patch_agent_token.py`, `patch_render.py`) — accumulated monkey-patches. Next agreed
  step after startup is stable: investigate and consolidate into the real code.
- **Repeated identical commits** (`REAL FIX …` ×3, `smart run` ×8) indicate fixes were
  re-applied without a reliable verify loop. Establishing the checks above is the fix.
