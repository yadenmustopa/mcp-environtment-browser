# 40 — Distribution & Installation

> Detail teknis untuk `install.sh`, PyInstaller binary build, dan
> user-facing install experience.

---

## Installation — 3 Channels

### Channel 1: `pip install` (developer)

Untuk owner + contributor + agent masa depan:

```bash
git clone git@github.com:yadenmustopa/mcp-environtment-browser.git
cd mcp-environtment-browser
pip install -e ".[server,dev]"
python -m playwright install chromium
```

### Channel 2: `install.sh` (end-user basic)

Bash script idempotent, download dari GitHub Release:

```bash
curl -fsSL https://raw.githubusercontent.com/yadenmustopa/mcp-environtment-browser/main/install.sh | bash
```

Tasks:
1. Detect OS (Linux/macOS, x86_64/arm64)
2. Detect Python ≥3.10 (kalau tidak ada, install via pyenv)
3. Create venv di `~/.local/share/mcp-env-browser/venv`
4. `pip install mcp-env-browser` (dari PyPI — Phase 2 publish)
5. `playwright install chromium`
6. Run `mcp-env-browser init` (interactive setup API key + server URL)
7. Print next steps

### Channel 3: PyInstaller binary (end-user no-Python)

```bash
curl -fsSL https://github.com/yadenmustopa/mcp-environtment-browser/releases/latest/download/install-binary.sh | bash
```

Tasks:
1. Detect OS + arch
2. Download binary dari release (`mcp-env-browser-{version}-{os}-{arch}.bin`)
3. chmod +x, move ke `~/.local/bin/mcp-env-browser`
4. Create wrapper script yang handle venv activation
5. Run `mcp-env-browser init`

---

## `install.sh` Spec

```bash
#!/usr/bin/env bash
set -euo pipefail

# Constants
REPO_URL="https://github.com/yadenmustopa/mcp-environtment-browser"
PYTHON_MIN="3.10"
VENV_PATH="${MCP_VENV_PATH:-$HOME/.local/share/mcp-env-browser/venv}"
CONFIG_DIR="$HOME/.config/mcp-env-browser"

# Step 1: Detect Python
python_bin=""
for py in python3.10 python3.11 python3.12 python3; do
  if command -v "$py" >/dev/null 2>&1; then
    version=$("$py" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
    if [[ "$(printf '%s\n%s' "$PYTHON_MIN" "$version" | sort -V | head -n1)" == "$PYTHON_MIN" ]]; then
      python_bin="$py"
      break
    fi
  fi
done

if [[ -z "$python_bin" ]]; then
  echo "ERROR: Python ≥$PYTHON_MIN not found. Install via pyenv: 'curl https://pyenv.run | bash'"
  exit 1
fi

# Step 2: Create venv (idempotent)
if [[ ! -d "$VENV_PATH" ]]; then
  echo "Creating venv at $VENV_PATH..."
  "$python_bin" -m venv "$VENV_PATH"
fi

# Step 3: pip install (idempotent)
echo "Installing mcp-env-browser..."
"$VENV_PATH/bin/pip" install --upgrade pip
"$VENV_PATH/bin/pip" install mcp-env-browser[server]  # Phase 2: PyPI publish

# Step 4: Playwright browsers
echo "Installing Chromium for Playwright..."
"$VENV_PATH/bin/playwright" install chromium

# Step 5: First-time init (interactive)
if [[ ! -f "$CONFIG_DIR/config.json" ]]; then
  echo "First-time setup..."
  "$VENV_PATH/bin/mcp-env-browser" init
fi

# Step 6: Verify
echo "Verifying installation..."
"$VENV_PATH/bin/mcp-env-browser" version
"$VENV_PATH/bin/mcp-env-browser" config show

echo ""
echo "✅ mcp-env-browser installed successfully!"
echo ""
echo "Next steps:"
echo "  1. Register your license: contact yadenmustopa for an API key"
echo "  2. Add to your agent's .mcp.json:"
echo '     {"mcpServers": {"mcp-env-browser": {"command": "'"$VENV_PATH/bin/mcp-env-browser"'", "args": ["serve"]}}}'
echo "  3. Run 'mcp-env-browser serve' to start the MCP server"
echo ""
```

