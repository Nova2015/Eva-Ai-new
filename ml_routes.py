# ════════════════════════════════════════════════════════════════════════════
# ML ENDPOINTS  — paste these into app.py after the /memory endpoints
# ════════════════════════════════════════════════════════════════════════════
#
# Also add these imports near the top of app.py:
#   from ml_engine import get_classifier, get_sentiment, get_trainer
#
# And add these Pydantic models with the others:
#
# class ClassifyRequest(BaseModel):
#     text: str
#
# class SentimentRequest(BaseModel):
#     text: str
#     messages: list = []
#
# class TrainRequest(BaseModel):
#     pairs: list          # [{"sentence1":..,"sentence2":..,"label":0.9}, ...]
#     epochs: int = 3
#     batch_size: int = 16
#
# class SimilarityRequest(BaseModel):
#     text1: str
#     text2: str
# ════════════════════════════════════════════════════════════════════════════


# ── Document Classifier ───────────────────────────────────────────────────────

@app.post("/ml/classify")
async def classify_document(req: ClassifyRequest):
    """Auto-classify a document chunk into category."""
    try:
        clf = get_classifier()
        return clf.classify(req.text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ml/classify-batch")
async def classify_batch(texts: list):
    """Classify multiple texts at once."""
    try:
        clf = get_classifier()
        return {"results": clf.classify_batch(texts)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ml/classifier/retrain")
async def retrain_classifier(samples: list):
    """
    Retrain classifier with new samples.
    Body: [{"text": "...", "label": "Technical"}, ...]
    """
    try:
        clf = get_classifier()
        pairs = [(s["text"], s["label"]) for s in samples]
        clf.retrain(pairs)
        return {"message": f"✅ Retrained on {len(pairs)} new samples"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Sentiment Analysis ────────────────────────────────────────────────────────

@app.post("/ml/sentiment")
async def analyze_sentiment(req: SentimentRequest):
    """Analyze sentiment of a single text."""
    try:
        sa = get_sentiment()
        return sa.analyze(req.text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ml/sentiment/conversation")
async def analyze_conversation_sentiment(req: SentimentRequest):
    """
    Analyze sentiment across a full conversation.
    req.messages: [{"role": "user", "content": "..."}, ...]
    """
    try:
        sa = get_sentiment()
        return sa.analyze_conversation(req.messages)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/ml/sentiment/mode")
async def sentiment_mode():
    """Returns which sentiment backend is active."""
    sa = get_sentiment()
    return {"mode": sa.mode}


# ── Embedding Trainer ─────────────────────────────────────────────────────────

@app.get("/ml/embeddings/status")
async def embedding_status():
    """Get custom embedding model status and training log."""
    trainer = get_trainer()
    return trainer.get_status()

@app.post("/ml/embeddings/train")
async def train_embeddings(req: TrainRequest):
    """
    Fine-tune the embedding model on domain pairs.
    pairs: [{"sentence1": "...", "sentence2": "...", "label": 0.9}]
    label 1.0 = very similar, 0.0 = very different
    """
    try:
        trainer = get_trainer()
        result  = trainer.train(req.pairs, epochs=req.epochs, batch_size=req.batch_size)
        if result["success"]:
            return {"message": f"✅ Trained on {result['samples']} pairs in {result['elapsed_sec']}s"}
        raise HTTPException(status_code=500, detail=result["error"])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ml/embeddings/similarity")
async def compute_similarity(req: SimilarityRequest):
    """Compute semantic similarity between two texts (0.0 - 1.0)."""
    try:
        trainer = get_trainer()
        score   = trainer.similarity(req.text1, req.text2)
        label   = "Very Similar" if score > 0.85 else "Similar" if score > 0.6 else "Different" if score < 0.3 else "Somewhat Similar"
        return {"similarity": score, "label": label}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ml/embeddings/encode")
async def encode_texts(texts: list):
    """Encode a list of texts into embedding vectors."""
    try:
        trainer = get_trainer()
        vecs    = trainer.encode(texts)
        return {"vectors": vecs, "dim": len(vecs[0]) if vecs else 0}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── ML Health / Stats ─────────────────────────────────────────────────────────

@app.get("/ml/health")
async def ml_health():
    """Overview of all ML components."""
    try:
        clf     = get_classifier()
        sa      = get_sentiment()
        trainer = get_trainer()
        return {
            "classifier": {
                "loaded":  clf.model is not None,
                "labels":  clf.labels,
            },
            "sentiment": {
                "loaded": sa.mode != "none",
                "mode":   sa.mode,
            },
            "embeddings": {
                "custom_trained": trainer.trained_model is not None,
                "base_model":     trainer.base_model,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
