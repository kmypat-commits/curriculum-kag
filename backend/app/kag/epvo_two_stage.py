"""Optional second-stage EPVO course-to-LO ranker.

The classifier score remains the link gate.  The ranking model only reorders
accepted candidates and is loaded lazily, so ordinary API requests stay light.
"""
from __future__ import annotations

import math
import hashlib
from collections import OrderedDict
from threading import RLock
from typing import Iterable

import numpy as np

from app.config import settings


class EpvoTwoStageRanker:
    def __init__(self) -> None:
        self.model = None
        self.load_error: str | None = None
        self._attempted = False
        self._lock = RLock()
        self._vector_cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._vector_cache_limit = 4096

    def _encode_cached(self, texts: list[str], batch_size: int) -> np.ndarray:
        """Encode only unseen texts; course descriptions repeat across LOs."""
        keys = [hashlib.sha256(str(value or "").encode("utf-8")).hexdigest() for value in texts]
        vectors: list[np.ndarray | None] = [None] * len(texts)
        missing: list[int] = []
        with self._lock:
            for index, key in enumerate(keys):
                cached = self._vector_cache.get(key)
                if cached is None:
                    missing.append(index)
                else:
                    self._vector_cache.move_to_end(key)
                    vectors[index] = cached
        if missing:
            encoded = self.model.encode(
                [texts[index] for index in missing],
                batch_size=batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            with self._lock:
                for index, vector in zip(missing, encoded):
                    value = np.asarray(vector, dtype=np.float32)
                    vectors[index] = value
                    self._vector_cache[keys[index]] = value
                    self._vector_cache.move_to_end(keys[index])
                while len(self._vector_cache) > self._vector_cache_limit:
                    self._vector_cache.popitem(last=False)
        return np.asarray(vectors, dtype=np.float32)

    def _ensure_loaded(self) -> bool:
        if not settings.EPVO_RANKER_ENABLED:
            return False
        with self._lock:
            if self.model is not None:
                return True
            if self._attempted:
                return False
            self._attempted = True
            try:
                from sentence_transformers import SentenceTransformer

                self.model = SentenceTransformer(
                    settings.EPVO_RANKER_MODEL_NAME,
                    device=settings.EPVO_RANKER_DEVICE,
                    local_files_only=True,
                )
                return True
            except (ImportError, OSError, RuntimeError, ValueError, TypeError) as exc:
                self.load_error = str(exc)
                self.model = None
                return False

    def rerank(
        self,
        lo_text: str,
        candidates: Iterable[dict],
    ) -> dict[int, dict]:
        rows = list(candidates)
        if not rows or not self._ensure_loaded():
            return {}
        accepted = [
            row for row in rows
            if float(row.get("classifier_similarity") or 0) >= settings.EPVO_AI_THRESHOLD
            or float(row.get("expert_score") or 0) > 0
        ]
        if not accepted:
            return {}
        try:
            lo_vector = self._encode_cached([lo_text], batch_size=1)[0]
            course_vectors = self._encode_cached(
                [row["text"] for row in accepted], batch_size=48
            )
            similarities = np.asarray(course_vectors) @ np.asarray(lo_vector)
            mean = float(np.mean(similarities))
            std = max(float(np.std(similarities)), 0.05)
            weight = max(0.0, min(0.5, float(settings.EPVO_RANKER_WEIGHT)))
            result = {}
            for row, similarity in zip(accepted, similarities):
                rank_confidence = 1.0 / (1.0 + math.exp(-(float(similarity) - mean) / std))
                classifier_score = float(row.get("classifier_score") or 0)
                result[int(row["course_id"])] = {
                    "score": max(0.0, min(1.0, (1.0 - weight) * classifier_score + weight * rank_confidence)),
                    "ranker_similarity": round(float(similarity), 4),
                    "ranker_confidence": round(rank_confidence, 4),
                    "ranker_model": settings.EPVO_RANKER_MODEL_NAME,
                    "classifier_weight": round(1.0 - weight, 3),
                    "ranker_weight": round(weight, 3),
                }
            return result
        except (RuntimeError, ValueError, TypeError, OSError, OverflowError) as exc:
            self.load_error = str(exc)
            return {}

    def status(self) -> dict:
        return {
            "enabled": settings.EPVO_RANKER_ENABLED,
            "model": settings.EPVO_RANKER_MODEL_NAME,
            "device": settings.EPVO_RANKER_DEVICE,
            "loaded": self.model is not None,
            "load_error": self.load_error,
            "weight": settings.EPVO_RANKER_WEIGHT,
        }


epvo_two_stage_ranker = EpvoTwoStageRanker()
