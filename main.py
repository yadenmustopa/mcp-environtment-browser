"""ASGI entry point — exposes mcp_env_browser.monitor:app as `app`.

Allows `uvicorn main:app` and `hermes verify` to launch the FastAPI app
from a conventional `main.py` location.

Per spec §6.6 + refactor/45_monitoring.md: monitoring UI on localhost:9876.
Real deployment wires this via `mcp-env-browser serve` (CLI) which also runs
MCP stdio in same process.
"""

from mcp_env_browser.monitor import app  # noqa: F401

__all__ = ["app"]
