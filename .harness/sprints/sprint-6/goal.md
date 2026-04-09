# Sprint 6 Goal

**Feature:** Forget and supersede operations
**ID:** 6

## Acceptance Criteria
- forget(id) sets deleted_at and memory no longer appears in recall results
- forget does NOT physically delete the row
- supersede(old_id, 'new fact') creates a new memory and soft-deletes the old one
- The new memory's supersedes_id points to old_id
- get_history(new_id) returns the full supersession chain including the old memory
- Attempting to forget a non-existent ID raises a clear error

## Approach
Added forget(), supersede(), and get_history() to the existing curated.py module. forget() sets deleted_at and removes from FTS5 index. supersede() creates a new memory inheriting type/source/tags from the old one, then forgets the old. get_history() walks the supersedes_id chain backwards to build the full revision history.
