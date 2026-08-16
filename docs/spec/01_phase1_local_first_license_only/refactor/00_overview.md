# Refactor Overview — Phase 1 Scope Contract

> Owner workflow (verified): brainstorming → matrix scoring → plan di
> `docs/spec/<slug>/refactor/` (multi-file) → approval → implementation.
> Plan disimpan **sebelum** kode ditulis.

---

## Quick Split Matrix (dari brainstorm)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  STRATEGI A: Local-first + license server only   → 22/25 (JUARA)              │
│  Strategi D: Hybrid credential-from-server      → 16/25 (Phase 2)            │
│  Strategi B: Server-rendered encrypted scripts  → 10/25 (skip)               │
│  Strategi C: Server-side browser farm           →  5/25 (skip — K2 violated)  │
└──────────────────────────────────────────────────────────────────────────────┘
```

Detail skor & alasan lihat `spec.md` §4.

---

## Why "Quick Split" (Strategi A) — Bukan "Clean Split" (Strategi D)

Owner memilih strategi yang **sesuai permintaan eksplisit** (K7: simple
dulu), bukan yang paling future-proof secara abstrak. Trade-off sadar:

| Aspek | Quick Split (A) | Clean Split (D) |
|---|---|---|
| Time-to-market | ~1-2 minggu | ~6-8 minggu |
| Source visible ke developer | ✅ Ya (mitigasi: PyInstaller binary) | ❌ Tidak (server-side code only) |
| Business model validated | ✅ Pertama | ❌ Lewat validasi |
| Effort re-do kalau ganti strategi | Rendah (vault logic reusable) | Tinggi (rebuild server infra) |

Owner **menyimpan Strategi D sebagai roadmap** di `roadmap_migration.md`
sehingga migrasi tinggal switch endpoint.

---

## Scope Contract

**IN SCOPE (Phase 1)**:
- MCP stdio server di local user
- 13 MCP tools (lihat `spec.md` §6.4) + 3 MCP prompts (lihat `spec.md` §6.4.1)
- Credential vault pakai libsecret (Linux) + encrypted JSON fallback
- License server FastAPI + SQLite
- Per-tab counter real-time
- CLI `init` + `serve`
- Install script bash idempotent
- End-to-end test dengan Hermes Agent

**OUT OF SCOPE (Phase 1)**:
- Dashboard web (→ Phase 3)
- Master key KDF server-side (→ Phase 2)
- Cross-platform vault adapter (→ Phase 2/3, Phase 1 Linux only)
- Multi-tenant isolation (→ Phase 2)
- Workflow script signing (→ Phase 2)
- Stripe/billing integration (→ Phase 3)

---

## File Map (Phase 1 — INI YANG DISENTUH)

```
mcp-environtment-browser/
├── README.md                              [NEW] orientasi + quick start
├── LICENSE                                [NEW] MIT
├── pyproject.toml                         [NEW] project config + deps
├── install.sh                             [NEW] bash idempotent
├── .env.example                           [NEW] config template
├── .gitignore                             [NEW] standard Python
├── src/
│   ├── mcp_env_browser/
│   │   ├── __init__.py                    [NEW] package metadata
│   │   ├── cli.py                         [NEW] Click CLI (serve, init)
│   │   ├── mcp_server.py                  [NEW] MCP stdio server
│   │   ├── vault/
│   │   │   ├── __init__.py                [NEW] VaultBackend protocol
│   │   │   ├── secretstorage.py           [NEW] Linux libsecret adapter
│   │   │   └── encrypted_json.py          [NEW] fallback / headless
│   │   ├── browser/
│   │   │   ├── __init__.py                [NEW] Playwright wrapper
│   │   │   ├── executor.py                [NEW] smart_connect_browser
│   │   │   └── cdp.py                     [NEW] Console/Network/DOM helpers
│   │   └── license/
│   │       ├── __init__.py                [NEW] License client
│   │       └── client.py                  [NEW] HTTP ke license server
│   └── license_server/
│       ├── __init__.py                    [NEW] package metadata
│       ├── server.py                      [NEW] FastAPI app
│       ├── db.py                          [NEW] SQLite + migrations
│       └── api/
│           ├── __init__.py                [NEW] router aggregator
│           ├── license.py                 [NEW] /license/check
│           ├── tab.py                     [NEW] /tab/increment
│           └── admin.py                   [NEW] /license/register
├── tests/
│   ├── unit/
│   │   ├── test_vault.py                  [NEW] roundtrip + types
│   │   ├── test_browser.py                [NEW] mock Playwright
│   │   ├── test_license_client.py         [NEW] mock HTTP
│   │   └── test_cli.py                    [NEW] Click runner
│   ├── integration/
│   │   ├── test_mcp_stdio.py              [NEW] end-to-end MCP
│   │   ├── test_license_server.py         [NEW] FastAPI TestClient
│   │   └── test_per_tab_counter.py        [NEW] 100 tabs simulation
│   └── manual/
│       └── test_hermes_e2e.py             [NEW] manual Hermes integration
└── docs/
    └── spec/01_phase1_local_first_license_only/
        ├── spec.md                        ✅ done
        ├── state.json                     ✅ done
        ├── knowledge.md                   ✅ done
        ├── roadmap_migration.md           ✅ done
        └── refactor/
            ├── 00_overview.md             ← this file
            ├── 10_mcp_server.md           [DRAFT — next]
            ├── 20_license_server.md       [DRAFT — next]
            ├── 30_client_arch.md          [DRAFT — next]
            ├── 40_distribution.md         [DRAFT — next]
            └── 90_decisions_log.md        ✅ next (CAPTURE K1-K7)
```

---

## Implementation Order (Quick Win Sequence)

Sesuai owner workflow KISS — implement smallest viable first:

1. **Install script + pyproject.toml** — bisa `pip install -e .` work
2. **License server** — FastAPI minimal + SQLite (1 endpoint: `/health`)
3. **Vault backend** — `secretstorage` adapter + encrypted JSON fallback
4. **License client** — HTTP wrapper + retry logic
5. **Browser executor** — Playwright wrapper + per-tab counter hook
6. **MCP server** — 13 tools + 3 prompts (lihat spec §6.4 + §6.4.1)
7. **CLI** — Click `init` + `serve`
8. **Tests** — unit + integration + manual
9. **End-to-end Hermes test** — owner-driven validation

Setiap step = 1 commit conventional (`feat:`, `test:`, `docs:`, `chore:`).

---

## Plan Status

- **DRAFT** — menunggu approval owner (`yadenmustopa`)
- Tidak ada kode di-write sampai plan di-approve
- Setelah approve, implementation mengikuti urutan di atas