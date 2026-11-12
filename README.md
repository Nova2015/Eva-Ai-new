# EVA AI

EVA AI is a React frontend backed by a FastAPI application, with a separately hosted ML/RAG service.

## Architecture

- **Frontend:** React 19 / Create React App in `frontend/`.
- **Backend:** FastAPI application in `src/app.py`.
- **ML and RAG:** External service configured with `HF_ML_URL`; its health endpoint is `/ml/health`.
- **Desktop:** Electron shell in `frontend/electron.js`.
- **Learning review:** SQLite-backed, opt-in candidate capture and human approval in `src/learning_loop.py`. Candidate capture does not train a model.

## Local development

Run commands from the repository root unless stated otherwise.

### Backend

Create and activate a Python 3.11 virtual environment, install backend requirements, then configure the required environment variables.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r src/requirements.txt
python -m uvicorn src.app:app --host 127.0.0.1 --port 8000
```

### Frontend

In a second terminal:

```powershell
cd frontend
npm ci
npm start
```

The frontend keeps loopback defaults for local browser and Electron sessions. Hosted builds use the production backend and ML service defaults below unless explicit `REACT_APP_*` build variables override them.

## Required and optional environment variables

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Required JWT signing secret. The backend refuses to start without it. |
| `HF_ML_URL` | Base URL of the external ML/RAG service. The service must expose `/ml/health`. |
| `TRAIN_ADMIN_KEY` | Enables protected learning-review and dataset-admin endpoints. If unset, those endpoints return HTTP 503 (fail closed). |
| `LEARNING_CAPTURE_DEFAULT` | Defaults to `false`; learning capture remains opt-in. |
| `LEARNING_DB_PATH` | Optional SQLite database path for learning candidates. |
| `LEARNING_DATASET_DIR` | Optional output directory for reviewed dataset versions. |
| `REACT_APP_API_BASE` | Optional frontend build-time override for the backend URL. |
| `REACT_APP_RAG_API_BASE` | Optional frontend build-time override for the ML/RAG URL. |
| `OPENAI_API_KEY`, `GROQ_API_KEY`, `GOOGLE_API_KEY` | Optional provider credentials, depending on enabled providers. |

Never commit real secrets or local `.env` files. The Docker build context excludes them.

## Docker

Build the production image from the repository root:

```bash
docker build -t eva-ai .
```

The image builds the React bundle from source using Node 22, then packages the FastAPI backend on Python 3.11. It listens on the container's `PORT` (default 7860). For a local container, map the same port and pass secrets through your local environment mechanism; do not bake them into the image.

## CI and verification

The branch CI runs:
- Cognitive-learning and chat-integration regression tests.
- Frontend Jest tests.
- A production Docker image build without publishing the image.

Run deployment checks against a deployed backend and its ML service:

```bash
python verify_deploy.py https://YOUR-BACKEND-URL --ml-url https://YOUR-ML-SERVICE-URL
```

The verifier checks backend health, the backend's live ML-health probe, the ML service's own health endpoint, and version metadata.

## Persistence note

The default SQLite learning database and generated dataset directory are local filesystem paths. Container filesystems on ephemeral hosting plans do not guarantee persistence across restarts or deployments. Configure `LEARNING_DB_PATH` and `LEARNING_DATASET_DIR` to paths on an attached persistent disk before relying on long-term retention. The current Render blueprint uses the free plan and does not provision a persistent disk automatically.

## Safety boundaries

- Learning capture is opt-in and does not automatically train models.
- Human approval is required before chat candidates can enter a dataset.
- Cognitive observations are kept separate from chat SFT exports.
- Missing PII detection fails closed for capture.
- Missing `TRAIN_ADMIN_KEY` disables learning-admin endpoints.
