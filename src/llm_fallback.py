"""
LLM Fallback System for EVA — add to app.py
============================================
How it works:
  1. RAG pipeline answers first (your FAISS index)
  2. If RAG confidence < threshold → try Groq (LLaMA)
  3. If Groq fails or key missing → try OpenAI (GPT-4o-mini)
  4. If OpenAI fails → try Gemini (gemini-3.5-flash)
  5. Always returns best available answer + which provider was used

Setup (.env):
  GROQ_API_KEY=gsk_...
  OPENAI_API_KEY=sk-...          ← get free at platform.openai.com
  GEMINI_API_KEY=AIza...         ← get free at aistudio.google.com
  RAG_CONFIDENCE_THRESHOLD=0.35  ← below this → use fallback LLM

Add to app.py:
  from llm_fallback import smart_chat
  Then replace your /chat route body with: return await smart_chat(req)
"""

import os
import time
from typing import Optional
from pydantic import BaseModel

# ── Config ────────────────────────────────────────────────
GROQ_KEY      = os.getenv("GROQ_API_KEY", "")
OPENAI_KEY    = os.getenv("OPENAI_API_KEY", "")
GEMINI_KEY    = os.getenv("GEMINI_API_KEY", "")
THRESHOLD     = float(os.getenv("RAG_CONFIDENCE_THRESHOLD", "0.35"))
GROQ_MODEL    = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
OPENAI_MODEL  = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
GEMINI_MODEL  = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"

SYSTEM_PROMPT = """You are EVA (Embedded Virtual Assistant), an intelligent AI assistant 
with access to a document knowledge base. Be helpful, precise, and concise. 
Format responses with markdown when appropriate."""


CHART_SYSTEM_PROMPT = """CHART OUTPUT CONTRACT (HIGH PRIORITY)

When the user asks for a chart, graph, pie chart, bar chart, line chart, or visualization:

MUST:
- include a fenced ```chart block containing valid JSON
- use one of these chart types when possible: pie, bar, line
- include title and data fields

NEVER:
- provide matplotlib code
- provide Python chart code
- describe charts only in prose
- say "imagine a chart"
- explain how to create charts instead of returning the chart block

Allowed:
- a short explanation after the chart block."""


CHART_INTENT_WORDS = ("chart", "graph", "pie", "bar", "line", "visualization")


def is_chart_request(prompt: str) -> bool:
    text = (prompt or "").lower()
    return any(word in text for word in CHART_INTENT_WORDS)


def chart_system_prompt(system_prompt: str, prompt: str) -> str:
    if is_chart_request(prompt) and CHART_SYSTEM_PROMPT not in system_prompt:
        return f"{system_prompt}\n\n{CHART_SYSTEM_PROMPT}"
    return system_prompt


def _log_raw_model_response(content: str) -> None:
    print("RAW MODEL RESPONSE:")
    print(content)


# ── Request / Response models ─────────────────────────────
class ChatRequest(BaseModel):
    message:     str
    question:    Optional[str] = None   # some frontends send "question"
    user_id:     str = "user_001"
    model:       Optional[str] = None
    temperature: float = 0.7
    max_tokens:  int = 1024
    history:     Optional[list] = []


class ChatResponse(BaseModel):
    answer:     str
    response:   str           # alias so both field names work
    provider:   str           # "rag" | "groq" | "openai" | "gemini"
    confidence: Optional[float] = None
    sources:    Optional[list] = None
    fallback:   bool = False
    latency_ms: Optional[int] = None


# ══════════════════════════════════════════════════════════
# PROVIDER FUNCTIONS
# ══════════════════════════════════════════════════════════

async def call_groq(question: str, history: list, temperature: float, max_tokens: int) -> str:
    """Call Groq LLaMA — fastest, free tier available"""
    from groq import Groq
    client = Groq(api_key=GROQ_KEY)
    messages = [{"role": "system", "content": chart_system_prompt(SYSTEM_PROMPT, question)}]
    messages += [{"role": m["role"], "content": m["content"]} for m in (history or [])]
    messages.append({"role": "user", "content": question})
    resp = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    content = resp.choices[0].message.content
    _log_raw_model_response(content or "")
    return content


async def call_openai(question: str, history: list, temperature: float, max_tokens: int) -> str:
    """Call OpenAI GPT-4o-mini — cheap fallback ($0.15/1M tokens)"""
    import openai
    client = openai.AsyncOpenAI(api_key=OPENAI_KEY)
    messages = [{"role": "system", "content": chart_system_prompt(SYSTEM_PROMPT, question)}]
    messages += [{"role": m["role"], "content": m["content"]} for m in (history or [])]
    messages.append({"role": "user", "content": question})
    resp = await client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    content = resp.choices[0].message.content
    _log_raw_model_response(content or "")
    return content


