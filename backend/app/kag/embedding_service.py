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


def _resolve_sbert_device(requested: str) -> str | None:
    """Use CPU when a config requests CUDA on a CPU-only runtime."""
    normalized = (requested or "auto").strip().lower()
    if normalized == "auto":
        return None
    if normalized in {"cuda", "gpu"}:
        try:
            import torch
            if not torch.cuda.is_available():
                return "cpu"
        except (ImportError, OSError, RuntimeError):
            return "cpu"
        return "cuda"
    return requested

class EmbeddingService:
    def __init__(self):
        self.model_name = settings.EMBEDDING_MODEL_NAME
        self.model = None
        self.load_error: Optional[str] = None
        self._load_attempted = False
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._cache_lock = RLock()
        self._model_lock = RLock()
        self._cache_limit = 8192

    def _ensure_model_loaded(self):
        if self._load_attempted or not (SBERT_INSTALLED and settings.ENABLE_SBERT):
            return
        with self._model_lock:
            if self._load_attempted:
                return
            self._load_attempted = True
            self._load_model()

    def _runtime_profile(self) -> str:
        if self.model is not None:
            return f"sbert:{self.model_name}:device={getattr(self.model, 'device', 'unknown')}:dim={settings.EMBEDDING_DIMENSION}"
        return f"feature-hash-v2:dim={settings.EMBEDDING_DIMENSION}"

    def _cache_key(self, text: str) -> str:
        return hashlib.sha256(f"{self._runtime_profile()}\0{text}".encode("utf-8")).hexdigest()

    def _load_model(self):
        global SentenceTransformer, HAS_TRANSFORMERS
        try:
            if SentenceTransformer is None:
                from sentence_transformers import SentenceTransformer as _SentenceTransformer
                SentenceTransformer = _SentenceTransformer
                HAS_TRANSFORMERS = True
            device = _resolve_sbert_device(settings.SBERT_DEVICE)
            self.model = SentenceTransformer(
                self.model_name,
                device=device,
                local_files_only=True,
            )
        except (AssertionError, ImportError, OSError, RuntimeError, ValueError, TypeError) as exc:
            self.load_error = str(exc)
            self.model = None
    def encode(self, text: str) -> np.ndarray:
        if not text or not text.strip(): return np.zeros(settings.EMBEDDING_DIMENSION, dtype=np.float32)
        self._ensure_model_loaded()
        cache_key = self._cache_key(text)
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                self._cache.move_to_end(cache_key)
                return cached
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
        if not texts:
            return np.empty((0, settings.EMBEDDING_DIMENSION), dtype=np.float32)

        self._ensure_model_loaded()
        keys = [self._cache_key(text) if text and text.strip() else "" for text in texts]
        vectors: list[Optional[np.ndarray]] = [None] * len(texts)
        missing_indices: list[int] = []
        with self._cache_lock:
            for index, key in enumerate(keys):
                if key:
                    cached = self._cache.get(key)
                    if cached is not None:
                        self._cache.move_to_end(key)
                        vectors[index] = cached
                        continue
                missing_indices.append(index)

        if not missing_indices:
            return np.vstack(vectors).astype(np.float32)

        if self.model is not None:
            try:
                # Use one vectorized call: SentenceTransformers still chunks
                # internally, but avoids Python/model setup overhead for every
                # small frontier batch.  The configured bound keeps staging
                # CPU/RAM usage predictable.
                batch_size = min(max(int(settings.SBERT_BATCH_SIZE), 1), 128)
                # A candidate can occur more than once in the same frontier
                # (for example through equivalent EPVO records or localized
                # catalogue entries).  The cache only receives values *after*
                # ``model.encode`` returns, so the old implementation encoded
                # every duplicate in a cold batch.  Group by cache key first;
                # this preserves ordering and exact vectors while avoiding
                # redundant transformer work.
                unique_indices: list[int] = []
                duplicate_indices: dict[int, list[int]] = {}
                index_by_key: dict[str, int] = {}
                for index in missing_indices:
                    key = keys[index]
                    original = index_by_key.get(key)
                    if original is None:
                        index_by_key[key] = index
                        unique_indices.append(index)
                    else:
                        duplicate_indices.setdefault(original, []).append(index)
                encoded_matrix = self.model.encode(
                    [texts[index] for index in unique_indices],
                    batch_size=batch_size,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                ).astype(np.float32)
                for index, vector in zip(unique_indices, encoded_matrix):
                    vectors[index] = vector
                    with self._cache_lock:
                        self._cache[keys[index]] = vector
                        self._cache.move_to_end(keys[index])
                        while len(self._cache) > self._cache_limit:
                            self._cache.popitem(last=False)
                    for duplicate_index in duplicate_indices.get(index, []):
                        vectors[duplicate_index] = vector
                return np.vstack(vectors).astype(np.float32)
            except (RuntimeError, ValueError, TypeError, OSError) as exc: self.load_error = str(exc)
        for index in missing_indices:
            vectors[index] = self.encode(texts[index])
        return np.vstack(vectors).astype(np.float32)
    def get_model_version(self) -> str:
        return self.model_name if self.model is not None else "feature-hash-v2"
    def get_status(self) -> dict:
        mode = "sentence_transformer" if self.model is not None else "feature_hash_fallback"
        if settings.ENABLE_SBERT and not self._load_attempted:
            mode = "sentence_transformer_pending"
        return {"mode": mode, "model_name": self.get_model_version(), "configured_model": self.model_name, "runtime_profile": self._runtime_profile(), "dimension": settings.EMBEDDING_DIMENSION, "sentence_transformers_installed": SBERT_INSTALLED, "sbert_enabled": settings.ENABLE_SBERT, "model_loaded": self.model is not None, "load_error": self.load_error, "device": str(getattr(self.model, "device", "cpu")) if self.model is not None else None, "epvo_ai_enabled": settings.EPVO_AI_ENABLED, "epvo_ai_threshold": settings.EPVO_AI_THRESHOLD, "cache_entries": len(self._cache), "cache_limit": self._cache_limit}

embedding_service = EmbeddingService()
