"""
EVA — Unsupervised Learning + Fine-Tuning Module
K-Means / HDBSCAN clustering + LoRA/PEFT fine-tuning stubs
Add to your FastAPI app.py with: from ml_advanced import router as ml_advanced_router
                                  app.include_router(ml_advanced_router)
"""

import os
import json
import logging
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("EVA.ml_advanced")
router = APIRouter(prefix="/ml/advanced", tags=["ML Advanced"])

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
MODEL_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────

class ClusterRequest(BaseModel):
    texts: List[str]
    n_clusters: int = 5
    method: str = "kmeans"          # "kmeans" or "hdbscan"
    min_cluster_size: int = 2       # for HDBSCAN

class FineTuneRequest(BaseModel):
    pairs: List[dict]               # [{"input": "...", "output": "..."}]
    epochs: int = 3
    learning_rate: float = 2e-4
    method: str = "lora"            # "lora" or "full"

class TopicRequest(BaseModel):
    texts: List[str]
    n_topics: int = 5

# ─────────────────────────────────────────────────────────────
# CLUSTERING ENGINE
# ─────────────────────────────────────────────────────────────

class ClusteringEngine:
    def __init__(self):
        self.embedder = None
        self._load_embedder()

    def _load_embedder(self):
        try:
            from sentence_transformers import SentenceTransformer
            self.embedder = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("✅ Clustering embedder loaded")
        except Exception as e:
            logger.warning(f"⚠️ Embedder load failed: {e}")

    def embed(self, texts: list) -> np.ndarray:
        if self.embedder is None:
            raise RuntimeError("Embedder not loaded")
        return self.embedder.encode(texts, show_progress_bar=False)

    def kmeans_cluster(self, texts: list, n_clusters: int) -> dict:
        """K-Means clustering — groups similar questions/docs"""
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import normalize

        embeddings = self.embed(texts)
        embeddings_norm = normalize(embeddings)

        n = min(n_clusters, len(texts))
        km = KMeans(n_clusters=n, random_state=42, n_init=10)
        labels = km.fit_predict(embeddings_norm)

        # Build cluster groups
        clusters = {}
        for idx, label in enumerate(labels.tolist()):
            clusters.setdefault(str(label), []).append({
                "index": idx,
                "text": texts[idx][:120] + ("…" if len(texts[idx]) > 120 else ""),
            })

        # Representative text per cluster (closest to centroid)
        representatives = {}
        for label_id in range(n):
            mask = labels == label_id
            if mask.any():
                center = km.cluster_centers_[label_id]
                dists = np.linalg.norm(embeddings_norm[mask] - center, axis=1)
                best = np.where(mask)[0][np.argmin(dists)]
                representatives[str(label_id)] = texts[best][:100]

        inertia = float(km.inertia_)
        silhouette = self._silhouette(embeddings_norm, labels)

        return {
            "method": "kmeans",
            "n_clusters": n,
            "clusters": clusters,
            "representatives": representatives,
            "inertia": round(inertia, 4),
            "silhouette_score": round(silhouette, 4),
            "total_texts": len(texts),
        }

    def hdbscan_cluster(self, texts: list, min_cluster_size: int) -> dict:
        """HDBSCAN — density-based, auto-detects cluster count"""
        try:
            import hdbscan
        except ImportError:
            raise HTTPException(
                status_code=422,
                detail="hdbscan not installed. Run: pip install hdbscan"
            )

        embeddings = self.embed(texts)

        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=max(2, min_cluster_size),
            metric="euclidean",
            cluster_selection_method="eom",
        )
        labels = clusterer.fit_predict(embeddings)

        unique_labels = set(labels.tolist()) - {-1}  # -1 = noise
        clusters = {}
        for idx, label in enumerate(labels.tolist()):
            key = str(label) if label != -1 else "noise"
            clusters.setdefault(key, []).append({
                "index": idx,
                "text": texts[idx][:120] + ("…" if len(texts[idx]) > 120 else ""),
                "probability": round(float(clusterer.probabilities_[idx]), 3),
            })

        return {
            "method": "hdbscan",
            "n_clusters": len(unique_labels),
            "noise_points": int(np.sum(labels == -1)),
            "clusters": clusters,
            "total_texts": len(texts),
        }

    def _silhouette(self, X, labels) -> float:
        try:
            from sklearn.metrics import silhouette_score
            if len(set(labels)) < 2:
                return 0.0
            return float(silhouette_score(X, labels, sample_size=min(300, len(X))))
        except Exception:
            return 0.0

    def topic_keywords(self, texts: list, n_topics: int) -> dict:
        """Extract topic keywords using TF-IDF"""
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.decomposition import NMF

        vec = TfidfVectorizer(max_features=1000, stop_words="english", ngram_range=(1, 2))
        tfidf = vec.fit_transform(texts)

        n = min(n_topics, len(texts))
        nmf = NMF(n_components=n, random_state=42, max_iter=300)
        nmf.fit(tfidf)

        feature_names = vec.get_feature_names_out()
        topics = {}
        for i, comp in enumerate(nmf.components_):
            top_idx = comp.argsort()[-8:][::-1]
            topics[f"topic_{i}"] = [feature_names[j] for j in top_idx]

        return {"topics": topics, "n_topics": n, "total_texts": len(texts)}


