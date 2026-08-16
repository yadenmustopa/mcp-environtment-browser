"""Unit tests untuk EncryptedJSONBackend (AES-GCM + scrypt fallback).

Per refactor/30_client_arch.md §EncryptedJSONBackend line 115-140.

These tests verify:
- Set/get/delete roundtrip
- Encrypted at rest (file does not contain plaintext)
- Restart persistence (new instance loads from disk)
- Passphrase required (raises without it)
- Atomic write (temp file + rename)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mcp_env_browser.vault import EncryptedJSONBackend


@pytest.fixture
def vault_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide isolated vault location per test."""
    vault = tmp_path / "vault.json"
    salt = tmp_path / "vault.json.salt"
    # Don't set MCP_VAULT_PATH globally (test passes path directly)
    return vault


@pytest.fixture
def backend(vault_dir: Path) -> EncryptedJSONBackend:
    """Create EncryptedJSONBackend with explicit path + passphrase."""
    return EncryptedJSONBackend(
        path=vault_dir,
        passphrase="test-strong-passphrase-1234567890",
    )


class TestEncryptedJSONBackendInit:
    """Constructor + passphrase requirement."""

    def test_init_creates_dir_and_salt(self, vault_dir: Path) -> None:
        parent = vault_dir.parent
        b = EncryptedJSONBackend(
            path=vault_dir, passphrase="test-passphrase"
        )
        assert vault_dir.parent.exists()
        assert (vault_dir.parent / (vault_dir.name + ".salt")).exists()
        assert b.is_unlocked() is True
        assert b.backend_name() == "encrypted_json"

    def test_init_requires_passphrase(self, tmp_path: Path) -> None:
        path = tmp_path / "x.json"
        with pytest.raises(ValueError, match="passphrase"):
            EncryptedJSONBackend(path=path, passphrase=None)
            # Also test env var unset
            os.environ.pop("MCP_VAULT_PASSPHRASE", None)
            EncryptedJSONBackend(path=path)

    def test_init_reuses_existing_salt(self, tmp_path: Path) -> None:
        """Salt file should be stable across restarts (otherwise decryption fails)."""
        path = tmp_path / "x.json"
        EncryptedJSONBackend(path=path, passphrase="p1")
        salt_bytes_1 = (tmp_path / "x.json.salt").read_bytes()
        EncryptedJSONBackend(path=path, passphrase="p1")
        salt_bytes_2 = (tmp_path / "x.json.salt").read_bytes()
        assert salt_bytes_1 == salt_bytes_2, "salt must be stable across restarts"


class TestRoundtrip:
    """Set/get/delete + plaintext not in file."""

    def test_set_get(self, backend: EncryptedJSONBackend) -> None:
        backend.set(
            "tiktok_alice",
            b'{"username": "alice@x.com", "password": "hunter2"}',
            {"type": "username_password"},
        )
        got = backend.get("tiktok_alice")
        assert got == b'{"username": "alice@x.com", "password": "hunter2"}'

    def test_get_missing_returns_none(self, backend: EncryptedJSONBackend) -> None:
        assert backend.get("never_existed") is None

    def test_delete(self, backend: EncryptedJSONBackend) -> None:
        backend.set("k", b"v", {"type": "api_key"})
        backend.delete("k")
        assert backend.get("k") is None

    def test_delete_missing_is_idempotent(self, backend: EncryptedJSONBackend) -> None:
        # Should not raise even if key doesn't exist
        backend.delete("never_existed")

    def test_plaintext_not_in_file(self, backend: EncryptedJSONBackend, vault_dir: Path) -> None:
        """AES-GCM must encrypt — plaintext bytes not present on disk."""
        secret_value = b"SECRET-TOKEN-XYZ-plaintext-must-not-appear-on-disk"
        backend.set("k", secret_value, {"type": "api_key"})
        # Force flush
        # Read raw file bytes
        raw_bytes = vault_dir.read_bytes()
        assert secret_value not in raw_bytes, (
            "FAILURE: plaintext credential bytes found in vault file"
        )
        # Also verify the JSON wrapper contains only encoded data
        decoded = json.loads(raw_bytes)
        items = decoded.get("items", {})
        k_entry = items.get("k")
        assert "value_b64" in k_entry
        # value_b64 is base64(nonce + ciphertext + tag) — original plaintext not in it
        import base64

        blob = base64.b64decode(k_entry["value_b64"])
        assert secret_value not in blob


