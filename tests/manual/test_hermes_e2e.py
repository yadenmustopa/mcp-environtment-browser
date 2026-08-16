"""Hermes E2E Validation smoke script (Phase 9).

Per PLAN_PHASES.md §Phase 9 + spec §9 Acceptance Criteria.

This is a MANUAL smoke script — NOT a unit test. It exercises the MCP stdio
JSON-RPC round-trip without launching a real browser (Playwright not installed
in CI). Owner can run it locally to verify MCP wiring before/after install.sh.

Usage:
    python tests/manual/test_hermes_e2e.py

What it verifies (auto, no manual input):
1. `mcp-env-browser --version` works
2. `mcp-env-browser version` subcommand works
3. MCP stdio round-trip: spawn `mcp-env-browser serve` as subprocess,
   send `tools/list` JSON-RPC, expect 13 tools registered
4. MCP stdio round-trip: send `prompts/list`, expect 3 prompts registered
5. JSON parse: extract tool names, verify all 13 per spec §6.4
6. JSON parse: extract prompt names, verify 3 per spec §6.4.1

What requires MANUAL verification (not in this script):
- Browser actually launches and navigates (Chromium binary needed)
- Tab counter increments on real server DB
- License gate with invalid key returns 401 from real FastAPI server
- Pause/resume UI workflow in real browser

Owner should run this after install.sh + license-server running to verify
the install pipeline works end-to-end on their machine.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
# Use clean Python 3.10 paths only — avoid hermes-agent venv which has
# broken pydantic_core binary (unrelated to mcp-env-browser).
PYTHONPATH_PARTS = [
    str(REPO_ROOT / "src"),
    "/home/denevill/.local/lib/python3.10/site-packages",
    "/usr/local/lib/python3.10/dist-packages",
    "/usr/lib/python3/dist-packages",
]

# Filter out any pre-set PYTHONPATH that might pull in hermes-agent venv
os.environ.pop("PYTHONPATH", None)


def run_cli(*args: str, timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    """Run mcp-env-browser CLI subprocess and capture output."""
    env = {
        "PYTHONPATH": ":".join(PYTHONPATH_PARTS),
        "PATH": "/usr/bin:/usr/local/bin",
        "MCP_VAULT_BACKEND": "encrypted_json",
        "MCP_VAULT_PASSPHRASE": "smoke_test_passphrase",
    }
    return subprocess.run(
        [sys.executable, "-m", "mcp_env_browser.cli", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=timeout,
    )


def send_stdio_request(request: dict[str, object], timeout: float = 10.0) -> dict[str, object]:
    """Spawn `mcp-env-browser serve`, send MCP initialize + tools/prompts/list, return response.

    MCP protocol requires initialize handshake before tools/list (per
    https://modelcontextprotocol.io/). We send both requests, then read
    the response to the actual request.
    """
    env = {
        "PYTHONPATH": ":".join(PYTHONPATH_PARTS),
        "PATH": "/usr/bin:/usr/local/bin",
        "MCP_VAULT_BACKEND": "encrypted_json",
        "MCP_VAULT_PASSPHRASE": "smoke_test_passphrase",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "mcp_env_browser.cli", "serve", "--no-monitor"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )
    try:
        assert proc.stdin is not None
        assert proc.stdout is not None
        # Send initialize + the actual request as 2 separate JSON-RPC lines
        initialize_request = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "smoke-test", "version": "0.1.0"},
            },
        }
        # Send the actual request with id=1; initialize with id=0
        request_with_id = dict(request)
        if request_with_id.get("id") == 1:
            request_with_id["id"] = 2
        # Send in two writes with a flush + sleep between, so server can process
        # initialize before prompts/tools list arrives.
        proc.stdin.write(json.dumps(initialize_request) + "\n")
        proc.stdin.flush()
        # Generous delay so server processes initialize fully
        import time as _time

        _time.sleep(1.0)
        proc.stdin.write(json.dumps(request_with_id) + "\n")
        proc.stdin.flush()
        _time.sleep(0.5)
        stdout, stderr = proc.communicate(timeout=timeout)
        # Parse responses — skip first (initialize response), take second
        json_lines = [line.strip() for line in stdout.splitlines() if line.strip().startswith("{")]
        if len(json_lines) >= 2:
            return json.loads(json_lines[1])
        if len(json_lines) == 1:
            return json.loads(json_lines[0])
        raise RuntimeError(f"no JSON response. stdout={stdout!r}, stderr={stderr!r}")
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=2.0)


def main() -> int:
    failures = 0

    # 1. CLI --version
    print("[1] mcp-env-browser --version ... ", end="")
    result = run_cli("--version")
    if result.returncode == 0 and "0.1.0" in result.stdout:
        print("✓")
    else:
        print(f"✗ (exit={result.returncode}, stdout={result.stdout!r}, stderr={result.stderr!r})")
        failures += 1

    # 2. version subcommand
    print("[2] mcp-env-browser version ... ", end="")
    result = run_cli("version")
    if result.returncode == 0 and "mcp-env-browser 0.1.0" in result.stdout:
        print("✓")
    else:
        print(f"✗ (exit={result.returncode}, stdout={result.stdout!r})")
        failures += 1

    # 3. MCP stdio: tools/list
    print("[3] MCP stdio tools/list ... ", end="")
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    }
    try:
        resp = send_stdio_request(request)
        tools = resp.get("result", {}).get("tools", [])
        tool_names = {t["name"] for t in tools}
        expected = {
            "smart_list_credentials",
            "smart_get_credential_meta",
            "smart_set_credential",
            "smart_delete_credential",
            "smart_connect_browser",
            "smart_list_sessions",
            "smart_close_browser",
            "smart_browser_action",
            "smart_browser_console_log",
            "smart_browser_network_log",
            "smart_browser_inspect",
            "smart_session_pause",
            "smart_session_resume",
        }
        missing = expected - tool_names
        if not missing:
            print(f"✓ ({len(tools)} tools)")
        else:
            print(f"✗ missing tools: {missing}")
            failures += 1
    except Exception as e:
        print(f"✗ exception: {e}")
        failures += 1

    # 4. MCP stdio: prompts/list
    print("[4] MCP stdio prompts/list ... ", end="")
    request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "prompts/list",
        "params": {},
    }
    try:
        resp = send_stdio_request(request)
        prompts = resp.get("result", {}).get("prompts", [])
        prompt_names = {p["name"] for p in prompts}
        expected_prompts = {
            "oauth_confirmation_flow",
            "browser_debug_workflow",
            "human_intervention_workflow",
        }
        missing_p = expected_prompts - prompt_names
        if not missing_p:
            print(f"✓ ({len(prompts)} prompts)")
        else:
            print(f"✗ missing prompts: {missing_p}")
            failures += 1
    except Exception as e:
        print(f"✗ exception: {e}")
        failures += 1

    # Summary
    print()
    if failures == 0:
        print("✓ Phase 9 auto smoke: 4/4 PASS")
        print()
        print("Manual checks remaining (require owner + license-server running):")
        print("  - init wizard on popOS user saves config + vault roundtrip")
        print("  - serve launches real Chromium browser")
        print("  - tab counter increments in license_server SQLite DB")
        print("  - license gate returns 401 with invalid API key")
        print("  - pause/resume UI workflow in real browser (CAPTCHA test)")
        return 0
    else:
        print(f"✗ Phase 9 auto smoke: {failures} failure(s)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
