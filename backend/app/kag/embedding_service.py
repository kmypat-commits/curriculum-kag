from typing import Optional
import hashlib
import importlib.util
import re
from collections import OrderedDict
from threading import RLock
import numpy as np
from app.config import settings
SentenceTransformer = None
SBERT_INSTALLED = importlib.util.find_spec("sentence_transformers") is not None
HAS_TRANSFORMERS = False

class EmbeddingService:
    def __init__(self):
        self.model_name = settings.EMBEDDING_MODEL_NAME
        self.model = None
        self.load_error: Optional[str] = None
        self._load_attempted = False
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._cache_lock = RLock()
        self._cache_limit = 8192

    def _ensure_model_loaded(self):
        if self._load_attempted or not (SBERT_INSTALLED and settings.ENABLE_SBERT):
            return
        self._load_attempted = True
        self._load_model()

    def _load_model(self):
        global SentenceTransformer, HAS_TRANSFORMERS
        try:
            if SentenceTransformer is None:
                from sentence_transformers import SentenceTransformer as _SentenceTransformer
                SentenceTransformer = _SentenceTransformer
                HAS_TRANSFORMERS = True
            device = None if settings.SBERT_DEVICE == "auto" else settings.SBERT_DEVICE
            self.model = SentenceTransformer(
                self.model_name,
                device=device,
                local_files_only=True,
            )
        except (ImportError, OSError, RuntimeError, ValueError, TypeError) as exc:
            self.load_error = str(exc)
            self.model = None
    def encode(self, text: str) -> np.ndarray:
        if not text or not text.strip(): return np.zeros(settings.EMBEDDING_DIMENSION, dtype=np.float32)
        cache_key = hashlib.sha256(text.encode("utf-8")).hexdigest()
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                self._cache.move_to_end(cache_key)
                return cached
        self._ensure_model_loaded()
        if self.model is not None:
            try:
                vector = self.model.encode(text, convert_to_numpy=True, normalize_embeddings=True).astype(np.float32)
                with self._cache_lock:
                    self._cache[cache_key] = vector
                    self._cache.move_to_end(cache_key)
                    while len(self._cache) > self._cache_limit:
                        self._cache.popitem(last=False)
                return vector
            except (RuntimeError, ValueError, TypeError, OSError) as exc: self.load_error = str(exc)
        vector = np.zeros(settings.EMBEDDING_DIMENSION, dtype=np.float32)
        tokens = re.findall(r"[\w-]+", text.lower(), flags=re.UNICODE)
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % settings.EMBEDDING_DIMENSION
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = np.linalg.norm(vector)
        vector = vector / norm if norm > 0 else vector
        with self._cache_lock:
            self._cache[cache_key] = vector
            while len(self._cache) > self._cache_limit:
                self._cache.popitem(last=False)
        return vector
    def encode_batch(self, texts: list[str]) -> np.ndarray:
        self._ensure_model_loaded()
        if self.model is not None:
            try:
                # Keep inference responsive on CPU and avoid one long opaque
                # call for large EPVO frontiers.
                batch_size = 32
                vectors = [
                    self.model.encode(
                        texts[start:start + batch_size],
                        convert_to_numpy=True,
                        normalize_embeddings=True,
                        show_progress_bar=False,
                    )
                    for start in range(0, len(texts), batch_size)
                ]
                return np.vstack(vectors).astype(np.float32) if vectors else np.empty((0, settings.EMBEDDING_DIMENSION))
            except (RuntimeError, ValueError, TypeError, OSError) as exc: self.load_error = str(exc)
        return np.vstack([self.encode(text) for text in texts]) if texts else np.empty((0, settings.EMBEDDING_DIMENSION))
    def get_model_version(self) -> str:
        return self.model_name if self.model is not None else "feature-hash-v2"
    def get_status(self) -> dict:
        return {"mode": "sentence_transformer" if self.model is not None else "feature_hash_fallback", "model_name": self.get_model_version(), "configured_model": self.model_name, "dimension": settings.EMBEDDING_DIMENSION, "sentence_transformers_installed": SBERT_INSTALLED, "sbert_enabled": settings.ENABLE_SBERT, "model_loaded": self.model is not None, "load_error": self.load_error, "device": str(getattr(self.model, "device", "cpu")) if self.model is not None else None, "epvo_ai_enabled": settings.EPVO_AI_ENABLED, "epvo_ai_threshold": settings.EPVO_AI_THRESHOLD, "cache_entries": len(self._cache), "cache_limit": self._cache_limit}

embedding_service = EmbeddingService()
