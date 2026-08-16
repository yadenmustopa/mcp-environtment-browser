"""EncryptedJSONBackend — AES-GCM + scrypt KDF fallback (Phase 1 dev).

Per refactor/30_client_arch.md line 115-140 + knowledge.md §2 headless use case.
Triggered when:
- libsecret unavailable (e.g., SSH tanpa D-Bus session bus)
- MCP_VAULT_BACKEND=encrypted_json (forced)
- Auto fallback in factory
"""

from __future__ import annotations

import base64
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from . import VaultBackend

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path("~/.local/share/mcp-env-browser/vault.json")
SALT_FILE_SUFFIX = ".salt"
NONCE_SIZE = 12  # AES-GCM standard
DKLEN = 32  # AES-256


class EncryptedJSONBackend(VaultBackend):
    """File-based encrypted credential vault.

    File format:
    ```json
    {
      "version": 1,
      "salt_b64": "<base64>",
      "items": {
        "<key>": {
          "value_b64": "<base64 of nonce+ciphertext+tag>",
          "attributes": {"type": "username_password", ...}
        }
      }
    }
    ```

    KDF: scrypt(passphrase, salt, n=2^14, r=8, p=1) -> 32-byte key
    Cipher: AES-256-GCM with random 12-byte nonce per item
    """

    def __init__(
        self,
        path: Path | None = None,
        passphrase: str | None = None,
    ) -> None:
        env_path = os.environ.get("MCP_VAULT_PATH")
        self._path = (Path(env_path) if env_path else (path or DEFAULT_PATH)).expanduser()

        passphrase = passphrase or os.environ.get("MCP_VAULT_PASSPHRASE")
        if not passphrase:
            raise ValueError(
                "EncryptedJSONBackend requires passphrase via "
                "MCP_VAULT_PASSPHRASE env var or constructor arg. "
                "See refactor/30_client_arch.md §EncryptedJSONBackend."
            )
        self._passphrase = passphrase.encode("utf-8")

        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._salt_path = self._path.with_suffix(self._path.suffix + SALT_FILE_SUFFIX)

        if self._salt_path.exists():
            salt = self._salt_path.read_bytes()
        else:
            salt = os.urandom(16)
            self._salt_path.write_bytes(salt)

        # Derive key via scrypt (per refactor/30_client_arch.md line 127)
        kdf = Scrypt(salt=salt, length=DKLEN, n=2**14, r=8, p=1)
        self._key = kdf.derive(self._passphrase)

        # Lazy-load existing vault
        self._items: dict[str, dict[str, Any]] = {}
        if self._path.exists():
            try:
                self._items = self._load()
            except Exception as e:
                logger.warning("vault file present but failed to load: %s", e)

    def set(self, key: str, value: bytes, attributes: dict[str, str]) -> None:
        """Encrypt and persist credential."""
        aesgcm = AESGCM(self._key)
        nonce = os.urandom(NONCE_SIZE)
        # AES-GCM appends 16-byte tag automatically
        ct = aesgcm.encrypt(nonce, value, None)
        # Encode as nonce+ct (tag at end of ct)
        import base64

        encoded = base64.b64encode(nonce + ct).decode("ascii")
        self._items[key] = {
            "value_b64": encoded,
            "attributes": dict(attributes),
        }
        self._persist()

    def get(self, key: str) -> bytes | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        encoded = entry.get("value_b64")
        if not isinstance(encoded, str):
            return None
        blob = base64.b64decode(encoded)
        nonce, ct = blob[:NONCE_SIZE], blob[NONCE_SIZE:]
        aesgcm = AESGCM(self._key)
        return aesgcm.decrypt(nonce, ct, None)

    def delete(self, key: str) -> None:
        self._items.pop(key, None)
        self._persist()

    def list_keys(self, filter_text: str | None = None) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        for key, entry in self._items.items():
            if filter_text and filter_text not in key:
                continue
            attrs = entry.get("attributes", {}) or {}
            results.append(
                {
                    "key": key,
                    "type": attrs.get("type", ""),
                    "summary": attrs.get("summary", "***"),
                }
            )
        return results

    def is_unlocked(self) -> bool:
        """Always 'unlocked' once passphrase derived; libsecret semantics analog."""
        return True

    def backend_name(self) -> str:
        return "encrypted_json"

    # --- internal ---
    def _persist(self) -> None:
        """Atomic write: temp file + rename."""

        payload = {"version": 1, "items": self._items}
        fd, tmp_path = tempfile.mkstemp(dir=str(self._path.parent), prefix=".vault_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f)
            os.replace(tmp_path, self._path)
            # chmod 600 per security (file has credential blobs)
            self._path.chmod(0o600)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _load(self) -> dict[str, dict[str, Any]]:
        with open(self._path) as f:
            raw_payload: object = json.load(f)
        if not isinstance(raw_payload, dict):
            return {}
        payload: dict[str, Any] = raw_payload
        items_obj: object = payload.get("items", {})
        if not isinstance(items_obj, dict):
            return {}
        items: dict[str, Any] = items_obj
        result: dict[str, dict[str, Any]] = {}
        for key, value in items.items():
            if isinstance(value, dict):
                result[str(key)] = value
        return result
