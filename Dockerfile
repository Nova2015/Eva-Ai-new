# ── Stage 1: build the React bundle from source ───────────────
# Previously frontend/build/ was committed and copied in verbatim. That made
# the bundle a hand-maintained artifact: it drifted from src/ whenever someone
# forgot to rebuild, and nothing validated it — CRA only checks src/, and this
# image just copied whatever bytes were in git. A bad merge once put a literal
# '<<<<<<< HEAD' into index.html and it rendered as text in production.
# Building here makes the bundle a pure function of the source.
FROM node:20-slim AS frontend

WORKDIR /frontend

# Manifests first: this layer caches independently of source edits, so routine
# UI changes skip the ~14k-entry install entirely.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

# Then the source. frontend/.env is tracked and carries the REACT_APP_* values
# CRA inlines at build time (API base, Google client ID) — without it the
# bundle would point at nothing.
COPY frontend/ ./

# CI=true makes warnings fatal, the same gate used locally. It has caught a TDZ
# ReferenceError and a shadowed import that would otherwise have shipped.
RUN CI=true npm run build

# ── Stage 2: Python backend, serving the bundle built above ───
FROM python:3.11-slim

# Install only essential system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    git \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY src/ ./src/
COPY backend/ ./backend/

# The React bundle, from the builder stage — not from git.
# app.py resolves this as ROOT_DIR/frontend/build (src/app.py:1043).
COPY --from=frontend /frontend/build ./frontend/build

# Create necessary directories
RUN mkdir -p data generated uploads faiss_index models static

WORKDIR /app/src

ENV PYTHONUNBUFFERED=1
ENV PORT=7860

EXPOSE 7860

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port $PORT"]
