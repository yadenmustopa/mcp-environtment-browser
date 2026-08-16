"""SecretStorageBackend — Linux libsecret adapter via python-secretstorage.

Per refactor/30_client_arch.md line 57-112 + knowledge.md §2.
"""

from __future__ import annotations

import json
import logging

from . import VaultBackend

logger = logging.getLogger(__name__)


class SecretStorageBackend(VaultBackend):
    """libsecret adapter. OS handles encryption + access control.

    Each credential stored as Item with:
    - Label: `{key}` (e.g., "tiktok_user_alice")
    - Attributes: {"app": "mcp-env-browser", "key": "{key}", "type": "{type}"}
    - Secret: JSON-encoded value bytes (libsecret encrypts at OS level)
    """

    APP_NAME = "mcp-env-browser"

    def __init__(self) -> None:
        # Imported lazily to avoid DBus errors at import time (Phase 1 robustness)
        import secretstorage

        self._conn = secretstorage.dbus_init()
        collection = secretstorage.get_default_collection(self._conn)
        if collection.is_locked():
            collection.unlock()
        self._collection = collection

    def set(self, key: str, value: bytes, attributes: dict[str, str]) -> None:
        """Create or update credential."""
        attrs = {"app": self.APP_NAME, "key": key, **attributes}

        # Coerce value to bytes
        if isinstance(value, bytes):
            secret_bytes = value
        elif isinstance(value, (dict, list)):
            secret_bytes = json.dumps(value).encode("utf-8")
        else:
            secret_bytes = str(value).encode("utf-8")

        # libsecret's Python API: look up existing items by attrs, update or create
        existing = list(self._collection.search_items(attrs))
        if existing:
            existing[0].set_secret(secret_bytes)
        else:
            self._collection.create_item(
                label=key,
                attributes=attrs,
                secret=secret_bytes,
                replace=True,
            )

    def get(self, key: str) -> bytes | None:
        attrs = {"app": self.APP_NAME, "key": key}
        for item in self._collection.search_items(attrs):
            return bytes(item.get_secret())
        return None

    def delete(self, key: str) -> None:
        attrs = {"app": self.APP_NAME, "key": key}
        for item in self._collection.search_items(attrs):
            item.delete()
            return

    def list_keys(self, filter_text: str | None = None) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        for item in self._collection.search_items({"app": self.APP_NAME}):
            attrs = item.get_attributes()
            key = attrs.get("key", "")
            if filter_text and filter_text not in key:
                continue
            results.append(
                {
                    "key": key,
                    "type": attrs.get("type", ""),
                    "summary": attrs.get("summary", "***"),
                }
            )
        return results

    def is_unlocked(self) -> bool:
        return not self._collection.is_locked()

    def backend_name(self) -> str:
        return "secretstorage"
