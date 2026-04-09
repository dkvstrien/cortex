"""Tests for cortex.decay: confidence decay, reinforcement, and stale detection."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from cortex.db import init_db
from cortex.curated import remember, recall_curated
from cortex.decay import decay_confidence, reinforce, get_stale


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = init_db(tmp_path / "test.db")
    yield c
    c.close()


def _set_updated_at(conn: sqlite3.Connection, memory_id: int, dt: datetime) -> None:
    """Helper: backdate a memory's updated_at for testing time-based decay."""
    conn.execute(
        "UPDATE curated_memories SET updated_at = ? WHERE id = ?",
        (dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), memory_id),
    )
    conn.commit()


class TestReinforce:
    def test_resets_confidence_to_one(self, conn: sqlite3.Connection):
        mid = remember(conn, "test memory", type="fact")
        # Manually lower confidence
        conn.execute("UPDATE curated_memories SET confidence = 0.3 WHERE id = ?", (mid,))
        conn.commit()

        reinforce(conn, mid)

        row = conn.execute("SELECT confidence FROM curated_memories WHERE id = ?", (mid,)).fetchone()
        assert row[0] == 1.0

    def test_refreshes_updated_at(self, conn: sqlite3.Connection):
        mid = remember(conn, "test memory", type="fact")
        old_time = datetime(2020, 1, 1, tzinfo=timezone.utc)
        _set_updated_at(conn, mid, old_time)

        reinforce(conn, mid)

        row = conn.execute("SELECT updated_at FROM curated_memories WHERE id = ?", (mid,)).fetchone()
        updated = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
        assert updated.year >= 2026


class TestDecayConfidence:
    def test_90_day_half_life(self, conn: sqlite3.Connection):
        mid = remember(conn, "old memory", type="fact")
        past = datetime.now(timezone.utc) - timedelta(days=90)
        _set_updated_at(conn, mid, past)

        decay_confidence(conn, half_life_days=90)

        row = conn.execute("SELECT confidence FROM curated_memories WHERE id = ?", (mid,)).fetchone()
        assert abs(row[0] - 0.5) < 0.05, f"Expected ~0.5, got {row[0]}"

    def test_180_day_decay(self, conn: sqlite3.Connection):
        mid = remember(conn, "very old memory", type="fact")
        past = datetime.now(timezone.utc) - timedelta(days=180)
        _set_updated_at(conn, mid, past)

        decay_confidence(conn, half_life_days=90)

        row = conn.execute("SELECT confidence FROM curated_memories WHERE id = ?", (mid,)).fetchone()
        assert abs(row[0] - 0.25) < 0.05, f"Expected ~0.25, got {row[0]}"

    def test_fresh_memory_unchanged(self, conn: sqlite3.Connection):
        mid = remember(conn, "fresh memory", type="fact")
        # Don't backdate -- it was just created

        decay_confidence(conn)

        row = conn.execute("SELECT confidence FROM curated_memories WHERE id = ?", (mid,)).fetchone()
        # Sub-second elapsed time produces negligible decay
        assert row[0] > 0.999, f"Fresh memory should be ~1.0, got {row[0]}"

    def test_returns_count_of_updated(self, conn: sqlite3.Connection):
        mid1 = remember(conn, "old 1", type="fact")
        mid2 = remember(conn, "old 2", type="fact")
        past = datetime.now(timezone.utc) - timedelta(days=30)
        _set_updated_at(conn, mid1, past)
        _set_updated_at(conn, mid2, past)

        count = decay_confidence(conn)
        # At least the 2 backdated memories are updated; the fresh one may
        # also be touched due to sub-second elapsed time
        assert count >= 2

    def test_deleted_memories_not_decayed(self, conn: sqlite3.Connection):
        mid = remember(conn, "deleted memory", type="fact")
        past = datetime.now(timezone.utc) - timedelta(days=90)
        _set_updated_at(conn, mid, past)
        conn.execute(
            "UPDATE curated_memories SET deleted_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
            (mid,),
        )
        conn.commit()

        count = decay_confidence(conn)
        assert count == 0

    def test_custom_half_life(self, conn: sqlite3.Connection):
        mid = remember(conn, "custom decay", type="fact")
        past = datetime.now(timezone.utc) - timedelta(days=30)
        _set_updated_at(conn, mid, past)

        decay_confidence(conn, half_life_days=30)

        row = conn.execute("SELECT confidence FROM curated_memories WHERE id = ?", (mid,)).fetchone()
        assert abs(row[0] - 0.5) < 0.05


