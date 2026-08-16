# 45 — Web Monitoring Companion

> Detail teknis untuk `src/mcp_env_browser/monitor.py` + `monitor.html`.
> Companion UI supaya user bisa lihat real-time apa yang sedang agent
> lakukan di browser, dan click untuk intervene.

---

## Goals (Capture dari Diskusi)

1. **Real-time observability** — user lihat screenshot tiap session,
   seperti billing warnet menampilkan screen tiap client
2. **Session identity** — label manusia-baca per tab (mis: "TikTok Login",
   "GCP Billing"), supaya instruksi pause/resume jelas antara user dan agent
3. **Click-to-act** — user klik session card untuk bring browser window
   ke front, fokus ke tab yang dimaksud (terutama saat pause/resume)
4. **Multi-tab clarity** — ordering left-to-right, position field sync
   dengan visual tab order

## Arsitektur

```
mcp-env-browser (CLI serve)
  ├── MCP stdio (untuk agent)
  └── HTTP server di localhost:9876 (untuk monitoring UI)
       ├── GET /                       → static HTML
       ├── GET /api/sessions           → list sessions JSON
       └── POST /api/sessions/{id}/focus → bring browser window to front
```

**Bukan** SSE/WebSocket — polling HTTP tiap 2 detik cukup untuk Phase 1
(monitor visual, bukan real-time gaming).

## Module Map

```
src/mcp_env_browser/
├── monitor.py              # FastAPI app + endpoints
├── monitor.html            # Static HTML + vanilla JS
└── browser/
    └── executor.py         # add: list_sessions(), focus_session() methods
```

## `monitor.py` Spec

```python
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pathlib import Path

app = FastAPI(title="mcp-env-browser Monitor")

# Will be injected by CLI at startup
browser_executor = None  # type: BrowserExecutor

@app.get("/api/sessions")
async def list_sessions(include_screenshot: bool = True) -> list[dict]:
    """List semua session aktif dengan screenshot."""
    if browser_executor is None:
        raise HTTPException(503, "browser_executor not initialized")
    return browser_executor.list_sessions(include_screenshot=include_screenshot)

@app.post("/api/sessions/{session_id}/focus")
async def focus_session(session_id: str) -> dict:
    """Bring browser window + tab ke front."""
    if browser_executor is None:
        raise HTTPException(503, "browser_executor not initialized")
    try:
        browser_executor.focus_session(session_id)
        return {"ok": True}
    except KeyError:
        raise HTTPException(404, f"session {session_id} not found")

@app.get("/")
async def index() -> HTMLResponse:
    """Serve static monitoring page."""
    html = (Path(__file__).parent / "monitor.html").read_text()
    return HTMLResponse(html)

@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
```

## `monitor.html` Spec