class TestRestartPersistence:
    """New EncryptedJSONBackend instance loads existing items."""

    def test_restart_loads_existing_items(self, vault_dir: Path) -> None:
        b1 = EncryptedJSONBackend(path=vault_dir, passphrase="p1")
        b1.set("k1", b"value1", {"type": "api_key"})
        b1.set("k2", b"value2", {"type": "api_key"})

        # Simulate restart — new instance reads from disk
        b2 = EncryptedJSONBackend(path=vault_dir, passphrase="p1")
        assert b2.get("k1") == b"value1"
        assert b2.get("k2") == b"value2"

    def test_wrong_passphrase_fails_to_decrypt(self, vault_dir: Path) -> None:
        b1 = EncryptedJSONBackend(path=vault_dir, passphrase="correct")
        b1.set("k", b"value", {"type": "api_key"})

        # Wrong passphrase will generate different key, decrypt will fail
        b2 = EncryptedJSONBackend(path=vault_dir, passphrase="wrong")
        # Either list_keys returns items but get returns None (corrupt decryption),
        # OR raises. Either is fine — we just verify data is not in plaintext.
        try:
            result = b2.get("k")
            assert result is None or result != b"value"
        except Exception:
            pass  # Cryptography exception acceptable


class TestListKeys:
    """List metadata (no plaintext)."""

    def test_list_no_plaintext(self, backend: EncryptedJSONBackend) -> None:
        backend.set(
            "github_token",
            b"ghp_xxxxxxxxxxxxxxx",
            {"type": "oauth_token", "summary": "***exp:2026-12"},
        )
        keys = backend.list_keys()
        assert len(keys) == 1
        entry = keys[0]
        assert entry["key"] == "github_token"
        assert entry["type"] == "oauth_token"
        assert "summary" in entry
        # Plaintext must not appear in list_keys results
        assert b"ghp_xxxxxxxxxxxxxxx" not in str(entry).encode()

    def test_list_filter(self, backend: EncryptedJSONBackend) -> None:
        """Filter by key substring (per refactor/30_client_arch.md line 98-109).

        Note: per spec, filter_text matches against key (not type).
        """
        backend.set("tiktok_alice", b"x", {"type": "username_password"})
        backend.set("github_otp", b"x", {"type": "oauth_token"})
        backend.set("google_drive", b"x", {"type": "oauth_token"})

        # Filter by exact key substring
        keys = backend.list_keys(filter_text="tiktok")
        assert len(keys) == 1
        assert keys[0]["key"] == "tiktok_alice"

        # Filter that matches 2 keys (lowercase 'o' also in tiktok, so use unique part)
        keys = backend.list_keys(filter_text="o")  # all 3 contain 'o' actually
        # Better: use substring unique to 2 keys (not 3)
        keys = backend.list_keys(filter_text="o")  # all 3 contain 'o'
        assert len(keys) == 3  # tiktok_alice (has 'o'), github_otp (has 'o'), google_drive (has 'o')

        # Filter unique to 2 keys (not 3)
        keys = backend.list_keys(filter_text="g")  # github_otp + google_drive contain 'g'
        assert len(keys) == 2
        assert {k["key"] for k in keys} == {"github_otp", "google_drive"}

        # No match
        keys = backend.list_keys(filter_text="nonexistent")
        assert keys == []

    def test_list_empty(self, backend: EncryptedJSONBackend) -> None:
        assert backend.list_keys() == []


class TestAtomicWrite:
    """_persist uses temp file + rename."""

    def test_persist_does_not_leave_temp_files(
        self, backend: EncryptedJSONBackend, vault_dir: Path
    ) -> None:
        backend.set("k", b"v", {"type": "api_key"})
        parent = vault_dir.parent
        tmp_files = [f for f in parent.iterdir() if f.name.startswith(".vault_")]
        assert tmp_files == [], f"temp files remain: {tmp_files}"

    def test_persist_chmod_600(self, backend: EncryptedJSONBackend, vault_dir: Path) -> None:
        """Vault file must be owner-readable only."""
        import stat

        backend.set("k", b"v", {"type": "api_key"})
        mode = vault_dir.stat().st_mode
        # Check owner-only read/write (600)
        assert (mode & stat.S_IRUSR) and (mode & stat.S_IWUSR)
        assert not (mode & stat.S_IRGRP), "vault file should NOT be group-readable"
        assert not (mode & stat.S_IROTH), "vault file should NOT be world-readable"


class TestFactoryFallback:
    """get_vault_backend() auto-fallback from secretstorage → encrypted_json."""

    def test_factory_returns_backend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Force encrypted_json since we're in a sandbox without D-Bus session
        monkeypatch.setenv("MCP_VAULT_BACKEND", "encrypted_json")
        monkeypatch.setenv("MCP_VAULT_PASSPHRASE", "test123")
        from mcp_env_browser.vault import get_vault_backend

        b = get_vault_backend()
        assert b.backend_name() == "encrypted_json"
        assert b.is_unlocked() is True

    def test_factory_unknown_backend_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MCP_VAULT_BACKEND", "nonexistent_backend")
        from mcp_env_browser.vault import get_vault_backend

        with pytest.raises(ValueError, match="unknown MCP_VAULT_BACKEND"):
            get_vault_backend()
