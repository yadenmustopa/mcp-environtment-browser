# Quick Reference Card — mcp-environtment-browser

> **TL;DR untuk agent/developer yang baca repo ini dan butuh orientasi 2 menit.**

---

## Saya harus baca apa dulu?

```
1. README.md                           — orientasi umum
2. AGENTS.md                           — strict guidelines (PRINSIP UTAMA)
3. docs/spec/01_phase1_local_first_license_only/spec.md
4. docs/spec/01_phase1_local_first_license_only/refactor/90_decisions_log.md
   (CAPTURE K1-K7 — JANGAN HAPUS)
```

---

## Status saat ini

```
Phase:    1 (Strategi A)
Status:   PLANNING (DRAFT spec, belum implementasi)
Stack:    Python + FastAPI + Click + Playwright + libsecret
Lisensi:  MIT
Branch:   master
MCP:      13 Tools + 3 Prompts (oauth_confirmation_flow, browser_debug_workflow, human_intervention_workflow)
Web:      Monitoring UI di http://localhost:9876 (real-time session screenshots)
```

---

## Aturan paling penting (5 teratas)

1. **Default ke paling sederhana**. Jangan over-engineer.
2. **Strategi A, bukan D**. Credential + browser di local. Server cuma license.
3. **Tidak ada kode sebelum plan di-approve owner**.
4. **Tidak ada silent decision change**. Update `90_decisions_log.md` + diskusi owner.
5. **Honest gate status**. `skipped` ≠ `passed`. Tulis apa adanya.

---

## Yang BOLEH dilakukan tanpa diskusi

- ✅ Bug fix sesuai plan
- ✅ Conventional commit
- ✅ Edit doc non-decision (typo, link, format)
- ✅ Internal refactor yang tetap di Strategi A
- ✅ Tambah test (sesuai §3 default testing tools)

---

## Yang TIDAK BOLEH tanpa diskusi

- ❌ Ganti strategi A → D
- ❌ Tambah MCP tool baru
- ❌ Tambah MCP prompt baru (sudah ada 2, cukup)
- ❌ Tambah credential type baru
- ❌ Tambah backend/platform support baru
- ❌ Edit `90_decisions_log.md` K1-K7
- ❌ Edit `spec.md` §6 (desain tanpa owner approval)
- ❌ Couple dengan `smart_agent` repo

---

## Default teknologi (no need to ask owner)

| Kategori | Pakai |
|---|---|
| HTTP client | httpx |
| CLI | click |
| JSON schema | pydantic v2 |
| Logging | structlog → stderr |
| Testing | pytest + pytest-asyncio |
| Lint | ruff |
| Type check | mypy |
| Config | JSON di `~/.config/mcp-env-browser/` |
| Build | pyproject.toml |
| Binary | PyInstaller |
| MCP | stdio transport |
| Credential enc | libsecret (OS handle) |
| Migration | alembic |
| DB | SQLite (Phase 1) |
| Test coverage target | 80% |

---

## K1-K7 Quick Ref

| ID | Topik | Keputusan |
|---|---|---|
| K1 | Per-tab metric | `browser.new_page()` = 1 tab |
| K2 | Credential & browser location | Local |
| K3 | Subscription tier Phase 1 | Dev/free only (dashboard Phase 3) |
| K4 | Anti-piracy | Binary + license gate |
| K5 | Protected layer | Main MCP code via binary distribution |
| K6 | Counter sync | Real-time per-tab (fail-fast) |
| K7 | Hardware-bound key | Tidak untuk Phase 1 |

Detail lengkap: `refactor/90_decisions_log.md`

---

## Alur kerja (workflow)

```
brainstorm → matrix scoring → plan di docs/spec/<slug>/refactor/
→ owner approval → implementation → cross-check → commit
```

**Tidak boleh skip approval gate** (lihat `AGENTS.md` §4).

---

## Quality gates (Phase 1)

Lulus semua di `spec.md` §7 sebelum `state.json` di-archive:

- [ ] functional_mcp_tools
- [ ] per_tab_counter_accurate
- [ ] license_gate_enforced
- [ ] vault_roundtrip
- [ ] build_success
- [ ] tests_pass
- [ ] docs_complete

---

## Hubungi owner

Telegram/chat — lihat memory: `yadenmustopa` (denevill), popOS Linux.

**Diskusi trigger**: perubahan strategi, tambah fitur baru, decision K1-K7
revisit, plan approval.

**Silent OK**: bug fix, internal refactor, test, doc typo.