async def call_gemini(question: str, history: list, temperature: float) -> str:
    """Call Google Gemini — free tier: 1500 requests/day"""
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=chart_system_prompt(SYSTEM_PROMPT, question),
        generation_config={"temperature": temperature, "max_output_tokens": 1024}
    )
    # Build conversation history for Gemini
    gemini_history = []
    for m in (history or []):
        role = "user" if m["role"] == "user" else "model"
        gemini_history.append({"role": role, "parts": [m["content"]]})
    chat = model.start_chat(history=gemini_history)
    resp = chat.send_message(question)
    _log_raw_model_response(resp.text or "")
    return resp.text


async def call_rag(question: str, user_id: str) -> dict:
    """
    Call your existing RAG pipeline.
    Returns: {"answer": str, "confidence": float, "sources": list}
    Adjust the import to match your actual rag_pipeline.py
    """
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent))
        from rag_pipeline import RAGPipeline

        rag = RAGPipeline()
        result = rag.query(question)

        # Handle different return formats from your pipeline
        if isinstance(result, dict):
            answer     = result.get("answer") or result.get("response") or ""
            confidence = float(result.get("confidence", result.get("score", 0.0)))
            sources    = result.get("sources", result.get("source_documents", []))
        elif isinstance(result, str):
            answer, confidence, sources = result, 0.5, []
        else:
            answer, confidence, sources = str(result), 0.0, []

        return {"answer": answer, "confidence": confidence, "sources": sources}

    except Exception as e:
        return {"answer": "", "confidence": 0.0, "sources": [], "error": str(e)}


# ══════════════════════════════════════════════════════════
# SMART CHAT — main function to call from /chat route
# ══════════════════════════════════════════════════════════

async def smart_chat(req: ChatRequest) -> ChatResponse:
    """
    Intelligent LLM cascade:
      RAG → Groq → OpenAI → Gemini

    Replace your /chat route body with:
      return await smart_chat(req)
    """
    t_start  = time.time()
    question = req.question or req.message
    history  = req.history or []

    # ── Step 1: Try RAG first ─────────────────────────────
    rag_result = await call_rag(question, req.user_id)
    rag_answer     = rag_result.get("answer", "")
    rag_confidence = rag_result.get("confidence", 0.0)
    rag_sources    = rag_result.get("sources", [])

    # Good RAG answer → return immediately
    if rag_answer and rag_confidence >= THRESHOLD:
        latency = int((time.time() - t_start) * 1000)
        return ChatResponse(
            answer=rag_answer,
            response=rag_answer,
            provider="rag",
            confidence=rag_confidence,
            sources=rag_sources,
            fallback=False,
            latency_ms=latency,
        )

    # ── Step 2: RAG low confidence → add context + try LLM ─
    # Inject partial RAG context into question for better LLM answer
    enhanced_q = question
    if rag_answer and rag_confidence > 0.1:
        enhanced_q = (
            f"{question}\n\n"
            f"[Partial context from knowledge base (confidence {rag_confidence:.0%})]:\n"
            f"{rag_answer[:600]}"
        )

    # ── Step 3: Try Groq (LLaMA) ─────────────────────────
    if GROQ_KEY:
        try:
            answer = await call_groq(enhanced_q, history, req.temperature, req.max_tokens)
            latency = int((time.time() - t_start) * 1000)
            return ChatResponse(
                answer=answer,
                response=answer,
                provider="groq",
                confidence=None,
                sources=rag_sources if rag_sources else None,
                fallback=True,
                latency_ms=latency,
            )
        except Exception as e:
            print(f"[EVA] Groq failed: {e}")

    # ── Step 4: Try OpenAI (GPT-4o-mini) ─────────────────
    if OPENAI_KEY:
        try:
            answer = await call_openai(enhanced_q, history, req.temperature, req.max_tokens)
            latency = int((time.time() - t_start) * 1000)
            return ChatResponse(
                answer=answer,
                response=answer,
                provider="openai",
                confidence=None,
                sources=None,
                fallback=True,
                latency_ms=latency,
            )
        except Exception as e:
            print(f"[EVA] OpenAI failed: {e}")

    # ── Step 5: Try Gemini ────────────────────────────────
    if GEMINI_KEY:
        try:
            answer = await call_gemini(enhanced_q, history, req.temperature)
            latency = int((time.time() - t_start) * 1000)
            return ChatResponse(
                answer=answer,
                response=answer,
                provider="gemini",
                confidence=None,
                sources=None,
                fallback=True,
                latency_ms=latency,
            )
        except Exception as e:
            print(f"[EVA] Gemini failed: {e}")

    # ── Step 6: All failed → return best RAG answer ───────
    final = rag_answer or "I couldn't find an answer. Please check your API keys in .env"
    latency = int((time.time() - t_start) * 1000)
    return ChatResponse(
        answer=final,
        response=final,
        provider="rag_only",
        confidence=rag_confidence,
        sources=rag_sources,
        fallback=False,
        latency_ms=latency,
    )


