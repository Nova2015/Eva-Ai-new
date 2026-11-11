"""
ARIA — ML Engine
Provides:
  1. Document Classifier     (scikit-learn: TF-IDF + LogisticRegression)
  2. Sentiment Analyzer      (transformers: DistilBERT fine-tuned)
  3. Custom Embedding Trainer (sentence-transformers fine-tuning)
"""

import os
import json
import logging
import pickle
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("aria.ml_engine")

BASE_DIR   = Path(__file__).resolve().parent
ROOT_DIR   = BASE_DIR.parent
MODELS_DIR = ROOT_DIR / "ml_models"
MODELS_DIR.mkdir(exist_ok=True)

# ══════════════════════════════════════════════════════════════════════════════
# 1. DOCUMENT CLASSIFIER  (scikit-learn)
# ══════════════════════════════════════════════════════════════════════════════

CLASSIFIER_PATH = MODELS_DIR / "doc_classifier.pkl"
VECTORIZER_PATH = MODELS_DIR / "doc_vectorizer.pkl"

# Default training data — extended when user uploads docs
DEFAULT_TRAINING = [
    # Technical
    ("machine learning neural network deep learning model training", "Technical"),
    ("algorithm data structure python code function class method", "Technical"),
    ("api endpoint server database query sql nosql", "Technical"),
    ("software engineering architecture microservices docker kubernetes", "Technical"),
    ("tensorflow pytorch scikit learn regression classification", "Technical"),
    ("cpu gpu memory ram processor hardware specification", "Technical"),
    # Legal
    ("contract agreement terms conditions liability clause", "Legal"),
    ("jurisdiction court law legal regulation compliance", "Legal"),
    ("patent copyright trademark intellectual property rights", "Legal"),
    ("indemnification warranty disclaimer limitation damages", "Legal"),
    ("privacy policy data protection gdpr personal information", "Legal"),
    # Medical
    ("patient diagnosis treatment symptoms clinical trial", "Medical"),
    ("drug dosage medication prescription pharmaceutical", "Medical"),
    ("disease infection virus bacteria antibody immune system", "Medical"),
    ("surgery procedure hospital doctor physician nurse", "Medical"),
    ("blood pressure heart rate glucose insulin diabetes", "Medical"),
    # Financial
    ("revenue profit loss balance sheet income statement", "Financial"),
    ("investment portfolio stock market equity bond fund", "Financial"),
    ("budget forecast quarter annual report earnings", "Financial"),
    ("tax audit compliance regulatory financial statement", "Financial"),
    ("loan mortgage interest rate credit debit banking", "Financial"),
    # Research
    ("hypothesis experiment methodology results conclusion abstract", "Research"),
    ("literature review citation bibliography reference study", "Research"),
    ("statistical analysis p-value confidence interval sample", "Research"),
    ("survey questionnaire participants data collection findings", "Research"),
    # General
    ("introduction overview summary background context", "General"),
    ("table of contents chapter section paragraph heading", "General"),
    ("figure image diagram chart graph visualization", "General"),
]

class DocumentClassifier:
    def __init__(self):
        self.model      = None
        self.vectorizer = None
        self.labels     = ["Technical", "Legal", "Medical", "Financial", "Research", "General"]
        self._load_or_train()

    def _load_or_train(self):
        if CLASSIFIER_PATH.exists() and VECTORIZER_PATH.exists():
            try:
                with open(CLASSIFIER_PATH, "rb") as f:
                    self.model = pickle.load(f)
                with open(VECTORIZER_PATH, "rb") as f:
                    self.vectorizer = pickle.load(f)
                logger.info("✅ Document classifier loaded from disk")
                return
            except Exception as e:
                logger.warning(f"Failed to load classifier: {e}")
        self._train(DEFAULT_TRAINING)

    def _train(self, data: list):
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline

        texts  = [d[0] for d in data]
        labels = [d[1] for d in data]

        self.vectorizer = TfidfVectorizer(
            ngram_range=(1, 2), max_features=5000, stop_words="english"
        )
        X = self.vectorizer.fit_transform(texts)

        self.model = LogisticRegression(max_iter=500, C=1.0)
        self.model.fit(X, labels)

        # Save
        with open(CLASSIFIER_PATH, "wb") as f: pickle.dump(self.model, f)
        with open(VECTORIZER_PATH, "wb") as f: pickle.dump(self.vectorizer, f)
        logger.info(f"✅ Document classifier trained on {len(data)} samples")

    def retrain(self, new_samples: list):
        """Add new samples and retrain."""
        combined = DEFAULT_TRAINING + new_samples
        self._train(combined)

    def classify(self, text: str) -> dict:
        if not self.model or not self.vectorizer:
            return {"label": "Unknown", "confidence": 0.0, "probabilities": {}}
        try:
            X     = self.vectorizer.transform([text[:2000]])
            label = self.model.predict(X)[0]
            probs = self.model.predict_proba(X)[0]
            prob_dict = dict(zip(self.model.classes_, [round(float(p), 3) for p in probs]))
            return {
                "label":         label,
                "confidence":    round(float(max(probs)), 3),
                "probabilities": prob_dict,
            }
        except Exception as e:
            logger.error(f"Classification error: {e}")
            return {"label": "Unknown", "confidence": 0.0, "probabilities": {}}

    def classify_batch(self, texts: list) -> list:
        return [self.classify(t) for t in texts]


