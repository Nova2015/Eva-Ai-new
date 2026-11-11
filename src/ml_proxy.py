"""
EVA ML Proxy (Render copy)
==========================
Render (light backend) forwards heavy ML requests to Hugging Face Spaces.

This file lives in src/ because the Render Docker image only copies src/ and
backend/ (see Dockerfile) — the eva-ml-service/ copy of ml_proxy.py is never
in the image, which made `from ml_proxy import ...` in app.py fail on every
deploy and left /ml/* permanently unregistered.

Registered in app.py as:

    from ml_proxy import router as ml_proxy_router
    app.include_router(ml_proxy_router, prefix="/ml", tags=["ML"])
"""

import os
import logging
import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()

# Same default the rest of app.py uses for the HF service (see HF_RAG_URL),
# so /ml/health reports real HF status even without the env var set.
HF_ML_URL = os.getenv("HF_ML_URL", "http://127.0.0.1:7860").rstrip("/")


async def _proxy(path: str, body: dict) -> dict:
    if not HF_ML_URL:
        raise HTTPException(status_code=503, detail="ML service not configured. Set HF_ML_URL in environment.")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{HF_ML_URL}{path}", json=body)
            return resp.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="ML service timed out")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ML service error: {e}")


@router.post("/sentiment")
async def sentiment(request: Request):
    body = await request.json()
    return JSONResponse(await _proxy("/ml/sentiment", body))


@router.post("/classify")
async def classify(request: Request):
    body = await request.json()
    return JSONResponse(await _proxy("/ml/classify", body))


@router.post("/toxic")
async def toxic(request: Request):
    body = await request.json()
    return JSONResponse(await _proxy("/ml/toxic", body))


@router.post("/rag/query")
async def rag_query(request: Request):
    body = await request.json()
    return JSONResponse(await _proxy("/rag/query", body))


@router.get("/health")
async def ml_health():
    if not HF_ML_URL:
        return {"status": "not_configured", "hf_url": None}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{HF_ML_URL}/health")
            return {"status": "ok", "hf_url": HF_ML_URL, "hf_status": resp.json()}
    except Exception as e:
        return {"status": "unreachable", "error": str(e)}
