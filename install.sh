#!/usr/bin/env bash
# mcp-env-browser install.sh
# Source: refactor/40_distribution.md §install.sh Spec (modified for Phase 1)
# Behavior: idempotent (sesuai AGENTS.md §7 'Future-proof, auto sekali setup').
#           Owner workflow: "Pastikan tidak menghapus hal penting" (memory).
#           TIDAK menghapus/menimpa existing files. Hanya creates + skips if exists.
set -euo pipefail

# === Determine script directory (where pyproject.toml + src/ live) ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# === Constants (per refactor/40_distribution.md line 56-64) ===
REPO_URL="https://github.com/yadenmustopa/mcp-environtment-browser"
PYTHON_MIN="3.10"
VENV_PATH="${MCP_VENV_PATH:-$HOME/.local/share/mcp-env-browser/venv}"
CONFIG_DIR="$HOME/.config/mcp-env-browser"

# === Step 1: Detect Python >=3.10 ===
python_bin=""
for py in python3.12 python3.11 python3.10 python3; do
  if command -v "$py" >/dev/null 2>&1; then
    version=$("$py" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
    # Compare versions: $PYTHON_MIN must be <= $version
    if [[ "$(printf '%s\n%s' "$PYTHON_MIN" "$version" | sort -V | head -n1)" == "$PYTHON_MIN" ]]; then
      python_bin="$py"
      break
    fi
  fi
done

if [[ -z "$python_bin" ]]; then
  echo "ERROR: Python ≥$PYTHON_MIN not found."
  echo "  Install via pyenv: 'curl https://pyenv.run | bash' lalu 'pyenv install 3.11'."
  exit 1
fi
echo "[1/5] ✅ Python detected: $python_bin ($version)"

# === Step 2: Create venv (idempotent — skip kalau sudah ada) ===
if [[ ! -d "$VENV_PATH" ]]; then
  echo "[2/5] Creating venv at $VENV_PATH..."
  "$python_bin" -m venv "$VENV_PATH"
else
  echo "[2/5] ✅ Venv sudah ada: $VENV_PATH (skip create, idempotent)"
fi

# === Step 3: pip install (Phase 1: install editable dari source repo) ===
# Phase 2: switch ke 'pip install mcp-env-browser[server]' dari PyPI
# Handle uv venv (no pip symlink) — fallback ke python -m pip
echo "[3/5] Installing mcp-env-browser (editable + server + dev)..."
# uv-created venv has no `pip` symlink — use `python -m pip` fallback
# cd to script dir so `pip install -e .` finds pyproject.toml
cd "$SCRIPT_DIR"
if [[ -x "$VENV_PATH/bin/pip" ]]; then
  "$VENV_PATH/bin/pip" install --upgrade pip --quiet 2>/dev/null || true
  "$VENV_PATH/bin/pip" install -e ".[server,dev]" --quiet
else
  "$VENV_PATH/bin/python" -m pip install --upgrade pip --quiet 2>/dev/null || true
  "$VENV_PATH/bin/python" -m pip install -e ".[server,dev]" --quiet
fi
echo "[3/5] ✅ Pip install selesai"

# === Step 4: Playwright Chromium ===
# Penting: Playwright butuh chromium binary (knowledge.md §3)
# Handle uv venv (no playwright symlink) — fallback ke python -m playwright
# Skip kalau MCP_SKIP_PLAYWRIGHT=1 (untuk CI/air-gapped; Phase 5 add proper handling)
echo "[4/5] Installing Chromium for Playwright..."
if [[ "${MCP_SKIP_PLAYWRIGHT:-0}" == "1" ]]; then
  echo "  → MCP_SKIP_PLAYWRIGHT=1, skip (Phase 5 will install later)"
else
  if [[ -x "$VENV_PATH/bin/playwright" ]]; then
    "$VENV_PATH/bin/playwright" install chromium || echo "  → WARN: playwright install failed (non-fatal, can retry later)"
  else
    "$VENV_PATH/bin/python" -m playwright install chromium || echo "  → WARN: playwright install failed (non-fatal, can retry later)"
  fi
fi

# === Step 5: Verify (Phase 1: import check, karena CLI plugin Phase 8) ===
echo "[5/5] Verifying installation..."
if "$VENV_PATH/bin/python" -c "import mcp_env_browser; print('  ✅ mcp_env_browser version:', mcp_env_browser.__version__)" 2>/dev/null; then
  : # success
else
  echo "  WARN: package not yet implemented (Phase 1 expected — akan datang di commit berikutnya)"
fi

echo ""
echo "✅ mcp-env-browser Phase 1 install selesai."
echo ""
echo "Next steps (akan implemented per Phase 1-9 PLAN_PHASES.md):"
echo "  1. Phase 2 — License server: '$VENV_PATH/bin/mcp-env-browser-license-server' (coming)"
echo "  2. Phase 8 — First-time init CLI: '$VENV_PATH/bin/mcp-env-browser init'"
echo "  3. Phase 8 — Start MCP stdio: '$VENV_PATH/bin/mcp-env-browser serve'"
echo "  4. Phase 9 — Setup Hermes Agent .mcp.json — example:"
echo '     {"mcpServers": {"mcp-env-browser": {"command": "'"$VENV_PATH/bin/mcp-env-browser"'", "args": ["serve"]}}}}'
echo ""
echo "Repo: $REPO_URL"
echo "Spec: $REPO_URL/blob/master/docs/spec/01_phase1_local_first_license_only/spec.md"
echo ""