_clustering_engine: Optional[ClusteringEngine] = None

def get_clustering():
    global _clustering_engine
    if _clustering_engine is None:
        _clustering_engine = ClusteringEngine()
    return _clustering_engine


# ─────────────────────────────────────────────────────────────
# FINE-TUNING ENGINE (LoRA / PEFT)
# ─────────────────────────────────────────────────────────────

class FineTuningEngine:
    def __init__(self):
        self.log_path = MODEL_DIR / "finetune_log.json"
        self.log = self._load_log()

    def _load_log(self) -> list:
        if self.log_path.exists():
            try:
                return json.loads(self.log_path.read_text())
            except Exception:
                return []
        return []

    def _save_log(self):
        self.log_path.write_text(json.dumps(self.log, indent=2))

    def lora_finetune(self, pairs: list, epochs: int, lr: float) -> dict:
        """
        LoRA fine-tuning using HuggingFace PEFT.
        Requires: pip install peft transformers accelerate bitsandbytes
        """
        try:
            from transformers import AutoTokenizer, AutoModelForCausalLM, TrainingArguments, Trainer
            from peft import LoraConfig, get_peft_model, TaskType
            from datasets import Dataset
        except ImportError as e:
            return {
                "success": False,
                "error": f"Missing packages: {e}. Run: pip install peft transformers accelerate datasets",
                "install_cmd": "pip install peft transformers accelerate datasets bitsandbytes"
            }

        try:
            start = datetime.now()
            model_name = "microsoft/phi-2"  # Small, fast model good for fine-tuning

            logger.info(f"🚀 LoRA fine-tuning started: {len(pairs)} pairs, {epochs} epochs")

            tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
            tokenizer.pad_token = tokenizer.eos_token

            # Prepare dataset
            def format_pair(p):
                return f"### Input:\n{p['input']}\n\n### Output:\n{p['output']}"

            formatted = [{"text": format_pair(p)} for p in pairs]
            dataset = Dataset.from_list(formatted)

            def tokenize(example):
                return tokenizer(
                    example["text"],
                    truncation=True,
                    max_length=512,
                    padding="max_length",
                )

            tokenized = dataset.map(tokenize, batched=True)

            # LoRA config
            lora_config = LoraConfig(
                task_type=TaskType.CAUSAL_LM,
                r=8,                    # Rank — lower = less params
                lora_alpha=16,
                lora_dropout=0.1,
                target_modules=["q_proj", "v_proj"],
                bias="none",
            )

            model = AutoModelForCausalLM.from_pretrained(model_name, trust_remote_code=True)
            model = get_peft_model(model, lora_config)
            model.print_trainable_parameters()

            output_dir = str(MODEL_DIR / "lora_adapter")

            training_args = TrainingArguments(
                output_dir=output_dir,
                num_train_epochs=epochs,
                per_device_train_batch_size=2,
                gradient_accumulation_steps=4,
                learning_rate=lr,
                logging_steps=10,
                save_strategy="epoch",
                fp16=False,
                report_to="none",
            )

            trainer = Trainer(
                model=model,
                args=training_args,
                train_dataset=tokenized,
            )

            trainer.train()
            model.save_pretrained(output_dir)
            tokenizer.save_pretrained(output_dir)

            elapsed = round((datetime.now() - start).total_seconds(), 1)

            entry = {
                "timestamp": datetime.now().isoformat(),
                "method": "lora",
                "samples": len(pairs),
                "epochs": epochs,
                "elapsed_sec": elapsed,
                "model": model_name,
                "adapter_path": output_dir,
                "success": True,
            }
            self.log.append(entry)
            self._save_log()

            logger.info(f"✅ LoRA fine-tuning complete in {elapsed}s")
            return entry

        except Exception as e:
            logger.error(f"LoRA fine-tuning failed: {e}")
            return {"success": False, "error": str(e)}

    def embedding_finetune(self, pairs: list, epochs: int) -> dict:
        """Fine-tune sentence embeddings using contrastive learning"""
        try:
            from sentence_transformers import SentenceTransformer, InputExample, losses
            from torch.utils.data import DataLoader
        except ImportError as e:
            return {
                "success": False,
                "error": f"Missing: {e}. Run: pip install sentence-transformers",
            }

        try:
            start = datetime.now()
            model = SentenceTransformer("all-MiniLM-L6-v2")

            examples = [
                InputExample(texts=[p["input"], p["output"]], label=float(p.get("label", 0.9)))
                for p in pairs
            ]

            loader = DataLoader(examples, shuffle=True, batch_size=8)
            loss = losses.CosineSimilarityLoss(model)

            output_dir = str(MODEL_DIR / "finetuned_embeddings")
            model.fit(
                train_objectives=[(loader, loss)],
                epochs=epochs,
                warmup_steps=max(10, len(examples) // 4),
                output_path=output_dir,
            )

            elapsed = round((datetime.now() - start).total_seconds(), 1)
            entry = {
                "timestamp": datetime.now().isoformat(),
                "method": "embedding_contrastive",
                "samples": len(pairs),
                "epochs": epochs,
                "elapsed_sec": elapsed,
                "model_path": output_dir,
                "success": True,
            }
            self.log.append(entry)
            self._save_log()
            return entry

        except Exception as e:
            logger.error(f"Embedding fine-tune failed: {e}")
            return {"success": False, "error": str(e)}

    def get_log(self) -> list:
        return self.log


_finetune_engine: Optional[FineTuningEngine] = None

def get_finetuner():
    global _finetune_engine
    if _finetune_engine is None:
        _finetune_engine = FineTuningEngine()
    return _finetune_engine


# ─────────────────────────────────────────────────────────────
# API ROUTES
# ─────────────────────────────────────────────────────────────

@router.post("/cluster")
async def cluster_texts(req: ClusterRequest):
    """
    Cluster similar texts using K-Means or HDBSCAN.
    Great for grouping similar questions, auto-tagging docs.
    """
    if len(req.texts) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 texts to cluster")
    try:
        engine = get_clustering()
        if req.method == "hdbscan":
            return engine.hdbscan_cluster(req.texts, req.min_cluster_size)
        return engine.kmeans_cluster(req.texts, req.n_clusters)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/topics")
async def extract_topics(req: TopicRequest):
    """Extract topic keywords from a list of texts using NMF + TF-IDF"""
    if len(req.texts) < 3:
        raise HTTPException(status_code=400, detail="Need at least 3 texts for topic extraction")
    try:
        engine = get_clustering()
        return engine.topic_keywords(req.texts, req.n_topics)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/finetune")
async def finetune_model(req: FineTuneRequest):
    """
    Fine-tune the model using LoRA (LLM) or contrastive learning (embeddings).
    method='lora'      → fine-tunes LLM with LoRA/PEFT
    method='embedding' → fine-tunes sentence embeddings
    """
    if len(req.pairs) < 4:
        raise HTTPException(status_code=400, detail="Need at least 4 training pairs")
    try:
        engine = get_finetuner()
        if req.method == "embedding":
            result = engine.embedding_finetune(req.pairs, req.epochs)
        else:
            result = engine.lora_finetune(req.pairs, req.epochs, req.learning_rate)
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error", "Fine-tuning failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/finetune/log")
async def finetune_log():
    """Get fine-tuning history"""
    engine = get_finetuner()
    return {"log": engine.get_log(), "total_runs": len(engine.get_log())}


@router.get("/cluster/health")
async def cluster_health():
    """Check clustering engine status"""
    try:
        engine = get_clustering()
        return {
            "embedder_loaded": engine.embedder is not None,
            "sklearn_available": True,
        }
    except Exception as e:
        return {"embedder_loaded": False, "error": str(e)}