class TestGetStale:
    def test_returns_stale_memories(self, conn: sqlite3.Connection):
        mid = remember(conn, "stale memory", type="fact")
        conn.execute("UPDATE curated_memories SET confidence = 0.05 WHERE id = ?", (mid,))
        conn.commit()

        stale = get_stale(conn)
        assert len(stale) == 1
        assert stale[0]["id"] == mid

    def test_excludes_above_threshold(self, conn: sqlite3.Connection):
        remember(conn, "healthy memory", type="fact")  # confidence=1.0

        stale = get_stale(conn)
        assert len(stale) == 0

    def test_custom_threshold(self, conn: sqlite3.Connection):
        mid = remember(conn, "medium confidence", type="fact")
        conn.execute("UPDATE curated_memories SET confidence = 0.4 WHERE id = ?", (mid,))
        conn.commit()

        stale = get_stale(conn, threshold=0.5)
        assert len(stale) == 1

    def test_excludes_deleted(self, conn: sqlite3.Connection):
        mid = remember(conn, "deleted stale", type="fact")
        conn.execute(
            "UPDATE curated_memories SET confidence = 0.01, "
            "deleted_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
            (mid,),
        )
        conn.commit()

        stale = get_stale(conn)
        assert len(stale) == 0


class TestRecallReinforces:
    def test_recall_resets_confidence(self, conn: sqlite3.Connection):
        mid = remember(conn, "searchable memory about databases", type="fact")
        conn.execute("UPDATE curated_memories SET confidence = 0.3 WHERE id = ?", (mid,))
        conn.commit()

        results = recall_curated(conn, "databases")
        assert len(results) >= 1
        # The returned result should show reinforced confidence
        assert results[0]["confidence"] == 1.0

        # Check in DB too
        row = conn.execute("SELECT confidence FROM curated_memories WHERE id = ?", (mid,)).fetchone()
        assert row[0] == 1.0

    def test_new_memories_start_at_one(self, conn: sqlite3.Connection):
        mid = remember(conn, "brand new memory", type="fact")
        row = conn.execute("SELECT confidence FROM curated_memories WHERE id = ?", (mid,)).fetchone()
        assert row[0] == 1.0


class TestDecayMath:
    """Verify the exponential decay formula at specific time points."""

    def test_300_days_near_threshold(self, conn: sqlite3.Connection):
        """At ~300 days with 90-day half-life, confidence should be ~0.1."""
        mid = remember(conn, "ancient memory", type="fact")
        past = datetime.now(timezone.utc) - timedelta(days=300)
        _set_updated_at(conn, mid, past)

        decay_confidence(conn, half_life_days=90)

        row = conn.execute("SELECT confidence FROM curated_memories WHERE id = ?", (mid,)).fetchone()
        # 0.5^(300/90) = 0.5^3.33 ≈ 0.0992
        assert abs(row[0] - 0.1) < 0.02, f"Expected ~0.1, got {row[0]}"

    def test_45_days_is_sqrt_half(self, conn: sqlite3.Connection):
        """At 45 days (half of half-life), confidence should be ~0.707."""
        mid = remember(conn, "medium age memory", type="fact")
        past = datetime.now(timezone.utc) - timedelta(days=45)
        _set_updated_at(conn, mid, past)

        decay_confidence(conn, half_life_days=90)

        row = conn.execute("SELECT confidence FROM curated_memories WHERE id = ?", (mid,)).fetchone()
        # 0.5^(45/90) = 0.5^0.5 ≈ 0.707
        assert abs(row[0] - 0.707) < 0.02, f"Expected ~0.707, got {row[0]}"
