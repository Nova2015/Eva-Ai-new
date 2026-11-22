# EVA AI — Platform Guide (Updates 48–58)

How the continuous-learning platform is put together, what every endpoint does,
how to test it, how to deploy it, and how to roll it back.

---

## 1. Architecture

Three deployables, three separate repos/remotes:

| Component | Host | Repo | Serves |
|---|---|---|---|
| **Frontend** | Vercel | `frontend/` in the backend repo | User chat UI only |
| **Backend** | Render (`eva-ai-1-9wfc.onrender.com`) | GitHub `Nova2015/EVA-ai`, branch `main` | Chat API, security, admin Training Center |
| **ML service** | HF Space (`keshav1212-eva-ml-service.hf.space`) | `eva-ml-service/` — **separate git remote** (HF) | RAG, embeddings, datasets, registry, training jobs, knowledge ingestion |
| **Data** | Supabase Postgres + pgvector | — | Chunks, datasets, registry, jobs (durable) |

```
User ─► Vercel (chat only)
          │
          ▼
     Render backend ──► inbound firewall ──► routing ──► HF ML service ──► Supabase/pgvector
          │                                                   │
          │◄──────────── outbound firewall ◄──────────────────┘
          │
          └─► /admin/training  (Training Center — admin only)
```

**Request path for one chat message**

1. `_security_gate()` — inbound firewall (prompt injection, PII, rate limit, threat intel).
2. Conversational gate on the ML service — greetings/identity skip retrieval entirely.
3. Hybrid retrieval — pgvector cosine + Postgres full-text, merged, deduped, reranked.
4. Model router — intent → provider/model, overlaid by the **active registry config version**.
5. `_finalize_response()` — outbound firewall under a hard 2s timeout, fail-open.
6. `_capture_learning()` — optional training-candidate capture (opt-in, PII-scrubbed).

### Surface separation (Update 58)

The same React bundle serves users and admins, switched by `REACT_APP_ADMIN_MODE`
/ port. User sidebar is **Chat · History · Profile · Settings**; every
AI-engineering page is `adminOnly` — routes still exist (admin workspace and
deep links keep working), they are simply never shown to end users. Mode
selection (General AI / RAG / Vision / OCR / Code / CAD) is automatic on the
backend; there is no user-facing switch.

---

## 2. Folder structure

```
src/                            Render backend
  app.py                        Chat API, firewall gates, routers (8000+ lines — do not refactor)
  security_config.py            SECURITY_CONFIG flags (ENFORCE_FIREWALL, timeouts)
  security/ai_firewall.py       inspect_request / inspect_response (one scanner)
  learning_loop.py              U51 candidates → review → versioned datasets
  admin_training.py             U53 admin APIs (eval, prompt tests, synthetic, feedback)
  admin_training_ui.html        U53/58 Training Center dashboard (self-contained)
eva-ml-service/                 HF Space (separate remote)
  hybrid_rag_v2.py              retrieval, context budget, conversational gate
  model_router.py               intent → provider, registry overlay
  dataset_center.py             U52 datasets (upload/HF/URL/JSONL, versions, merge, export)
  model_registry.py             U54 routing config versions, deploy/rollback
  training_jobs.py              U55 CPU embedder training + GPU LoRA script generation
  knowledge_expansion.py        U57 GitHub/website/arXiv/YouTube ingestion
  efficiency.py                 U56 ONNX/int8 benchmark, GGUF script generation
frontend/src/                   Vercel user UI
  components/Sidebar.js         user nav (Chat/History/Profile/Settings)
  components/SettingsModal.js   settings; engineering panels are adminOnly
  pages/Chat.js                 the entire user product (~4000 lines)
docs/AI_PLATFORM.md             this file
```

---

## 3. API reference

All admin/mutating endpoints honour `X-Train-Key` when `TRAIN_ADMIN_KEY` is set
(open when unset). Nothing below changes the pre-existing chat API.

### Backend — continuous learning (`/train`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/train/status` | candidate counts, capture outcomes, latest dataset |
| GET | `/train/candidates?status=` | review queue (`PENDING`/`APPROVED`/`REJECTED`/`NEEDS_IMPROVEMENT`) |
| POST | `/train/candidates/{id}/approve` | human approval — the only path into a dataset |
| POST | `/train/candidates/{id}/reject` | reject with note |
| POST | `/train/candidates/{id}/needs-improvement` | park for editing |
| POST | `/train/candidates/{id}/correct` | replace answer with corrected text, auto-approve |
| POST | `/train/dataset/build` | clean → dedup → split → JSONL + manifest; pushes to Dataset Center |
| GET | `/train/datasets`, `/train/datasets/{v}/preview` | local build history |

### Backend — Autopilot (`/autopilot`, Update 64)

`POST /run` (goal → background task) · `GET /tasks` · `GET /tasks/{id}`
(plan, per-step trace, report) · `POST /tasks/{id}/cancel` · `GET /tools`.

