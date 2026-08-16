"""CLI entry point — Click subcommands init/serve/version/config/doctor.

Per refactor/10_mcp_server.md §CLI Commands + refactor/40_distribution.md §install.sh + PyInstaller.

Phase 8 implementation. Subcommands:
- init: first-time setup (write config.json + test connection)
- serve: start MCP stdio + monitor.http + BrowserExecutor in single process
- version: print __version__
- config: show/set-server-url/set-api-key/path
- doctor: health check (vault, server, playwright version)

Security:
- init prompts for sensitive data (API key) — use click.prompt with hide_input=True
- config.json chmod 600 after write (POSIX only)

Logging:
- structlog ke stderr + file ~/.local/share/mcp-env-browser/logs/{date}.log
- NEVER print to stdout (breaks MCP protocol per knowledge §4 line 173)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import stat
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import click
import httpx
import structlog

from mcp_env_browser import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_LICENSE_SERVER_URL,
    DEFAULT_MONITOR_HOST,
    DEFAULT_MONITOR_PORT,
    __version__,
)

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(os.path.expanduser(DEFAULT_CONFIG_DIR.replace("$HOME", "")))
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_DIR = Path(os.path.expanduser("~/.local/share/mcp-env-browser/logs"))


# ============================================================================
# structlog setup
# ============================================================================


def setup_logging(level: str = "INFO") -> None:
    """Configure structlog to stderr + log file (per refactor §30 line 335-340).

    NEVER print to stdout — breaks MCP stdio protocol (knowledge §4 line 173).
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log"

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=getattr(logging, level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
    # Also tee to file
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(file_handler)


# ============================================================================
# Click group
# ============================================================================


@click.group()
@click.version_option(version=__version__, prog_name="mcp-env-browser")
def cli() -> None:
    """mcp-env-browser — credential vault + browser execution broker (Phase 1 Strategi A)."""


# ============================================================================
# version
# ============================================================================


@cli.command()
def version() -> None:
    """Print version."""
    click.echo(f"mcp-env-browser {__version__}")


# ============================================================================
# config
# ============================================================================


@cli.group()
def config() -> None:
    """Show/edit config."""


@config.command("show")
def config_show() -> None:
    """Print current config (masked API key)."""
    cfg = load_config_dict()
    if not cfg:
        click.echo("(no config — run `mcp-env-browser init` first)")
        return
    masked = dict(cfg)
    if "license_api_key" in masked:
        key = masked["license_api_key"]
        if len(key) > 4:
            masked["license_api_key"] = "***" + key[-4:]
    click.echo(json.dumps(masked, indent=2))


@config.command("set-server-url")
@click.argument("url")
def config_set_server_url(url: str) -> None:
    """Set license server URL."""
    cfg = load_config_dict()
    cfg["license_server_url"] = url
    save_config_dict(cfg)
    click.echo(f"license_server_url = {url}")


@config.command("set-api-key")
@click.argument("key")
def config_set_api_key(key: str) -> None:
    """Set license API key."""
    cfg = load_config_dict()
    cfg["license_api_key"] = key
    save_config_dict(cfg)
    click.echo(f"license_api_key = ***{key[-4:] if len(key) > 4 else '***'}")


@config.command("path")
def config_path() -> None:
    """Print config file path."""
    click.echo(str(CONFIG_FILE))


# ============================================================================
# init
# ============================================================================


@cli.command()
@click.option(
    "--server-url",
    default=None,
    help="License server URL (default: localhost:8765)",
)
@click.option(
    "--api-key",
    default=None,
    help="License API key (will prompt if not provided)",
)
@click.option(
    "--non-interactive",
    is_flag=True,
    help="Fail if prompts needed (CI mode)",
)
def init(
    server_url: str | None,
    api_key: str | None,
    non_interactive: bool,
) -> None:
    """First-time setup wizard.

    Per refactor/10_mcp_server.md §init (line 25-34):
    1. Check config dir exists
    2. Prompt server URL + API key (or accept flags)
    3. Validate connectivity (POST /health)
    4. Test vault backend (set/get/delete)
    5. Save config.json chmod 600
    """
    setup_logging()

    # 1. Config dir
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # 2. Prompt for missing values
    cfg = load_config_dict()
    if server_url is None:
        server_url = cfg.get("license_server_url") or click.prompt(
            "License server URL",
            default=DEFAULT_LICENSE_SERVER_URL,
        )
    if api_key is None:
        if cfg.get("license_api_key"):
            api_key = cfg["license_api_key"]
        elif non_interactive:
            click.echo("ERROR: --api-key required in non-interactive mode", err=True)
            sys.exit(1)
        else:
            api_key = click.prompt("License API key", hide_input=True)

    cfg["license_server_url"] = server_url
    cfg["license_api_key"] = api_key

    # 3. Validate connectivity
    click.echo(f"Testing connection to {server_url}/health ...")
    try:
        resp = httpx.get(f"{server_url}/health", timeout=2.0)
        if resp.status_code != 200:
            click.echo(f"ERROR: server returned {resp.status_code}", err=True)
            sys.exit(1)
        click.echo("  ✓ health OK")
    except httpx.HTTPError as e:
        click.echo(f"ERROR: connection failed: {e}", err=True)
        click.echo("Continuing — you can fix server URL later with `config set-server-url`")
        if non_interactive:
            sys.exit(1)

    # 4. Test vault backend
    click.echo("Testing vault backend ...")
    try:
        from mcp_env_browser.vault import get_vault_backend

        backend = get_vault_backend()
        test_key = "__mcp_env_browser_init_test__"
        test_value = b"ok"
        backend.set(test_key, test_value, attributes={"type": "test", "app": "mcp-env-browser"})
        if backend.get(test_key) != test_value:
            click.echo("ERROR: vault roundtrip failed", err=True)
            sys.exit(1)
        backend.delete(test_key)
        click.echo(f"  ✓ {backend.backend_name()} OK")
    except Exception as e:
        click.echo(f"WARN: vault test failed: {e}", err=True)
        click.echo("  Continuing — init may need vault backend fix later")

    # 5. Save config
    save_config_dict(cfg)
    click.echo(f"\n✓ Config saved to {CONFIG_FILE} (chmod 600)")
    click.echo("\nNext steps:")
    click.echo("  1. Edit ~/.mcp.json to add mcp-env-browser server")
    click.echo("  2. Restart Hermes Agent")
    click.echo("  3. Verify 13 tools available")


# ============================================================================
# doctor
# ============================================================================


@cli.command()
def doctor() -> None:
    """Health check (vault, server, playwright version)."""
    setup_logging()
    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        symbol = "✓" if ok else "✗"
        click.echo(f"  {symbol} {name}: {detail}")
        if not ok:
            failures += 1

    click.echo("mcp-env-browser doctor:\n")

    # Config
    cfg_path = CONFIG_FILE
    if cfg_path.exists():
        cfg = load_config_dict()
        check("config.json exists", True, str(cfg_path))
        check("license_server_url set", "license_server_url" in cfg, str(cfg.get("license_server_url", "")))
        check("license_api_key set", "license_api_key" in cfg, "***" + cfg.get("license_api_key", "")[-4:] if cfg.get("license_api_key") else "(missing)")
    else:
        check("config.json exists", False, "run `mcp-env-browser init` first")
        sys.exit(1)

    # Server connectivity
    server_url = cfg.get("license_server_url", DEFAULT_LICENSE_SERVER_URL)
    try:
        resp = httpx.get(f"{server_url}/health", timeout=2.0)
        check("license server reachable", resp.status_code == 200, f"{server_url} → {resp.status_code}")
    except Exception as e:  # noqa: BLE001
        check("license server reachable", False, str(e))

    # Vault
    try:
        from mcp_env_browser.vault import get_vault_backend

        backend = get_vault_backend()
        check("vault backend", True, backend.backend_name())
    except Exception as e:
        check("vault backend", False, str(e))

    # Playwright
    try:
        import playwright

        version_str = getattr(playwright, "__version__", "unknown")
        check("playwright installed", True, f"v{version_str}")
    except ImportError:
        check("playwright installed", False, "pip install playwright")

    # Chromium binary
    chromium_path = None
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            chromium_path = p.chromium.executable_path
    except Exception as e:  # noqa: BLE001
        check("chromium binary", False, str(e))
    else:
        check("chromium binary", chromium_path is not None and Path(chromium_path).exists(), chromium_path or "")

    # Platform info
    check("platform", True, f"{platform.system()} {platform.release()}")

    click.echo()
    if failures == 0:
        click.echo("All checks passed ✓")
        sys.exit(0)
    else:
        click.echo(f"{failures} check(s) failed")
        sys.exit(1)


# ============================================================================
# serve
# ============================================================================


@cli.command()
@click.option("--no-monitor", is_flag=True, help="Skip web monitoring HTTP server")
@click.option(
    "--monitor-host",
    default=DEFAULT_MONITOR_HOST,
    help="Monitoring UI bind host (default 127.0.0.1)",
)
@click.option(
    "--monitor-port",
    default=DEFAULT_MONITOR_PORT,
    type=int,
    help="Monitoring UI port (default 9876)",
)
def serve(no_monitor: bool, monitor_host: str, monitor_port: int) -> None:
    """Start MCP stdio server (and optionally web monitoring)."""
    setup_logging()
    cfg = load_config_dict()
    log = structlog.get_logger()

    log.info("mcp_env_browser.start", version=__version__, monitor=not no_monitor)

    # Init components
    license_client = _build_license_client(cfg)
    vault = _build_vault()
    browser_executor = _build_browser_executor(license_client, vault, cfg)

    # Run monitor (background) + MCP stdio (foreground) in same asyncio loop
    from mcp_env_browser.mcp_server import run_stdio_server

    if no_monitor:
        # No monitor — just run stdio
        asyncio.run(run_stdio_server(vault, browser_executor, license_client))
        return

    # With monitor: start uvicorn in same loop
    import uvicorn

    from mcp_env_browser import monitor
    from mcp_env_browser.monitor import set_browser_executor

    set_browser_executor(browser_executor)

    config = uvicorn.Config(
        monitor.app,
        host=monitor_host,
        port=monitor_port,
        log_level="warning",
    )
    uvi_server = uvicorn.Server(config)

    async def run_both() -> None:
        monitor_task = asyncio.create_task(uvi_server.serve())
        log.info("monitor.start", url=f"http://{monitor_host}:{monitor_port}")
        try:
            await run_stdio_server(vault, browser_executor, license_client)
        finally:
            monitor_task.cancel()
            try:
                await monitor_task
            except (asyncio.CancelledError, Exception):
                pass

    try:
        asyncio.run(run_both())
    except KeyboardInterrupt:
        log.info("mcp_env_browser.shutdown")
    finally:
        browser_executor.close()


# ============================================================================
# Helpers
# ============================================================================


def load_config_dict() -> dict[str, Any]:
    """Load config from CONFIG_FILE (JSON)."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_config_dict(cfg: dict[str, Any]) -> None:
    """Save config to CONFIG_FILE with chmod 600."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
    # chmod 600 (POSIX)
    if os.name == "posix":
        CONFIG_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _build_license_client(cfg: dict[str, Any]) -> Any:
    """Build LicenseClient from config (Phase 4 already implemented)."""
    from mcp_env_browser.license import LicenseClient

    return LicenseClient(
        base_url=cfg.get("license_server_url"),
        api_key=cfg.get("license_api_key"),
    )


def _build_vault() -> Any:
    """Build VaultBackend via factory (Phase 3)."""
    from mcp_env_browser.vault import get_vault_backend

    return get_vault_backend()


def _build_browser_executor(
    license_client: Any, vault: Any, cfg: dict[str, Any]
) -> Any:
    """Build BrowserExecutor (Phase 5).

    headless flag from config (default False per knowledge §3 line 132-133).
    """
    from mcp_env_browser.browser import BrowserExecutor

    headless = bool(cfg.get("browser_headless", False))
    return BrowserExecutor(license_client=license_client, vault=vault, headless=headless)


# ============================================================================
# Entry point
# ============================================================================

if __name__ == "__main__":
    cli()
