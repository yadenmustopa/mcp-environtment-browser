"""Vault backend module (Phase 3).

Per refactor/30_client_arch.md §Vault Module + knowledge.md §2 libsecret.

Module structure:
- src/mcp_env_browser/vault/__init__.py   (this file) — Protocol + factory
- src/mcp_env_browser/vault/secretstorage.py — Linux libsecret adapter
- src/mcp_env_browser/vault/encrypted_json.py — AES-GCM fallback (Phase 1 dev)

Lazy import via __getattr__ (PEP 562) — avoid loading libsecret unless we
actually use SecretStorageBackend. EncryptedJSONBackend is also lazy.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .encrypted_json import EncryptedJSONBackend as EncryptedJSONBackend
    from .secretstorage import SecretStorageBackend as SecretStorageBackend

logger = logging.getLogger(__name__)


@runtime_checkable
class VaultBackend(Protocol):
    """Credential vault backend Protocol (per refactor/30_client_arch.md line 17-28).

    Implementations:
    - SecretStorageBackend (Linux libsecret via secretstorage)
    - EncryptedJSONBackend (fallback for headless / no D-Bus)
    """

    def set(self, key: str, value: bytes, attributes: dict[str, str]) -> None:
        """Create or update credential. Value is bytes (OS encrypts at rest)."""
        ...

    def get(self, key: str) -> bytes | None:
        """Retrieve credential bytes. Returns None if not found."""
        ...

    def delete(self, key: str) -> None:
        """Remove credential by key."""
        ...

    def list_keys(self, filter_text: str | None = None) -> list[dict[str, str]]:
        """List credentials matching optional filter. Returns metadata only (no plaintext).

        Each entry: {"key": str, "type": str, "summary": str}
        """
        ...

    def is_unlocked(self) -> bool:
        """Whether backend is currently readable (libsecret may be locked)."""
        ...

    def backend_name(self) -> str:
        """Identifier for diagnostics + factory logging."""
        ...


def __getattr__(name: str) -> Any:
    """PEP 562 lazy module attribute access.

    Usage: `from mcp_env_browser.vault import SecretStorageBackend`
    Triggers __getattr__("SecretStorageBackend") — imported on demand.
    """
    if name == "SecretStorageBackend":
        from . import secretstorage

        return secretstorage.SecretStorageBackend
    if name == "EncryptedJSONBackend":
        from . import encrypted_json

        return encrypted_json.EncryptedJSONBackend
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_vault_backend() -> VaultBackend:
    """Factory: select vault backend based on MCP_VAULT_BACKEND env.

    Per refactor/30_client_arch.md line 31-55 factory spec:
    - 'auto' (default): try libsecret, fallback to encrypted_json
    - 'secretstorage': force libsecret
    - 'encrypted_json': force file-based
    - anything else: ValueError
    """
    pref = os.environ.get("MCP_VAULT_BACKEND", "auto").strip().lower()

    if pref == "secretstorage":
        from .secretstorage import SecretStorageBackend

        return SecretStorageBackend()

    if pref == "encrypted_json":
        from .encrypted_json import EncryptedJSONBackend

        return EncryptedJSONBackend()

    if pref == "auto":
        # Try libsecret first, fallback to encrypted_json
        try:
            from .secretstorage import SecretStorageBackend

            backend: VaultBackend = SecretStorageBackend()
            logger.info("vault: using libsecret backend")
            return backend
        except Exception as e:
            logger.warning(
                "vault: libsecret unavailable (%s), falling back to encrypted_json",
                e,
            )
            from .encrypted_json import EncryptedJSONBackend

            return EncryptedJSONBackend()

    raise ValueError(
        f"unknown MCP_VAULT_BACKEND: {pref!r} (expected: auto | secretstorage | encrypted_json)"
    )
