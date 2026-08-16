"""Phase 1 CLI skeleton — minimal Click entry point untuk verify entry points PyInstaller-ready.

Phase 8 akan replace ini dengan Click commands penuh (init, serve, version, config, doctor).
See refactor/10_mcp_server.md §CLI Commands + refactor/40_distribution.md §install.sh step 5.
"""

import click

from . import __version__


@click.group()
@click.version_option(version=__version__, prog_name="mcp-env-browser")
def cli() -> None:
    """mcp-env-browser — credential vault + browser execution broker (Phase 1 Strategi A)."""
    pass


@cli.command()
def version() -> None:
    """Print version."""
    click.echo(f"mcp-env-browser {__version__}")


# Phase 1: stub commands. Phase 8 wires full implementations.
# (Tidak ditambahkan di Phase 1 — `version` saja cukup untuk verify install + entry point.)


if __name__ == "__main__":
    cli()
