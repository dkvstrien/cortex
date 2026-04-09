# Sprint 12 Goal

**Feature:** MEMORY.md migration ingestion
**ID:** 12

## Acceptance Criteria
- Running on Dan's actual MEMORY.md imports all entries as curated memories
- Project entries get type='entity', User entries get type='preference', Feedback entries get type='procedure', Reference entries get type='fact'
- Source is set to 'memory_md_migration' for all entries
- Idempotent — running twice doesn't create duplicates
- A summary is printed: N memories imported, M skipped (duplicates)

## Approach
Created a migrate module that parses MEMORY.md section headers to determine memory type, extracts entries via regex, optionally reads linked .md files for richer content, and inserts into curated_memories with idempotency checks on source+content. Supports both the original section names (Project/User/Feedback/Reference) and the newer format (Dan/Active Projects/Tools & Environments/Areas).
