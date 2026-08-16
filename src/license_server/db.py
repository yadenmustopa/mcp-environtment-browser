"""SQLite database + repository functions untuk license server (Phase 2).

Atomicity:
- Per-tab counter pakai BEGIN IMMEDIATE transaction (per refactor/20_license_server.md
  line 92-94) — equivalent SQL dengan SELECT ... FOR UPDATE.
- Phase 1 SQLite cukup (AGENTS.md §3 default).

Schema (per refactor/20_license_server.md §Database Schema lines 137-167):
- users table: id, email, api_key (unique), plan, tabs_quota, tabs_used,
  created_at, expires_at, is_active
- tab_events table: id, user_id, tabs, source, created_at
- alembic_version: migration tracking (Phase 2 pakai raw SQL, alembic is Phase 3+)
"""

from __future__ import annotations

import secrets
import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Default plan config (Phase 1 — K3 dev/free tier only)
DEFAULT_PLAN = "dev"
DEFAULT_TABS_QUOTA = 10000  # per K3 + 20_license_server.md line 121
DEFAULT_EXPIRES_IN_DAYS = 365


@dataclass
class User:
    """In-memory representation of a users row."""

    id: int
    email: str
    api_key: str
    plan: str
    tabs_quota: int
    tabs_used: int
    created_at: datetime
    expires_at: datetime
    is_active: bool

    @property
    def is_valid(self) -> bool:
        """Validate: active + not expired."""
        return self.is_active and self.expires_at > datetime.now(timezone.utc)


def init_db(db_path: Path) -> None:
    """Initialize SQLite schema (idempotent).

    Per refactor/20_license_server.md lines 137-167.
    Uses CREATE TABLE IF NOT EXISTS so safe to call multiple times.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    api_key TEXT UNIQUE NOT NULL,
    plan TEXT NOT NULL DEFAULT 'dev',
    tabs_quota INTEGER NOT NULL DEFAULT 10000,
    tabs_used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_users_api_key ON users(api_key);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS tab_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    tabs INTEGER NOT NULL,
    source TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_tab_events_user_id_created
    ON tab_events(user_id, created_at);
"""


def generate_api_key() -> str:
    """Generate 256-bit hex API key (per 20_license_server.md line 240 `secrets.token_hex(32)`)."""
    return secrets.token_hex(32)


def _row_to_user(row: sqlite3.Row) -> User:
    """Convert sqlite row → User dataclass."""
    return User(
        id=row["id"],
        email=row["email"],
        api_key=row["api_key"],
        plan=row["plan"],
        tabs_quota=row["tabs_quota"],
        tabs_used=row["tabs_used"],
        created_at=datetime.fromisoformat(row["created_at"]),
        expires_at=datetime.fromisoformat(row["expires_at"]),
        is_active=bool(row["is_active"]),
    )


class LicenseRepository:
    """Repository over users + tab_events tables.

    Thread-safe via per-connection lock. SQLite connection is NOT shared
    across threads (per Python docs — sharing causes 'SQLite objects created
    in a thread can only be used in that same thread').

    For FastAPI multi-worker support, switch to file-based SQLite with
    busy_timeout. Phase 1 single-worker assumed (per knowledge.md §5).
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        if not db_path.exists():
            init_db(db_path)

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a new SQLite connection with row factory + busy timeout."""
        conn: sqlite3.Connection = sqlite3.connect(str(self._db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def get_user_by_api_key(self, api_key: str) -> User | None:
        """Lookup user (returns None if not found).

        Returns: User dataclass including is_active flag, expiry etc.
        """
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE api_key = ?", (api_key,)).fetchone()
            return _row_to_user(row) if row else None

    def register_user(
        self,
        email: str,
        plan: str = DEFAULT_PLAN,
        tabs_quota: int = DEFAULT_TABS_QUOTA,
        expires_in_days: int = DEFAULT_EXPIRES_IN_DAYS,
    ) -> User:
        """Register a new user. Returns the created User with freshly generated api_key.

        Per refactor/20_license_server.md §POST /license/register lines 116-129.
        """
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=expires_in_days)
        api_key = generate_api_key()

        with self._lock, self._conn() as conn:
            try:
                cur: sqlite3.Cursor = conn.execute(
                    """INSERT INTO users (
                        email, api_key, plan, tabs_quota, tabs_used,
                        created_at, expires_at, is_active
                    ) VALUES (?, ?, ?, ?, 0, ?, ?, 1)""",
                    (
                        email,
                        api_key,
                        plan,
                        tabs_quota,
                        now.isoformat(),
                        expires.isoformat(),
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError as e:
                # UNIQUE constraint on email violated
                raise ValueError(f"email already registered: {email}") from e

            user_id = cur.lastrowid
            assert user_id is not None, "INSERT should always return lastrowid"
            # Fetch the newly-created row
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            assert row is not None  # just inserted
            return _row_to_user(row)

    def increment_tab_counter(
        self,
        user_id: int,
        amount: int = 1,
        source: str | None = None,
    ) -> tuple[bool, int, int]:
        """Atomic counter increment via BEGIN IMMEDIATE.

        Per refactor/20_license_server.md line 92-94 atomic guarantee:
        - BEGIN IMMEDIATE acquires write lock immediately
        - SELECT tabs_used → check against tabs_quota → UPDATE OR ROLLBACK
        - Returns (success, tabs_used_after, tabs_quota)

        Returns:
            (success, tabs_used, tabs_quota)
            On quota exceeded: success=False, tabs_used remains unchanged.
        """
        if amount < 0:
            raise ValueError("amount must be non-negative")
        if amount == 0:
            # Idempotent no-op
            with self._lock, self._conn() as conn:
                row = conn.execute(
                    "SELECT tabs_used, tabs_quota FROM users WHERE id = ?", (user_id,)
                ).fetchone()
                assert row is not None
                return (True, row["tabs_used"], row["tabs_quota"])

        now = datetime.now(timezone.utc).isoformat()

        with self._lock, self._conn() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT tabs_used, tabs_quota FROM users WHERE id = ?", (user_id,)
                ).fetchone()
                if row is None:
                    conn.execute("ROLLBACK")
                    raise ValueError(f"user_id {user_id} not found")

                current = row["tabs_used"]
                quota = row["tabs_quota"]
                new_total = current + amount

                if new_total > quota:
                    conn.execute("ROLLBACK")
                    return (False, current, quota)

                conn.execute(
                    "UPDATE users SET tabs_used = ? WHERE id = ?",
                    (new_total, user_id),
                )
                conn.execute(
                    """INSERT INTO tab_events (user_id, tabs, source, created_at)
                       VALUES (?, ?, ?, ?)""",
                    (user_id, amount, source, now),
                )
                conn.commit()
                return (True, new_total, quota)
            except sqlite3.Error:
                # SQL errors only — try ROLLBACK to release write lock;
                # if no active tx (e.g. we just rolled back + raised ValueError),
                # OperationalError is harmless.
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.OperationalError:
                    pass
                raise
            # Note: ValueError propagates without rollback attempts
            # (we already rolled back before raising)
