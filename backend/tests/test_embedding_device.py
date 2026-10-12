import sys
from types import SimpleNamespace

from app.kag.embedding_service import _resolve_sbert_device
from app.kag.embedding_service import EmbeddingService
import numpy as np
import pytest

@pytest.mark.parametrize('batch', [False, True])
def test_failed_transformer_is_not_reported_or_cached_as_semantic(batch):
    class FailedModel:
        device = 'cpu'
        def encode(self, *_args, **_kwargs):
            raise RuntimeError('controlled encoder failure')
    service = EmbeddingService()
    service._load_attempted = True
    service.model = FailedModel()
    vector = service.encode_batch(['actual text'])[0] if batch else service.encode('actual text')
    assert service.get_model_version() == 'feature-hash-v2'
    assert service.get_status()['mode'] == 'feature_hash_fallback'
    assert np.array_equal(service._cache[service._cache_key('actual text')], vector)

def test_failed_batch_does_not_mix_cached_transformer_and_hash_vectors():
    from app.config import settings
    class Model:
        device = 'cpu'
        fail = False
        def encode(self, text, **_kwargs):
            if self.fail:
                raise RuntimeError('controlled batch failure')
            return np.ones(settings.EMBEDDING_DIMENSION, dtype=np.float32)
    service = EmbeddingService()
    service._load_attempted = True
    service.model = Model()
    service.encode('cached text')
    service.model.fail = True
    vectors = service.encode_batch(['cached text', 'new text'])
    fallback = EmbeddingService()
    fallback._load_attempted = True
    assert np.array_equal(vectors[0], fallback.encode('cached text'))
    assert service.get_model_version() == 'feature-hash-v2'


def test_cuda_request_falls_back_on_cpu_only_torch(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)),
    )
    assert _resolve_sbert_device("cuda") == "cpu"


def test_auto_keeps_sentence_transformer_auto_selection():
    assert _resolve_sbert_device("auto") is None


def test_encode_batch_reuses_cached_sentence_transformer_vectors():
    class FakeModel:
        def __init__(self):
            self.calls = 0

        def encode(self, texts, **kwargs):
            self.calls += 1
            return np.ones((len(texts), 384), dtype=np.float32)

    service = EmbeddingService()
    service.model = FakeModel()
    service._load_attempted = True

    first = service.encode_batch(["course one", "course two"])
    second = service.encode_batch(["course one", "course two"])

    assert first.shape == (2, 384)
    assert np.array_equal(first, second)
    assert service.model.calls == 1


def test_encode_batch_deduplicates_uncached_texts_within_one_batch():
    class FakeModel:
        def __init__(self):
            self.batches = []

        def encode(self, texts, **kwargs):
            self.batches.append(list(texts))
            return np.arange(len(texts) * 384, dtype=np.float32).reshape(len(texts), 384)

    service = EmbeddingService()
    service.model = FakeModel()
    service._load_attempted = True

    vectors = service.encode_batch(["same course", "other course", "same course"])

    assert service.model.batches == [["same course", "other course"]]
    assert np.array_equal(vectors[0], vectors[2])


def test_embedding_cache_does_not_reuse_fallback_vectors_after_model_becomes_available():
    service = EmbeddingService()
    service._load_attempted = True
    fallback = service.encode("same text")

    class FakeModel:
        device = "cpu"

        def encode(self, text, **_kwargs):
            return np.ones(768, dtype=np.float32)

    service.model = FakeModel()
    sbert = service.encode("same text")

    assert not np.array_equal(fallback, sbert)
    assert service.get_status()["runtime_profile"].startswith("sbert:")
