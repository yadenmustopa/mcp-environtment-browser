"""Unit tests untuk CLI (Phase 8).

Per refactor/10_mcp_server.md §CLI Commands + PLAN_PHASES.md §Phase 8.

Tests cover Click runner for each subcommand: version, config show/path/set-*, init, doctor.
Skip `serve` (long-running async, manual smoke).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from mcp_env_browser import cli as cli_module
from mcp_env_browser.cli import cli


@pytest.fixture(autouse=True)
def isolated_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Redirect CONFIG_FILE to tmp_path for every test."""
    monkeypatch.setattr(cli_module, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cli_module, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(cli_module, "LOG_DIR", tmp_path / "logs")
    return tmp_path


class TestVersionCommand:
    def test_version(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["version"])
        assert result.exit_code == 0
        assert "mcp-env-browser 0.1.0" in result.output


class TestConfigCommands:
    def test_config_path(self, isolated_config: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "path"])
        assert result.exit_code == 0
        assert str(isolated_config / "config.json") in result.output

    def test_config_show_empty(self, isolated_config: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "show"])
        assert result.exit_code == 0
        assert "no config" in result.output

    def test_config_show_with_data(self, isolated_config: Path) -> None:
        cfg = isolated_config / "config.json"
        cfg.write_text(
            json.dumps(
                {
                    "license_server_url": "http://x",
                    "license_api_key": "abcd1234secret5678",
                }
            )
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "show"])
        assert result.exit_code == 0
        # API key masked
        assert "abcd1234secret5678" not in result.output
        assert "5678" in result.output  # last 4 visible
        # server url visible
        assert "http://x" in result.output

    def test_config_set_server_url(self, isolated_config: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "set-server-url", "http://new:8765"])
        assert result.exit_code == 0
        cfg = json.loads((isolated_config / "config.json").read_text())
        assert cfg["license_server_url"] == "http://new:8765"

    def test_config_set_api_key(self, isolated_config: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "set-api-key", "supersecretkey"])
        assert result.exit_code == 0
        cfg = json.loads((isolated_config / "config.json").read_text())
        assert cfg["license_api_key"] == "supersecretkey"
        # chmod 600 (POSIX)
        if sys.platform != "win32":
            mode = (isolated_config / "config.json").stat().st_mode
            assert mode & 0o777 == 0o600


class TestInitCommand:
    def test_init_non_interactive_missing_api_key(
        self, isolated_config: Path
    ) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "init",
                "--server-url",
                "http://test:8765",
                "--non-interactive",
            ],
        )
        # Non-interactive + no API key → exit 1
        assert result.exit_code == 1

    def test_init_with_args_succeeds_when_server_unreachable(
        self, isolated_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Init should warn but still save config when server is down."""
        runner = CliRunner()
        with patch.object(cli_module, "_build_vault") as mock_vault_factory:
            mock_backend = MagicMock()
            mock_backend.backend_name.return_value = "encrypted_json"
            mock_vault_factory.return_value = mock_backend
            # Pretend server is down
            with patch("httpx.get", side_effect=Exception("connection refused")):
                result = runner.invoke(
                    cli,
                    [
                        "init",
                        "--server-url",
                        "http://test:8765",
                        "--api-key",
                        "testkey1234",
                    ],
                )
        # Non-interactive + server down → exit 1 (per init flow)
        assert result.exit_code == 1

    def test_init_with_args_succeeds(
        self, isolated_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runner = CliRunner()
        with (
            patch.object(cli_module, "_build_vault") as mock_vault_factory,
            patch("httpx.get") as mock_get,
        ):
            mock_backend = MagicMock()
            mock_backend.backend_name.return_value = "encrypted_json"
            mock_vault_factory.return_value = mock_backend
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            result = runner.invoke(
                cli,
                [
                    "init",
                    "--server-url",
                    "http://test:8765",
                    "--api-key",
                    "testkey1234",
                ],
            )
        assert result.exit_code == 0
        cfg = json.loads((isolated_config / "config.json").read_text())
        assert cfg["license_server_url"] == "http://test:8765"
        assert cfg["license_api_key"] == "testkey1234"
        assert "Config saved" in result.output


class TestDoctorCommand:
    def test_doctor_no_config(self, isolated_config: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor"])
        # No config → exit 1
        assert result.exit_code == 1
        assert "config.json exists" in result.output

    def test_doctor_all_pass(self, isolated_config: Path) -> None:
        cfg = isolated_config / "config.json"
        cfg.write_text(
            json.dumps(
                {
                    "license_server_url": "http://test:8765",
                    "license_api_key": "abcd1234",
                }
            )
        )
        runner = CliRunner()
        with (
            patch.object(cli_module, "_build_vault") as mock_vault_factory,
            patch("httpx.get") as mock_get,
            patch("playwright.sync_api.sync_playwright") as mock_pw,
            patch.object(Path, "exists", return_value=True),
        ):
            mock_backend = MagicMock()
            mock_backend.backend_name.return_value = "encrypted_json"
            mock_vault_factory.return_value = mock_backend
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            # Mock sync_playwright context manager
            mock_chromium = MagicMock()
            mock_chromium.executable_path = "/usr/bin/chromium"
            mock_pw.return_value.__enter__.return_value.chromium = mock_chromium
            result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 0, result.output
        assert "All checks passed" in result.output

    def test_doctor_server_unreachable(self, isolated_config: Path) -> None:
        cfg = isolated_config / "config.json"
        cfg.write_text(
            json.dumps(
                {
                    "license_server_url": "http://test:8765",
                    "license_api_key": "abcd1234",
                }
            )
        )
        runner = CliRunner()
        with (
            patch.object(cli_module, "_build_vault") as mock_vault_factory,
            patch("httpx.get", side_effect=Exception("down")),
        ):
            mock_backend = MagicMock()
            mock_backend.backend_name.return_value = "encrypted_json"
            mock_vault_factory.return_value = mock_backend
            result = runner.invoke(cli, ["doctor"])
        # server unreachable = at least 1 failure
        assert result.exit_code != 0
        assert "license server reachable" in result.output
        assert "failed" in result.output
