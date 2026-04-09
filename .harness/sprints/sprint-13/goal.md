# Sprint 13 Goal

**Feature:** End-to-end test suite
**ID:** 13

## Acceptance Criteria
- pytest runs all tests with 0 failures
- Tests cover: remember, recall_curated, recall_raw, recall (unified), forget, supersede, get_history, decay_confidence, status
- At least one test verifies FTS5 search ranks relevant results above irrelevant ones (30+ memories)
- At least one test verifies vector search ranks semantically similar content higher (20+ chunks)
- Tests use temporary databases (no leftover files)
- Confidence decay math is tested: half-life produces expected values
- MCP server can be instantiated without errors in tests

## Approach
Created tests/test_e2e.py with 21 tests across 8 test classes. Each class focuses on a specific end-to-end scenario: FTS5 ranking with 32 memories, vector search ranking with 22 chunks, full remember-supersede-forget pipeline, cross-layer deduplication, decay lifecycle with math verification, status dashboard accuracy, MCP server instantiation, and error handling. All tests use tmp_path fixtures for isolated temporary databases.
