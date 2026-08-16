# mcp-environtment-browser

> MCP server untuk credential vault + browser execution broker, dengan subscription per-tab.

---

## Status: PLANNING (Draft Spec — belum ada implementasi)

Repo ini masih dalam **fase planning**. Belum ada kode yang ditulis.
Lihat [`docs/spec/01_phase1_local_first_license_only/spec.md`](docs/spec/01_phase1_local_first_license_only/spec.md)
untuk latar belakang, scope, dan strategi implementasi fase 1.

---

## Apa Ini (Goal)

Sebuah **MCP server** yang memungkinkan agent (Hermes, OpenAI, Claude Code, dll)
menjalankan tugas di browser — seperti login ke TikTok, scrape data Google,
akses GCP, atau ambil data dari Coretax DJP — **tanpa agent harus pegang
credential mentah**.

**Prinsip utama:**
- **Credential vault** — username/password/SSH/OAuth token/env var, disimpan
  terenkripsi di local user
- **Browser execution broker** — agent minta "scrape akun TikTok X", MCP yang
  handle login + ambil data + return JSON
- **Per-tab billing** — setiap `browser.new_page()` dihitung 1 tab, hit server
  license DB; user tidak terdaftar = tidak bisa pakai
- **Multi-agent** — agent apapun yang bisa connect MCP (stdio transport) bisa
  pakai, tanpa modifikasi
- **13 MCP Tools + 3 MCP Prompts** — Tools untuk runtime action (credential +
  browser + DevTools + pause/resume + list sessions + web monitoring),
  Prompts untuk pattern guidance (OAuth confirmation + browser debug + human
  intervention)
- **Web monitoring companion** — real-time screenshot tiap tab di
  `http://localhost:9876`, click-to-act untuk user intervene
- **Cross-platform** — dirancang jalan di Linux/Windows/macOS

---

## Stack & Lisensi

| Item | Pilihan |
|---|---|
| Bahasa | Python 3.10+ |
| Server | FastAPI (license DB + per-tab counter) |
| Client | Click/Typer CLI + MCP stdio |
| Browser | Playwright (Python) |
| Credential storage | libsecret/Secret Service API (Linux), extensible ke Windows/macOS |
| Lisensi | MIT |
| Branch default | `master` |

---

## 🚨 Sebelum Kontribusi — WAJIB BACA

1. **[`AGENTS.md`](AGENTS.md)** — strict guidelines, anti-over-engineering, owner workflow style
2. **[`QUICKREF.md`](QUICKREF.md)** — TL;DR orientasi 2 menit
3. **`docs/spec/01_phase1_local_first_license_only/spec.md`** — latar belakang, K1-K7, scope, strategi A

## Struktur Docs

```
.
├── AGENTS.md                                  # ← BACA PERTAMA
├── QUICKREF.md                                # ← BACA KEDUA (orientasi 2 menit)
├── README.md                                  # file ini
├── LICENSE                                    # MIT
└── docs/spec/01_phase1_local_first_license_only/
    ├── spec.md                  # Latar belakang, K1-K7, scope, strategi A
    ├── state.json               # SSOT fase + quality gates
    ├── knowledge.md             # Reuse catatan (cua-driver, libsecret, Playwright)
    ├── roadmap_migration.md     # Strategi A → D → fase 3 (untuk agent masa depan)
    └── refactor/
        ├── 00_overview.md       # Quick split matrix + scope contract
        ├── 10_mcp_server.md     # Detail MCP tool spec
        ├── 20_license_server.md # Detail server endpoint spec
        ├── 30_client_arch.md    # Local-first client structure
        ├── 40_distribution.md   # PyInstaller binary + install script
        ├── 90_decisions_log.md  # CAPTURE K1-K7 — JANGAN DIHAPUS
        └── 95_anti_overengineering_guard.md  # ← BACA KETIGA (anti-over-engineer)
```

---

## Status Implementasi

| Phase | Strategi | Status |
|---|---|---|
| Phase 1 | A. Local-first + license-server-only | 📝 DRAFT spec |
| Phase 2 | D. Hybrid credential-from-server + local browser | 📋 ROADMAP |
| Phase 3 | Multi-tenant + per-target rate limit | 📋 ROADMAP |

Lihat [`roadmap_migration.md`](docs/spec/01_phase1_local_first_license_only/roadmap_migration.md)
untuk transisi detail.

---

## Kontribusi

Sampai spec disetujui owner (`yadenmustopa`), **JANGAN tulis kode implementasi**.
Tambah/update docs saja.

Setelah spec di-approve, kontribusi mengikuti workflow di
`docs/spec/01_phase1_local_first_license_only/refactor/00_overview.md`.

---

## Lisensi

MIT — lihat [`LICENSE`](LICENSE).