### Idempotency

Setiap step cek dulu apakah sudah done. `install.sh` bisa di-run berkali-kali
tanpa efek samping.

---

## PyInstaller Binary Build

### GitHub Actions workflow (Phase 2)

```yaml
# .github/workflows/release.yml (Phase 2)
name: Release
on:
  push:
    tags: ['v*']
jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -e ".[server,dev]"
      - run: pip install pyinstaller
      - run: pyinstaller --onefile --name mcp-env-browser src/mcp_env_browser/cli.py
      - uses: actions/upload-artifact@v4
        with:
          name: mcp-env-browser-${{ matrix.os }}
          path: dist/mcp-env-browser
```

### Phase 1 (manual)

```bash
# Owner build binary untuk testing lokal
pyinstaller --onefile --name mcp-env-browser src/mcp_env_browser/cli.py
ls -lh dist/mcp-env-browser  # cek size
```

Expected size: 50-100 MB (embed Python + stdlib + click + httpx + structlog)
TIDAK embed Chromium — Playwright browser di-install terpisah.

---

## MCP Registration di Agent User Side

### Untuk Hermes (atau agent apapun yang pakai MCP)

User edit `.mcp.json` (atau config equivalent):

```json
{
  "mcpServers": {
    "mcp-env-browser": {
      "command": "/home/user/.local/share/mcp-env-browser/venv/bin/mcp-env-browser",
      "args": ["serve"]
    }
  }
}
```

Restart agent → MCP tools available di context.

### Untuk Claude Code / OpenAI Codex / dll

Lihat docs masing-masing platform — pattern sama (command + args).

---

## Self-Update (Phase 2)

```bash
mcp-env-browser update
```

Tasks:
1. Cek GitHub release terbaru
2. Bandingkan dengan `__version__`
3. Kalau lebih baru, prompt konfirmasi
4. `pip install --upgrade mcp-env-browser` di venv
5. Run `playwright install chromium` kalau Playwright version naik

---

## Uninstallation

```bash
# Manual
rm -rf ~/.local/share/mcp-env-browser
rm -rf ~/.config/mcp-env-browser
# Hapus entry dari .mcp.json
```

Phase 2: `mcp-env-browser uninstall` script otomatis.

---

## Verification Checklist (Post-Install)

Setelah install, jalankan:

```bash
# 1. CLI works
mcp-env-browser version
# Expected: 0.1.0

# 2. Config valid
mcp-env-browser config show
# Expected: license_server_url + masked api_key

# 3. License server reachable
mcp-env-browser doctor
# Expected: ✅ server reachable, ✅ license valid

# 4. Vault roundtrip
mcp-env-browser vault test
# Expected: ✅ set/get/delete works

# 5. MCP stdio starts
mcp-env-browser serve &
sleep 1
# Kirim MCP initialize request via stdin, verify response
```

---

## Distribution Size Estimate

| Component | Size |
|---|---|
| Python interpreter (embedded) | ~30 MB |
| stdlib | ~10 MB |
| click + mcp + httpx + structlog | ~5 MB |
| cryptography | ~5 MB |
| **Total binary** | **~50 MB** |
| Playwright Chromium (separate) | ~150 MB |
| **Total user disk** | **~200 MB** |

Acceptable untuk desktop tool.

---

## Anti-Pattern Notes

### ❌ Jangan embed Chromium di binary
- Binary jadi 200+ MB, susah distribusi
- Playwright version mismatch dengan binary = bug
- Install terpisah lebih flexible (user bisa skip kalau sudah punya)

### ❌ Jangan auto-update tanpa konfirmasi
- Owner explicit concern soal destructive ops (lihat memory)
- Update harus explicit `mcp-env-browser update` dengan prompt

### ❌ Jangan hardcode Python path
- Gunakan `#!/usr/bin/env python3` shebang atau `python3 -m` pattern
- Allow user override via `MCP_PYTHON_BIN` env var

### ✅ Selalu idempotent
- Owner workflow: "future-proof, auto sekali setup untuk masa depan"
- Install script harus run 2x = same result