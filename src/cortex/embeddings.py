"""Embedding engine wrapping fastembed with bge-small-en-v1.5.

Provides lazy-loaded embedding functions and serialize/deserialize helpers
for storing vectors as SQLite BLOBs.
"""

from __future__ import annotations

import logging
import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastembed import TextEmbedding

logger = logging.getLogger("cortex")

MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384

# Check fastembed availability at import time
try:
    import fastembed as _fastembed_module  # noqa: F401

    FASTEMBED_AVAILABLE = True
except ImportError:
    FASTEMBED_AVAILABLE = False
    logger.warning("fastembed not available — embedding and vector search will be disabled")

_model: TextEmbedding | None = None


def _get_model() -> TextEmbedding:
    """Return the shared TextEmbedding model, initializing on first call.

    Raises RuntimeError if fastembed is not installed.
    """
    if not FASTEMBED_AVAILABLE:
        raise RuntimeError(
            "fastembed is not installed. Install it with: pip install fastembed"
        )
    global _model
    if _model is None:
        from fastembed import TextEmbedding

        _model = TextEmbedding(model_name=MODEL_NAME)
    return _model


def embed_one(text: str) -> list[float]:
    """Embed a single text string, returning a list of 384 floats.

    Raises RuntimeError if fastembed is not installed.
    """
    model = _get_model()
    # fastembed returns a generator; take the first (only) result
    embeddings = list(model.embed([text]))
    return embeddings[0].tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed multiple texts, returning a list of float vectors.

    Raises RuntimeError if fastembed is not installed.
    """
    model = _get_model()
    embeddings = list(model.embed(texts))
    return [e.tolist() for e in embeddings]


def serialize(vector: list[float]) -> bytes:
    """Pack a float vector into bytes for SQLite BLOB storage.

    Uses little-endian float32, prefixed with dimension count.
    """
    return struct.pack(f"<I{len(vector)}f", len(vector), *vector)


def deserialize(blob: bytes) -> list[float]:
    """Unpack bytes back into a float vector."""
    (dim,) = struct.unpack_from("<I", blob, 0)
    return list(struct.unpack_from(f"<{dim}f", blob, 4))


def serialize_vec(vector: list[float]) -> bytes:
    """Pack a float vector into raw float32 bytes for sqlite-vec.

    Unlike serialize(), this does NOT include a dimension prefix — sqlite-vec
    expects raw little-endian float32 data.
    """
    return struct.pack(f"<{len(vector)}f", *vector)