# ══════════════════════════════════════════════════════════════════════════════
# 2. SENTIMENT ANALYZER  (transformers / fallback to VADER)
# ══════════════════════════════════════════════════════════════════════════════

class SentimentAnalyzer:
    def __init__(self):
        self.pipeline = None
        self.mode     = "none"
        self._load()

    def _load(self):
        # Try transformers first
        try:
            from transformers import pipeline as hf_pipeline
            self.pipeline = hf_pipeline(
                "sentiment-analysis",
                model="distilbert-base-uncased-finetuned-sst-2-english",
                truncation=True, max_length=512
            )
            self.mode = "transformers"
            logger.info("✅ Sentiment: DistilBERT loaded")
            return
        except Exception as e:
            logger.warning(f"Transformers sentiment failed: {e}")

        # Fallback to VADER (pure Python)
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            self._vader = SentimentIntensityAnalyzer()
            self.mode   = "vader"
            logger.info("✅ Sentiment: VADER loaded (fallback)")
        except Exception:
            logger.warning("⚠️  No sentiment model available. Install: pip install vaderSentiment")
            self.mode = "rule"

    def analyze(self, text: str) -> dict:
        text = text.strip()
        if not text:
            return {"label": "NEUTRAL", "score": 0.5, "compound": 0.0, "mode": self.mode}

        if self.mode == "transformers":
            try:
                result = self.pipeline(text[:512])[0]
                return {
                    "label":    result["label"],
                    "score":    round(result["score"], 3),
                    "compound": round(result["score"] if result["label"] == "POSITIVE" else -result["score"], 3),
                    "mode":     "transformers",
                }
            except Exception as e:
                logger.error(f"Transformer sentiment error: {e}")

        if self.mode == "vader":
            scores = self._vader.polarity_scores(text)
            compound = scores["compound"]
            label = "POSITIVE" if compound >= 0.05 else "NEGATIVE" if compound <= -0.05 else "NEUTRAL"
            return {
                "label":    label,
                "score":    round(abs(compound), 3),
                "compound": round(compound, 3),
                "mode":     "vader",
                "details":  scores,
            }

        # Rule-based fallback
        pos_words = {"good","great","excellent","happy","love","amazing","wonderful","fantastic","helpful","thanks"}
        neg_words = {"bad","terrible","awful","hate","wrong","error","fail","broken","useless","disappointed"}
        words     = set(text.lower().split())
        pos_count = len(words & pos_words)
        neg_count = len(words & neg_words)
        if pos_count > neg_count:
            return {"label": "POSITIVE", "score": 0.7, "compound": 0.5, "mode": "rule"}
        elif neg_count > pos_count:
            return {"label": "NEGATIVE", "score": 0.7, "compound": -0.5, "mode": "rule"}
        return {"label": "NEUTRAL", "score": 0.5, "compound": 0.0, "mode": "rule"}

    def analyze_conversation(self, messages: list) -> dict:
        """Analyze a list of {role, content} messages."""
        if not messages:
            return {"overall": "NEUTRAL", "breakdown": [], "avg_compound": 0.0}

        results   = []
        compounds = []
        for msg in messages:
            r = self.analyze(msg.get("content", ""))
            results.append({
                "role":     msg.get("role", "unknown"),
                "label":    r["label"],
                "compound": r["compound"],
            })
            compounds.append(r["compound"])

        avg = sum(compounds) / len(compounds) if compounds else 0
        overall = "POSITIVE" if avg >= 0.05 else "NEGATIVE" if avg <= -0.05 else "NEUTRAL"
        return {
            "overall":      overall,
            "avg_compound": round(avg, 3),
            "breakdown":    results,
        }


