# Sprint 1 Changes

**Feature:** Project scaffolding and SQLite schema

## Files Changed
- `pyproject.toml` — created, project config with setuptools build
- `src/cortex/__init__.py` — created, package init
- `src/cortex/db.py` — created, schema SQL and init_db() function
- `tests/__init__.py` — created, test package init
- `tests/test_db.py` — created, 13 tests covering all schema requirements
- `.gitignore` — created
- `.harness/plan.json` — created with feature 1 in_progress

## Dependencies Added
- pytest>=7.0 (dev dependency)

## Notes
- sqlite-vec virtual table (raw_chunks_vec) deferred to Sprint 4 with TODO comment in db.py
- FTS5 uses content-sync mode with INSERT/UPDATE/DELETE triggers
- Python version requirement lowered to >=3.9 for compatibility with system Python
