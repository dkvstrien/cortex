# Sprint 3 Goal

**Feature:** Embedding engine with fastembed
**ID:** 3

## Acceptance Criteria
- embed_one('hello world') returns a list of 384 floats
- embed_batch(['a', 'b', 'c']) returns 3 vectors, each 384 floats
- Round-tripping through serialize/deserialize produces identical vectors
- Model is NOT loaded until the first embed call (lazy init)
- No PyTorch in dependencies — only fastembed + onnxruntime

## Approach
Created src/cortex/embeddings.py with a lazy-loaded fastembed TextEmbedding model (BAAI/bge-small-en-v1.5). The module exposes embed_one and embed_batch for generating 384-dim vectors, plus serialize/deserialize helpers using struct.pack for SQLite BLOB storage. Added fastembed to pyproject.toml dependencies.