# ══════════════════════════════════════════════════════════════════════════════
# 3. CUSTOM EMBEDDING TRAINER  (sentence-transformers)
# ══════════════════════════════════════════════════════════════════════════════

CUSTOM_MODEL_DIR = MODELS_DIR / "custom_embeddings"

class EmbeddingTrainer:
    def __init__(self):
        self.base_model   = "all-MiniLM-L6-v2"
        self.trained_model= None
        self.training_log = []
        self._load_existing()

    def _load_existing(self):
        if CUSTOM_MODEL_DIR.exists():
            try:
                from sentence_transformers import SentenceTransformer
                self.trained_model = SentenceTransformer(str(CUSTOM_MODEL_DIR))
                logger.info("✅ Custom embedding model loaded")
            except Exception as e:
                logger.warning(f"Could not load custom model: {e}")

    def get_status(self) -> dict:
        return {
            "base_model":    self.base_model,
            "custom_trained": self.trained_model is not None,
            "model_dir":     str(CUSTOM_MODEL_DIR),
            "training_log":  self.training_log[-10:],
        }

    def train(
        self,
        training_pairs: list,
        epochs: int = 3,
        batch_size: int = 16,
        warmup_steps: int = 100,
    ) -> dict:
        """
        Fine-tune sentence-transformers on domain pairs.
        training_pairs: list of {"sentence1": str, "sentence2": str, "label": float (0-1)}
        """
        start = time.time()
        try:
            from sentence_transformers import SentenceTransformer, InputExample, losses
            from torch.utils.data import DataLoader

            model = SentenceTransformer(self.base_model)

            examples = [
                InputExample(texts=[p["sentence1"], p["sentence2"]], label=float(p.get("label", 1.0)))
                for p in training_pairs
            ]

            loader = DataLoader(examples, shuffle=True, batch_size=batch_size)
            loss   = losses.CosineSimilarityLoss(model)

            model.fit(
                train_objectives=[(loader, loss)],
                epochs=epochs,
                warmup_steps=warmup_steps,
                show_progress_bar=False,
            )

            CUSTOM_MODEL_DIR.mkdir(exist_ok=True)
            model.save(str(CUSTOM_MODEL_DIR))
            self.trained_model = model

            elapsed = round(time.time() - start, 1)
            entry   = {
                "timestamp":   time.strftime("%Y-%m-%d %H:%M:%S"),
                "samples":     len(training_pairs),
                "epochs":      epochs,
                "elapsed_sec": elapsed,
                "status":      "success",
            }
            self.training_log.append(entry)
            logger.info(f"✅ Custom model trained in {elapsed}s")
            return {"success": True, "elapsed_sec": elapsed, "samples": len(training_pairs)}

        except ImportError:
            msg = "sentence-transformers not installed. Run: pip install sentence-transformers"
            logger.error(msg)
            return {"success": False, "error": msg}
        except Exception as e:
            logger.error(f"Training error: {e}")
            entry = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "status": "failed", "error": str(e)}
            self.training_log.append(entry)
            return {"success": False, "error": str(e)}

    def encode(self, texts: list) -> list:
        """Encode texts using custom model if available, else base model."""
        try:
            from sentence_transformers import SentenceTransformer
            model = self.trained_model or SentenceTransformer(self.base_model)
            embeddings = model.encode(texts)
            return embeddings.tolist()
        except Exception as e:
            logger.error(f"Encoding error: {e}")
            return []

    def similarity(self, text1: str, text2: str) -> float:
        """Compute cosine similarity between two texts."""
        try:
            from sentence_transformers import SentenceTransformer, util
            model = self.trained_model or SentenceTransformer(self.base_model)
            e1, e2 = model.encode([text1, text2])
            sim = float(util.cos_sim(e1, e2)[0][0])
            return round(sim, 4)
        except Exception as e:
            logger.error(f"Similarity error: {e}")
            return 0.0


# ══════════════════════════════════════════════════════════════════════════════
# Singletons
# ══════════════════════════════════════════════════════════════════════════════

_classifier = None
_sentiment  = None
_trainer    = None

def get_classifier() -> DocumentClassifier:
    global _classifier
    if _classifier is None:
        _classifier = DocumentClassifier()
    return _classifier

def get_sentiment() -> SentimentAnalyzer:
    global _sentiment
    if _sentiment is None:
        _sentiment = SentimentAnalyzer()
    return _sentiment

def get_trainer() -> EmbeddingTrainer:
    global _trainer
    if _trainer is None:
        _trainer = EmbeddingTrainer()
    return _trainer