# ══════════════════════════════════════════════════════════
# STREAMING VERSION (for /chat/stream endpoint)
# ══════════════════════════════════════════════════════════

async def smart_chat_stream(req: ChatRequest):
    """
    Streaming version — yields SSE tokens.
    Use in /chat/stream:
      return StreamingResponse(smart_chat_stream(req), media_type="text/event-stream")
    """
    import json

    question = req.question or req.message
    history  = req.history or []

    # Quick RAG check
    rag_result = await call_rag(question, req.user_id)
    rag_answer     = rag_result.get("answer", "")
    rag_confidence = rag_result.get("confidence", 0.0)

    if rag_answer and rag_confidence >= THRESHOLD:
        # Stream RAG answer word by word
        yield f"data: {json.dumps({'provider': 'rag', 'confidence': rag_confidence})}\n\n"
        for word in rag_answer.split(" "):
            yield f"data: {json.dumps({'token': word + ' '})}\n\n"
        yield "data: [DONE]\n\n"
        return

    # Use best available LLM for streaming
    enhanced_q = question
    if rag_answer and rag_confidence > 0.1:
        enhanced_q = f"{question}\n\nPartial context: {rag_answer[:400]}"

    # Try Groq streaming
    if GROQ_KEY:
        try:
            from groq import Groq
            client = Groq(api_key=GROQ_KEY)
            messages = [{"role": "system", "content": chart_system_prompt(SYSTEM_PROMPT, enhanced_q)}]
            messages += [{"role": m["role"], "content": m["content"]} for m in history]
            messages.append({"role": "user", "content": enhanced_q})

            yield f"data: {json.dumps({'provider': 'groq'})}\n\n"
            stream = client.chat.completions.create(
                model=GROQ_MODEL, messages=messages,
                max_tokens=req.max_tokens, temperature=req.temperature,
                stream=True
            )
            for chunk in stream:
                token = chunk.choices[0].delta.content or ""
                if token:
                    yield f"data: {json.dumps({'token': token})}\n\n"
            yield "data: [DONE]\n\n"
            return
        except Exception as e:
            print(f"[EVA stream] Groq failed: {e}")

    # Fallback: OpenAI streaming
    if OPENAI_KEY:
        try:
            import openai
            client = openai.AsyncOpenAI(api_key=OPENAI_KEY)
            messages = [{"role": "system", "content": chart_system_prompt(SYSTEM_PROMPT, enhanced_q)}]
            messages += [{"role": m["role"], "content": m["content"]} for m in history]
            messages.append({"role": "user", "content": enhanced_q})

            yield f"data: {json.dumps({'provider': 'openai'})}\n\n"
            async for chunk in await client.chat.completions.create(
                model=OPENAI_MODEL, messages=messages,
                max_tokens=req.max_tokens, temperature=req.temperature,
                stream=True
            ):
                token = chunk.choices[0].delta.content or ""
                if token:
                    yield f"data: {json.dumps({'token': token})}\n\n"
            yield "data: [DONE]\n\n"
            return
        except Exception as e:
            print(f"[EVA stream] OpenAI failed: {e}")

    # Fallback: Gemini (no streaming, simulate)
    if GEMINI_KEY:
        try:
            answer = await call_gemini(enhanced_q, history, req.temperature)
            yield f"data: {json.dumps({'provider': 'gemini'})}\n\n"
            for word in answer.split(" "):
                yield f"data: {json.dumps({'token': word + ' '})}\n\n"
            yield "data: [DONE]\n\n"
            return
        except Exception as e:
            print(f"[EVA stream] Gemini failed: {e}")

    # All failed
    yield f"data: {json.dumps({'token': 'No API keys configured. Add OPENAI_API_KEY or GEMINI_API_KEY to .env'})}\n\n"
    yield "data: [DONE]\n\n"