**Every tool is read-only**: `web_search`, `read_url`, `rag_query`, `think`.
Nothing writes, sends, deletes, posts, executes code, or spends money — that
is what makes unattended execution safe, and the planner's whitelist silently
drops any other tool the LLM invents. `read_url` refuses non-http(s) and
internal targets (localhost, RFC1918, and the `169.254.169.254` metadata
endpoint). Bounded by 10 steps, a 300s deadline, 25s per-tool timeouts, and
cooperative cancellation. If final synthesis fails, the task still completes
with the gathered material preserved and flagged `synthesis_unavailable`.

### Frontend — voice and vision (Updates 62–63)

`components/JarvisMode.js` — wake word ("Hey EVA"), hands-free loop, spoken
replies, barge-in. `components/CameraCapture.js` — camera capture producing a
normal image `File`. Both feed the **existing** chat/vision pipeline rather
than a parallel one; neither adds a backend endpoint. Microphone and camera
are off by default, opened only on explicit action, with all tracks stopped on
close/unmount/tab-hide.

### Backend — Training Center (`/admin-api/training`)

`GET /overview` · `GET /providers` · `POST /prompt-test` · `GET /prompt-tests` ·
`POST /evaluate` · `GET /evaluations[/{id}]` · `POST /synthetic` ·
`GET /feedback` · `POST /feedback-to-candidate` · `GET /registry`
Dashboard UI: **`GET /admin/training`**.

### ML service

| Area | Endpoints |
|---|---|
| RAG | `POST /rag/chat`, `/rag/query`, `/rag/upload`, `/rag/documents`, `/rag/stats` |
| Datasets (U52/53) | `GET/POST /datasets`, `/datasets/upload`, `/import/huggingface`, `/import/url`, `/import/jsonl`, `/{id}`, `/{id}/versions/{v}/{stats,preview,export}`, `POST /merge`, `DELETE /{id}` |
| Registry (U54) | `GET /registry`, `POST /registry/versions`, `/versions/{v}/deploy`, `POST /registry/rollback`, `POST /registry/metrics` |
| Training jobs (U55) | `POST/GET /train-jobs`, `/{id}`, `/{id}/script`, `/{id}/complete`, `/{id}/fail` |
| Efficiency (U56) | `POST /efficiency/onnx-benchmark`, `GET /efficiency/runs`, `/jobs/{id}`, `/gguf-script` |
| Knowledge (U57) | `POST /knowledge/{github,website,arxiv,youtube}`, `GET /knowledge/sources`, `/jobs/{id}` |

---

## 4. The learning loop

```
chat (learn:true) → PENDING candidate → human review → APPROVED
  → /train/dataset/build → Dataset Center version (durable, chat-SFT JSONL)
    → training job (cpu-embedder here | gpu-lora-sft script on Colab)
      → metrics + artifacts on the job record
        → evaluation → metrics attached to the active registry config
          → registry deploy / rollback
```

**Approval is structural.** Capture writes `PENDING`; only a human transition to
`APPROVED` makes a row eligible for a build. Synthetic generation and
feedback conversion both enter the same queue. Nothing trains automatically.

**Capture policy** — opt-in per request (`learn`) or `LEARNING_CAPTURE_DEFAULT`;
PII-bearing exchanges are skipped, never stored; security-flagged, failed and
image chats are skipped; content fingerprints deduplicate. Logs carry a fixed
outcome enum and a hashed user ref — never content.

---

## 5. Testing plan

**Before deploy (local)**
```bash
python -m py_compile src/app.py src/learning_loop.py src/admin_training.py
cd eva-ml-service && python -m py_compile *.py
NODE_ENV=production node -e "require('@babel/core').parseSync(...)"   # JSX parse
```
Generated artifacts (LoRA/GGUF scripts) must themselves compile — the
generators are covered by `py_compile` round-trip tests.

**After deploy (live only — never claim success from local runs)**
1. Confirm the deployed SHA: `GET /api/health/full` → `backend_commit`; HF API
   `runtime.stage == RUNNING` **and** top-level `sha`.
2. Smoke the chat path: greeting (expect `sources: []`, `mode_used:
   conversational`) and an on-corpus question (expect real sources + `[Source N]`).
3. Run the benchmark: `POST /admin-api/training/evaluate`, poll to `DONE`.
   Read `answer_preview` on failures — **429s mean provider quota, not a
   regression** (free-tier Gemini daily cap / Groq per-minute limit).

**Regression baseline:** accuracy 1.0, hallucination 0.0, citation accuracy
1.0, ~6.9s avg latency (run `64bc892b9d83`).

---

## 6. Deployment

| Target | Command | Time | Verify |
|---|---|---|---|
| Backend | `git push origin HEAD:main` | 1–5 min | `backend_commit` in `/api/health/full` |
| ML service | `cd eva-ml-service && git push origin` | **~35 min** (cpu-basic) | HF API `stage=RUNNING` + `sha` |
| Frontend | Vercel auto-deploys from `main`; the Render image builds its own copy | ~2 min | `frontend_version` |

