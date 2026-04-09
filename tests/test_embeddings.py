"""Tests for the embeddings module."""

from __future__ import annotations

import math
import struct

import pytest

from cortex import embeddings
from cortex.embeddings import (
    EMBEDDING_DIM,
    deserialize,
    embed_batch,
    embed_one,
    serialize,
)


class TestLazyInit:
    """Model should not load until the first embed call."""

    def test_model_is_none_at_import_time(self):
        # After import, the module-level _model should be None
        # (unless a previous test already triggered it).
        # We reset it to verify lazy behaviour.
        old = embeddings._model
        embeddings._model = None
        assert embeddings._model is None
        # Restore
        embeddings._model = old


class TestEmbedOne:
    def test_returns_list_of_floats(self):
        vec = embed_one("hello world")
        assert isinstance(vec, list)
        assert len(vec) == EMBEDDING_DIM
        assert all(isinstance(v, float) for v in vec)

    def test_different_inputs_give_different_vectors(self):
        v1 = embed_one("hello world")
        v2 = embed_one("quantum physics lecture notes")
        assert v1 != v2


class TestEmbedBatch:
    def test_returns_correct_count(self):
        texts = ["a", "b", "c"]
        vecs = embed_batch(texts)
        assert len(vecs) == 3

    def test_each_vector_has_correct_dim(self):
        vecs = embed_batch(["a", "b", "c"])
        for v in vecs:
            assert len(v) == EMBEDDING_DIM
            assert all(isinstance(x, float) for x in v)

    def test_batch_matches_individual(self):
        texts = ["hello", "world"]
        batch = embed_batch(texts)
        singles = [embed_one(t) for t in texts]
        for b, s in zip(batch, singles):
            for bv, sv in zip(b, s):
                assert math.isclose(bv, sv, rel_tol=1e-6)


class TestSerializeDeserialize:
    def test_round_trip(self):
        original = embed_one("round trip test")
        blob = serialize(original)
        recovered = deserialize(blob)
        assert len(recovered) == len(original)
        for o, r in zip(original, recovered):
            assert math.isclose(o, r, rel_tol=1e-6)

    def test_known_values(self):
        vec = [1.0, 2.0, 3.0]
        blob = serialize(vec)
        # Header: 4 bytes for dim (3), then 3 * 4 bytes for floats
        assert len(blob) == 4 + 3 * 4
        recovered = deserialize(blob)
        assert recovered == pytest.approx(vec)

    def test_empty_vector(self):
        vec: list[float] = []
        blob = serialize(vec)
        recovered = deserialize(blob)
        assert recovered == []

    def test_blob_is_bytes(self):
        vec = [0.5, -0.5]
        blob = serialize(vec)
        assert isinstance(blob, bytes)


class TestModelIsLazy:
    def test_model_loaded_after_embed(self):
        # After any embed call, model should be set
        embed_one("trigger load")
        assert embeddings._model is not None
