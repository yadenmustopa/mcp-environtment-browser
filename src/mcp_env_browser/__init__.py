"""mcp-env-browser — MCP server untuk credential vault + browser execution broker.

Phase 1 (Strategi A: Local-First + License Server Only).
See docs/spec/01_phase1_local_first_license_only/spec.md untuk context lengkap.
"""

__version__ = "0.1.0"
__spec_slug__ = "01_phase1_local_first_license_only"

# Phase 1 constants — added per-phase
DEFAULT_LICENSE_SERVER_URL = "http://localhost:8765"
DEFAULT_MONITOR_HOST = "127.0.0.1"
DEFAULT_MONITOR_PORT = 9876
DEFAULT_CONFIG_DIR = "$HOME/.config/mcp-env-browser"  # noqa: S105 — env var shell placeholder