Single-page vanilla JS, no framework, no build step:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>mcp-env-browser Monitor</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #1e1e1e; color: #ddd; margin: 0; padding: 16px; }
    h1 { font-size: 18px; margin: 0 0 16px; }
    .meta { color: #888; font-size: 13px; margin-bottom: 16px; }
    .grid { display: flex; gap: 12px; overflow-x: auto; padding-bottom: 16px; }
    .card {
      flex: 0 0 auto;
      width: 320px;
      border: 2px solid #444;
      border-radius: 6px;
      padding: 12px;
      background: #2a2a2a;
      cursor: pointer;
      transition: border-color 0.15s;
    }
    .card:hover { border-color: #007bff; }
    .card.paused { border-color: #ffc107; }
    .card.captcha { border-color: #dc3545; }
    .label { font-weight: bold; margin-bottom: 4px; }
    .position { color: #888; font-size: 12px; }
    .url { color: #6c9; font-size: 12px; word-break: break-all; margin: 8px 0; }
    .status {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 3px;
      font-size: 11px;
      text-transform: uppercase;
      font-weight: bold;
    }
    .status.active { background: #28a745; color: white; }
    .status.paused { background: #ffc107; color: black; }
    .status.captcha { background: #dc3545; color: white; }
    .status.error { background: #6c757d; color: white; }
    .age { color: #888; font-size: 11px; margin-top: 4px; }
    img { width: 100%; height: auto; margin-top: 8px; border-radius: 4px; }
  </style>
</head>
<body>
  <h1>mcp-env-browser Monitor</h1>
  <div class="meta">
    Auto-refresh every 2s. Click card to bring browser window to front.
    <span id="last-update"></span>
  </div>
  <div id="grid" class="grid"></div>

  <script>
    async function refresh() {
      try {
        const r = await fetch('/api/sessions?include_screenshot=true');
        const sessions = await r.json();
        render(sessions);
        document.getElementById('last-update').textContent =
          `Last updated: ${new Date().toLocaleTimeString()}`;
      } catch (e) {
        document.getElementById('grid').innerHTML =
          `<p style="color: #dc3545;">Connection lost: ${e.message}. Retrying...</p>`;
      }
    }

    function render(sessions) {
      const grid = document.getElementById('grid');
      if (sessions.length === 0) {
        grid.innerHTML = '<p style="color: #888;">No active sessions. Agent is idle.</p>';
        return;
      }
      grid.innerHTML = sessions.map(s => `
        <div class="card ${s.status}" onclick="focusSession('${s.session_id}')">
          <div class="label">${escapeHtml(s.label)}</div>
          <div class="position">Tab ${s.position} · ${s.status.toUpperCase()}</div>
          <div class="url">${escapeHtml(s.url)}</div>
          <div class="age">${formatAge(s.age_seconds)} old</div>
          ${s.last_screenshot_b64
            ? `<img src="data:image/png;base64,${s.last_screenshot_b64}" alt="${escapeHtml(s.label)}" />`
            : '<p style="color: #888; font-size: 12px;">No screenshot</p>'}
        </div>
      `).join('');
    }

    function escapeHtml(str) {
      const div = document.createElement('div');
      div.textContent = str;
      return div.innerHTML;
    }

    function formatAge(seconds) {
      if (seconds < 60) return `${seconds}s`;
      if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
      return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
    }

    async function focusSession(id) {
      try {
        await fetch(`/api/sessions/${id}/focus`, {method: 'POST'});
      } catch (e) {
        alert(`Failed to focus session: ${e.message}`);
      }
    }

    setInterval(refresh, 2000);
    refresh();
  </script>
</body>
</html>
```

## Browser Executor Extensions

Tambah 2 method ke `BrowserExecutor`:

```python
class BrowserExecutor:
    def list_sessions(self, include_screenshot: bool = False) -> list[dict]:
        """Return list of all active sessions dengan metadata."""
        import time
        now = time.time()
        sessions = []
        for sid, sess in sorted(
            self._sessions.items(),
            key=lambda x: x[1].get("position", 0)
        ):
            status = self._compute_status(sess)
            age_seconds = int(now - sess.get("created_at", now))

            entry = {
                "session_id": sid,
                "label": sess.get("label", "Unnamed"),
                "position": sess.get("position", 0),
                "url": sess["page"].url,
                "status": status,
                "age_seconds": age_seconds,
            }

            if include_screenshot:
                try:
                    shot = sess["page"].screenshot(full_page=False, type="png")
                    import base64
                    entry["last_screenshot_b64"] = base64.b64encode(shot).decode("ascii")
                except Exception:
                    entry["last_screenshot_b64"] = None

            sessions.append(entry)
        return sessions

    def focus_session(self, session_id: str) -> None:
        """Bring browser window + tab to front."""
        if session_id not in self._sessions:
            raise KeyError(f"session {session_id} not found")

        sess = self._sessions[session_id]
        page = sess["page"]

        # Bring page to front
        try:
            page.bring_to_front()
        except Exception:
            pass  # Fallback: just focus the browser window

        # Optional: highlight window via X11/wmctrl (Linux only)
        # self._focus_browser_window()  # OS-specific

    def _compute_status(self, sess: dict) -> str:
        """Heuristic status detection."""
        if sess.get("error"): return "error"
        if sess.get("paused"): return "paused"
        # Heuristic: check page for CAPTCHA iframe
        try:
            captcha_selectors = ["iframe[src*='recaptcha']", "iframe[src*='hcaptcha']", "#captcha"]
            for sel in captcha_selectors:
                if sess["page"].locator(sel).count() > 0:
                    return "captcha"
        except Exception:
            pass
        return "active"
```

## CLI Integration

Update `cli.py` untuk start both MCP stdio + monitoring HTTP:

```python
# cli.py
import asyncio
import threading
import uvicorn

@click.command()
@click.option("--no-monitor", is_flag=True, help="Skip web monitoring HTTP server")
@click.option("--monitor-port", default=9876, help="Port for monitoring UI")
def serve(no_monitor: bool, monitor_port: int):
    """Start MCP stdio server (and optionally web monitoring)."""
    browser_executor = BrowserExecutor(license_client, vault)
    license_client.start()
    vault.unlock()

    # Start monitoring HTTP server in background thread
    if not no_monitor:
        from . import monitor
        monitor.browser_executor = browser_executor
        config = uvicorn.Config(monitor.app, host="127.0.0.1", port=monitor_port, log_level="warning")
        server = uvicorn.Server(config)
        threading.Thread(target=server.run, daemon=True).start()
        click.echo(f"Web monitoring: http://localhost:{monitor_port}")

    # Run MCP stdio in main thread
    asyncio.run(run_mcp_stdio(browser_executor))
```

## Security

- **Bind ke `127.0.0.1`** saja — tidak exposed ke LAN/internet
- **No auth** di Phase 1 (localhost only, OS access control cukup)
- **Phase 2**: tambah Bearer token kalau perlu expose ke LAN/cloudflared

## Performance

- **Screenshot size**: 800x600 max (Playwright default sudah cukup)
- **Polling interval**: 2 detik (balance antara freshness dan CPU)
- **Compression**: PNG by default, JPEG quality 60 bisa di-config kalau perlu
- **Single session max**: screenshot ~100-500KB per session, 10 sessions = 5MB per refresh

## Testing Strategy

- **Unit**: `list_sessions()` + `focus_session()` dengan mock Playwright
- **Integration**: real browser, verify HTTP endpoints return valid JSON
- **Manual**: owner inspect di browser sendiri, verify click-to-focus works

## Gotchas

- **Browser window minimize**: kalau browser di-minimize, `bring_to_front()`
  tetap work (OS handle). Kalau browser closed, raise exception → status
  jadi "error"
- **Multi-monitor**: Phase 1 asumsi single monitor. Phase 2 handle multi-monitor
- **Headless mode**: kalau `--headless` flag di Playwright, focus_session()
  mungkin tidak work. Phase 1 pakai `headless=False` untuk local user
  (lihat `30_client_arch.md` §BrowserExecutor) — fokus dari monitoring
  tetap meaningful

---

## Phase 2 Roadmap (DEFER)

- **SSE streaming**: replace polling dengan Server-Sent Events untuk real-time
- **Click-to-pause / click-to-resume**: button di session card
- **Multi-window support**: kalau Playwright launch multi-browser window
- **Remote access**: cloudflared/ngrok tunnel untuk lihat dari device lain
- **Recording**: session replay (audit log + video) untuk compliance