The HF Space keeps serving the old build during a rebuild and reports
`RUNNING_BUILDING` — check **stage *and* sha**, never stage alone.

**Required environment**

| Variable | Where | Purpose |
|---|---|---|
| `TRAIN_ADMIN_KEY` | both | **Currently unset — the Training Center is open.** Set to lock it. |
| `DATABASE_URL` | ML service | Supabase (vector store, datasets, registry, jobs) |
| `GROQ_API_KEY` / `GEMINI_API_KEY` | both | Chat providers |
| `LEARNING_CAPTURE_DEFAULT` | backend | Default capture opt-in (ships `false`) |
| `RAG_CONTEXT_BUDGET` | ML service | Context chars (default 6000) |
| `HF_TOKEN` | ML service | Optional — persist trained models to the Hub |

---

## 7. Rollback

| Situation | Action |
|---|---|
| Bad routing config | `POST /registry/rollback` — re-activates the previous version, live in ≤15s |
| Bad backend deploy | `git revert <sha> && git push origin HEAD:main` |
| Bad ML deploy | `git revert <sha> && git push origin` (~35 min rebuild) |
| Firewall over-blocking | `ENFORCE_FIREWALL=False` — returns to shadow mode |
| Bad dataset version | Versions are immutable; build a new one. Sources unaffected by merges. |
| Bad ingested source | Re-ingest replaces chunks, or `DELETE /datasets/{id}` |

The registry is the only rollback that takes effect without a redeploy —
prefer routing changes over code changes when possible.

---

## 8. Known limitations

- **No GPU.** Render free + HF cpu-basic. LoRA/QLoRA training runs off-platform
  via generated scripts; there are deliberately no start/pause buttons.
- **ONNX is not adopted.** Measured slower than PyTorch here (0.29×/0.47×), and
  int8 drifts to 0.965 cosine vs the baseline that built the index — below the
  0.999 adoption gate. See `/efficiency/runs`.
- **Unreviewed candidates are ephemeral.** They live in instance-local SQLite on
  Render and are lost on redeploy; built datasets are durable in Supabase.
  Moving the queue to Supabase needs `psycopg2` on the backend.
- **YouTube transcripts fail from the Space** — YouTube blocks datacenter IPs
  (`RequestBlocked`). The code path is correct; it works from other egress.
- **Free-tier provider quotas** exhaust under heavy evaluation days.
- **Audio transcription** is intentionally absent (Whisper is too heavy for
  cpu-basic).

---

## 9. Roadmap

**Near term** — set `TRAIN_ADMIN_KEY`; move the candidate queue to Supabase;
re-run the benchmark after quota reset; Share Chat in the user UI.

**Later** — vision evaluation harness (image golden set), scheduled ingestion
refresh for crawled sources, per-workspace registry configs, DPO/preference
tuning on the RLHF pairs the feedback store already collects.

---

## 10. Git hooks

`.githooks/pre-commit` blocks commits containing merge-conflict markers.

**Enable it once per clone** (hooks are not installed by git automatically):

```bash
git config core.hooksPath .githooks
```

Why it exists: a bad merge resolution once left `<<<<<<< HEAD` in
`frontend/build/index.html` and `asset-manifest.json`. At the time those were
committed build artifacts that nothing validated — CRA only checks `src/`, and
the image copied whatever bytes were in git. The markers reached production and
rendered as literal text on the page, because `index.html` places them outside
the React root. That root cause is now fixed (§11); the hook remains as a cheap
guard for source files.

The hook matches the angle-bracket markers only (`<<<<<<<`, `>>>>>>>`). A bare
`=======` is deliberately not checked, because this repo has Python docstring
underlines that would false-positive; every real conflict carries the angle
markers too, so nothing is missed.

Bypass for a genuine edge case: `git commit --no-verify`.

---

## 11. The frontend bundle is built, not committed

`frontend/build/` **is no longer in git**. The Dockerfile builds it from source
in a `node:20-slim` stage and copies the result into the Python image, so the
bundle is a pure function of `frontend/src/**`.

**What this changes for day-to-day work:** edit `frontend/src/**`, commit, push.
That is the whole workflow. There is no rebuild-and-commit step any more, and it
is no longer possible for the deployed bundle to disagree with the source.

Two guarantees worth knowing:

- **`CI=true` runs in the image**, so lint warnings fail the Docker build. A
  broken frontend now fails the *deploy* rather than shipping — and Render only
  promotes a successful build, so a failure leaves the previous version serving.
- **`npm ci`, not `npm install`**, so `package-lock.json` is authoritative. This
  means a lock that has drifted from `package.json` is now a hard build failure
  instead of being silently papered over. Keep the lock in sync:

```bash
cd frontend && npm install
```

`.dockerignore` excludes `**/node_modules` — the developer machine is Windows,
and copying Windows-native binaries into the Linux builder would shadow the
image's own install and fail confusingly.

Vercel is unaffected: it already built from source.
