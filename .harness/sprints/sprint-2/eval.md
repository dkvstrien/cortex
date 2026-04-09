# Sprint 2 Evaluation

**Feature:** Curated layer: remember and FTS5 search
**Verdict:** PASS

## Criteria Results

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | remember('Dan prefers SQLite over Postgres', type='preference', source='manual') returns an integer ID | PASS | Interactive test returned `1` (type=int). Test `test_returns_integer_id` also passes. |
| 2 | recall_curated('database preference') returns the stored memory with a rank score | PASS | Returned 1 result with content "Dan prefers SQLite over Postgres" and rank=-1e-06 (float). |
| 3 | recall_curated with type filter only returns memories of that type | PASS | Inserted both 'preference' and 'fact' memories; filtered query returned only the preference. Test `test_type_filter` confirms. |
| 4 | recall_curated with limit=1 returns exactly 1 result | PASS | Inserted 5 memories, query with limit=1 returned exactly 1. Test `test_limit` confirms. |
| 5 | Soft-deleted memories (deleted_at set) do not appear in recall results | PASS | Set deleted_at on a memory, recall returned 0 results. Test `test_soft_deleted_excluded` confirms. |
| 6 | FTS5 search handles partial word matches via prefix queries | PASS | Query "infra" matched "Infrastructure management is important". Implementation expands each term with `*` suffix. Test `test_prefix_matching` confirms. |
| 7 | Results are returned as dicts with keys: id, content, type, source, tags, confidence, rank, created_at | PASS | Verified exact key set matches. Tags returned as list (deserialized from JSON). Test `test_result_dict_keys` confirms. |

## Testing Done

- Ran `pytest tests/test_curated.py -v`: 17/17 tests passed in 0.04s
- Ran interactive Python script exercising all 7 acceptance criteria against a temp DB: all passed
- Verified FTS5 triggers keep index in sync (insert trigger populates fts, update/delete triggers clean up)
- Verified superseded memories are excluded (subquery filters out memories pointed to by `supersedes_id`)
- Verified type CHECK constraint rejects invalid types (test_invalid_type_raises)

## Issues Found

- None. Implementation is clean and well-structured.
