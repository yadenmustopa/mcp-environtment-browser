"""Unit tests untuk license_server.db — LicenseRepository + init_db + counter.

Per PLAN_PHASES.md §3.2 + AGENTS.md §3 default testing tooling (pytest).
Tests pakai tmp_path fixture (pytest standard).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from license_server.db import (
    DEFAULT_PLAN,
    DEFAULT_TABS_QUOTA,
    LicenseRepository,
    generate_api_key,
    init_db,
)


@pytest.fixture
def repo(tmp_path: Path) -> LicenseRepository:
    """Create LicenseRepository backed by tmp SQLite file."""
    db_path = tmp_path / "test_license.sqlite3"
    return LicenseRepository(db_path)


class TestInitDb:
    """init_db() creates schema on fresh DB."""

    def test_init_db_creates_users_table(self, tmp_path: Path) -> None:
        db_path = tmp_path / "fresh.sqlite3"
        init_db(db_path)
        assert db_path.exists()
        # Validate schema by querying sqlite_master
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        conn.close()
        table_names = {r["name"] for r in rows}
        assert "users" in table_names
        assert "tab_events" in table_names

    def test_init_db_is_idempotent(self, tmp_path: Path) -> None:
        """Calling init twice should not raise or duplicate schema."""
        db_path = tmp_path / "idem.sqlite3"
        init_db(db_path)
        init_db(db_path)  # should not raise
        assert db_path.exists()

    def test_repository_constructor_init_if_missing(self, tmp_path: Path) -> None:
        """LicenseRepository auto-inits DB if file doesn't exist."""
        db_path = tmp_path / "auto.sqlite3"
        assert not db_path.exists()
        LicenseRepository(db_path)
        assert db_path.exists()


class TestGenerateApiKey:
    """API key generation."""

    def test_generate_api_key_length(self) -> None:
        key = generate_api_key()
        # 32 bytes hex = 64 chars (per 20_license_server.md line 240)
        assert len(key) == 64

    def test_generate_api_key_uniqueness(self) -> None:
        keys = {generate_api_key() for _ in range(100)}
        assert len(keys) == 100, "all 100 generated keys must be unique"


class TestUserRegistration:
    """User registration via repository."""

    def test_register_user_returns_user_with_key(self, repo: LicenseRepository) -> None:
        user = repo.register_user("alice@example.com")
        assert user.id > 0
        assert user.email == "alice@example.com"
        assert user.plan == DEFAULT_PLAN
        assert user.tabs_quota == DEFAULT_TABS_QUOTA
        assert user.tabs_used == 0
        assert user.is_active is True
        assert len(user.api_key) == 64

    def test_register_user_duplicate_email_raises(self, repo: LicenseRepository) -> None:
        repo.register_user("dup@example.com")
        with pytest.raises(ValueError, match="already registered"):
            repo.register_user("dup@example.com")

    def test_register_user_custom_quota_and_plan(self, repo: LicenseRepository) -> None:
        user = repo.register_user(
            "bob@example.com",
            plan="pro",
            tabs_quota=50000,
            expires_in_days=730,
        )
        assert user.plan == "pro"
        assert user.tabs_quota == 50000
        assert user.expires_at > datetime.now(timezone.utc) + timedelta(days=700)


class TestGetUserByApiKey:
    """Lookup + user validity flag."""

    def test_get_user_existing_returns_user(self, repo: LicenseRepository) -> None:
        user = repo.register_user("lookup@example.com")
        found = repo.get_user_by_api_key(user.api_key)
        assert found is not None
        assert found.id == user.id
        assert found.email == "lookup@example.com"

    def test_get_user_missing_returns_none(self, repo: LicenseRepository) -> None:
        assert repo.get_user_by_api_key("0" * 64) is None

    def test_is_valid_checks_active_and_expiry(self, repo: LicenseRepository) -> None:
        user = repo.register_user(
            "expired@example.com", expires_in_days=-1
        )
        found = repo.get_user_by_api_key(user.api_key)
        assert found is not None
        # expires_in_days=-1 means past expiration
        assert found.is_valid is False


class TestIncrementTabCounter:
    """Atomic counter via BEGIN IMMEDIATE (per refactor/20_license_server.md line 92-94)."""

    def test_increment_basic(self, repo: LicenseRepository) -> None:
        user = repo.register_user("counter1@example.com", tabs_quota=100)
        ok, used, quota = repo.increment_tab_counter(user.id, amount=1)
        assert ok is True
        assert used == 1
        assert quota == 100

    def test_increment_amount_greater_than_one(self, repo: LicenseRepository) -> None:
        user = repo.register_user("counter2@example.com", tabs_quota=100)
        ok, used, _ = repo.increment_tab_counter(user.id, amount=10)
        assert ok is True and used == 10

    def test_increment_atomic_quota_check(self, repo: LicenseRepository) -> None:
        """Must NOT exceed quota even on exact match + 1."""
        user = repo.register_user("quota@example.com", tabs_quota=5)
        for _ in range(5):
            ok, _, _ = repo.increment_tab_counter(user.id, amount=1)
            assert ok is True
        # 6th exceeds
        ok, used, quota = repo.increment_tab_counter(user.id, amount=1)
        assert ok is False
        assert used == 5  # unchanged
        assert quota == 5

    def test_increment_negative_amount_raises(self, repo: LicenseRepository) -> None:
        user = repo.register_user("neg@example.com")
        with pytest.raises(ValueError, match="non-negative"):
            repo.increment_tab_counter(user.id, amount=-1)

    def test_increment_zero_amount_idempotent(self, repo: LicenseRepository) -> None:
        user = repo.register_user("zero@example.com", tabs_quota=10)
        ok, used, _ = repo.increment_tab_counter(user.id, amount=0)
        assert ok is True
        assert used == 0

    def test_increment_unknown_user_raises(self, repo: LicenseRepository) -> None:
        with pytest.raises(ValueError, match="not found"):
            repo.increment_tab_counter(user_id=99999, amount=1)

    def test_concurrent_increments_atomic(self, repo: LicenseRepository) -> None:
        """Multi-threaded increment should be atomic (no lost updates)."""
        import threading

        user = repo.register_user("race@example.com", tabs_quota=10000)
        N_THREADS = 20
        INCR_PER_THREAD = 50

        errors: list[str] = []

        def worker() -> None:
            for _ in range(INCR_PER_THREAD):
                ok, _, _ = repo.increment_tab_counter(user.id, amount=1)
                if not ok:
                    errors.append("increment failed")

        threads = [threading.Thread(target=worker) for _ in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, errors[0]
        # Verify: 20 * 50 = 1000
        found = repo.get_user_by_api_key(user.api_key)
        assert found is not None
        assert found.tabs_used == N_THREADS * INCR_PER_THREAD, (
            f"expected {N_THREADS * INCR_PER_THREAD}, got {found.tabs_used}"
        )
