# Agent Strict Guidelines — mcp-environtment-browser

> **WAJIB BACA** sebelum agent (atau developer) melakukan perubahan apa pun
> di repo ini. Dokumen ini meng-encode **prinsip owner (yadenmustopa)**
> supaya agent tidak over-engineer dan tetap di jalur paling sederhana.

---

## 🚨 The Golden Rule

> **Default ke opsi paling sederhana yang memenuhi goal.**
> Jangan tambahkan fitur, layer, atau abstraksi tanpa trigger eksplisit
> dari owner. **Jika ragu, pilih yang lebih simple — bukan yang lebih
> powerful.**

---

## 1. Batasan Strategi (JANGAN DIUBAH TANPA DISKUSI OWNER)

### ❌ TIDAK BOLEH — sudah diputuskan di K1-K7

| Topik | Keputusan tetap | Jangan |
|---|---|---|
| Per-tab metric | `browser.new_page()` = 1 tab | ❌ Jangan ganti ke network request / wall-clock / action event |
| Credential location | Local (libsecret) | ❌ Jangan pindah ke server tanpa trigger (lihat `roadmap_migration.md` §Phase 2) |
| Browser location | Local (Playwright) | ❌ Jangan host di cloud / pakai browser farm |
| License tier (Phase 1) | Dev/free only | ❌ Jangan tambah tier baru / Stripe / billing logic |
| Anti-piracy | Binary distro + license gate | ❌ Jangan tambah obfuscation / DRM / TPM di Phase 1 |
| Counter sync | Real-time per-tab | ❌ Jangan ganti ke batch sync (akan weaken license gate) |
| Hardware-bound key | TIDAK untuk Phase 1 | ❌ Jangan tambah TPM2/scrypt master key di Phase 1 |
| Stack | Python + FastAPI + Click + Playwright | ❌ Jangan switch ke Node.js/Go/Rust |
| Lisensi repo | MIT | ❌ Jangan ganti ke proprietary/BSL |
| Branch default | `master` | ❌ Jangan rename ke `main` |
| Strategi | A. Local-first + license-only | ❌ Jangan lompat ke Strategi D |

### ✅ BOLEH dengan diskusi owner

- Bug fix yang tidak改变 arsitektur
- Deps upgrade yang aman (patch version)
- Test coverage improvement
- Doc clarification (no decision change)
- Refactor internal yang **tetap di Strategi A**

### ⚠️ BUTUH PERSETUJUAN EKSPLISIT OWNER

- Tambah MCP tool baru (cek dulu apakah `smart_*` yang sudah ada cukup)
- Tambah credential type baru (Phase 1: 4 types, jangan expand tanpa trigger)
- Tambah backend/platform support (Windows/macOS = Phase 2)
- Tambah workflow logic baru (login flow per target)
- Performance optimization (caching, prefetch, dll)
- Security hardening di luar scope K1-K7

---

## 2. Anti-Over-Engineering Checklist

Sebelum **setiap perubahan kode**, jawab 7 pertanyaan ini.
Kalau ada jawaban "ya" di pertanyaan bertanda ⚠️, **jangan lanjutkan dulu** —
diskusi dengan owner.

| # | Pertanyaan | ⚠️ |
|---|---|---|
| 1 | Apakah perubahan ini **di-trigger oleh bug nyata atau requirement eksplisit**? | ya |
| 2 | Apakah ada cara **lebih sederhana** untuk achieve tujuan yang sama? | ya |
| 3 | Apakah saya menambah **file/kelas/abstraksi** yang tidak dipakai oleh 2+ caller? | ya |
| 4 | Apakah saya menambah **dependency baru** yang belum dipakai di tempat lain? | ya |
| 5 | Apakah schema/config **lebih gemuk** dari yang dibutuhkan? | ya |
| 6 | Apakah saya menambahkan **layer caching/rate-limit/retry** tanpa trigger konkret? | ya |
| 7 | Apakah saya membuat **config option** yang owner belum minta? | ya |

**Prinsip KISS owner**: 1 JSON column > 8 field individual. 1 file purpose >
multi-file premature abstraction.

---

## 3. Default Decisions (Owner Pre-Approved)

Saat ada **ambiguitas implementasi**, agent tidak perlu tanya owner untuk
pilihan-pilihan ini. Default = opsi paling sederhana.

| Situasi | Default (pilih ini) | Alternatif (jangan kecuali trigger) |
|---|---|---|
| HTTP client | `httpx` sync | `aiohttp`, `requests` |
| Async pattern | Wrap sync di `asyncio.to_thread` | Native async Playwright |
| JSON schema | `pydantic` v2 | `dataclass`, `TypedDict` |
| Logging | `structlog` ke stderr | `print`, custom logger |
| Testing | `pytest` + `pytest-asyncio` | `unittest`, `nose` |
| Linting | `ruff` | `flake8`, `pylint` |
| Type checking | `mypy --strict` (incremental) | relaxed mode |
| Config format | JSON file di `~/.config/mcp-env-browser/` | YAML, TOML, env-only |
| CLI framework | `click` | `typer`, `argparse` |
| Build system | `pyproject.toml` (PEP 621) | `setup.py`, Poetry-only |
| Binary build | PyInstaller `--onefile` | Nuitka, cx_Freeze |
| MCP transport | stdio | SSE, HTTP |
| Credential encryption | libsecret (OS handle) | Custom AES-GCM |
| Migration tool | `alembic` | Custom SQL, peewee |
| Test coverage target | 80% | 100% (overkill untuk Phase 1) |
| Documentation | Markdown di `docs/spec/` | Sphinx, mkdocs |

---

## 4. Workflow Approval Gates

Sesuai workflow owner (verified di session sebelumnya):

```
Brainstorm → Matrix scoring 4 strategi → Plan di docs/spec/<slug>/refactor/
→ Owner approval → Implementation
```

| Action | Butuh owner approval? |
|---|---|
| Update `spec.md` (status, quality_gates, decisions) | **Ya** |
| Update `state.json` (transisi fase, decisions) | **Ya** |
| Tambah file di `refactor/` | **Ya** |
| Edit `roadmap_migration.md` (mengubah arah strategi) | **Ya, diskusi ulang** |
| Edit `90_decisions_log.md` K1-K7 | **TIDAK — file ini capture, jangan edit** |
| Bug fix di kode yang belum ditulis | **N/A** |
| Implementation sesuai plan yang sudah disetujui | **Tidak, langsung eksekusi** |
| Convention/formatting change (commit message, doc style) | **Tidak, asal konsisten** |

---

## 5. Failure Modes yang Harus Dihindari

### ❌ Premature Abstraction
**Gejala**: Bikin `VaultBackend` Protocol + factory + 3 adapter saat baru butuh 1
**Fix**: Hardcode SecretStorage dulu. Refactor ke Protocol saat butuh backend kedua.

### ❌ Speculative Features
**Gejala**: Tambah `oauth_auto_refresh` padahal cuma 1 user pakai static token
**Fix**: Implement minimal, tambah auto-refresh saat user konkret minta.

### ❌ Configuration Explosion
**Gejala**: 15 config options di `config.json`, hanya 3 yang dipakai
**Fix**: Hardcode constant. Config cuma untuk hal yang **user-facing**.

### ❌ Dependency Bloat
**Gejala**: `pyproject.toml` punya 20 deps, banyak yang transitif
**Fix**: Tambah dep baru harus ada di PR diff dengan alasan konkret.

### ❌ Microservice Sprawl
**Gejala**: Pecah license server jadi 4 service (auth, billing, rate-limit, audit)
**Fix**: Monolith FastAPI dulu. Split saat bottleneck konkret muncul.

### ❌ Database Over-Engineering
**Gejala**: Pakai Postgres + Redis + Kafka untuk Phase 1 dev/free tier
**Fix**: SQLite cukup untuk Phase 1. Postgres = Phase 2.

### ❌ API Surface Bloat
**Gejala**: 30 MCP tools, kebanyakan cuma wrapper tipis
**Fix**: 10 tools cukup untuk Phase 1 (lihat `10_mcp_server.md`). Tambah saat use case nyata muncul.

### ❌ Documentation Theatre
**Gejala**: Tulis 1000-line README dengan diagram ASCII + ASCII art banner
**Fix**: Doc secukupnya untuk onboarding. Update kalau ada perubahan, bukan untuk kelihatan lengkap.

---

## 6. Saat Ragu — Tanya Diri Sendiri

Tanyakan 5 pertanyaan ini dalam urutan. Kalau semua jawabannya "ya", lanjut. Kalau ada "tidak", STOP.

1. **Apakah owner eksplisit minta ini?** (cek memory/chat/spec — bukan asumsi)
2. **Apakah ini bisa di-defer ke Phase 2 tanpa merusak Phase 1?**
3. **Apakah saya menggunakan library/pattern yang sudah lazim?**
4. **Apakah solusi ini, kalau dibaca 6 bulan dari sekarang, masih masuk akal?**
5. **Apakah solusi ini solve problem riil, atau problem imajiner?**

---

## 7. Signal Bahaya (🚩)

Saat agent melihat salah satu dari ini di kode atau PR, **flag untuk diskusi owner**:

- 🚩 Tambah dependency baru tanpa trigger konkret
- 🚩 Tambah file baru di `refactor/` tanpa update `spec.md`
- 🚩 Schema/config berubah dari yang ada di `spec.md` §6
- 🚩 MCP tool signature berubah dari `10_mcp_server.md`
- 🚩 License server endpoint signature berubah dari `20_license_server.md`
- 🚩 Counter mechanism berubah dari `K6` decision
- 🚩 Ada attempt untuk import dari `smart_agent` (sister project, NOT REUSE)
- 🚩 Ada attempt implementasi Strategi D di Phase 1 (premature)
- 🚩 Ada rencana migration ke Phase 2/3 tanpa trigger eksplisit

---

## 8. Capture Owner Workflow Style

Untuk agent masa depan yang interaksi dengan `yadenmustopa`:

| Owner habit | Implikasi untuk agent |
|---|---|
| Brainstorm dengan matrix scoring | Sebelum implement, present 4 opsi + skor 1-5 |
| "Quick split" > "Clean split" | Pilih strategi yang **sesuai permintaan eksplisit**, bukan yang paling future-proof |
| Direct, low-ceremony | Jangan preamble panjang. Lanjut eksekusi. |
| Bahasa Indonesia + English code-mix | Agent boleh jawab mix, tapi **doc resmi** = English |
| Cross-check sebelum lanjut | Setelah implementasi, audit komprehensif (lihat `spec.md` §7 quality_gates) |
| Honest gate status | `skipped` ≠ `passed`. Kalau belum lulus, tulis `skipped` dengan reason, jangan false-positive |
| Commit conventional + pecah logical | `feat:`, `fix:`, `test:`, `docs:`, `chore:` — bukan 1 bulk commit |
| Security-conscious | Tidak ada password via chat. Manual sudo kalau perlu. Backup sebelum destructive op. |
| Plan di `docs/spec/<slug>/refactor/`, bukan `.hermes/plans/` | Multi-file refactor, bukan single subagent task |
| DRAFT → approval → implementation | Tidak ada kode di-write sebelum owner approve plan |

---

## 9. Checklist Sebelum Commit

Setiap commit harus pass:

- [ ] Tidak违反 §1 (Batasan Strategi)
- [ ] Lulus §2 (Anti-Over-Engineering Checklist)
- [ ] Pakai §3 default decisions (kecuali trigger eksplisit)
- [ ] Pass §4 approval gate
- [ ] Tidak dalam §5 failure modes
- [ ] Tidak trigger §7 signal bahaya
- [ ] Conventional commit message dengan scope
- [ ] Tests pass (kalau applicable)
- [ ] Spec `state.json` ter-update kalau status/spec berubah

---

## 10. Versi Dokumen

- v1 (2026-08-16) — initial, capture owner workflow + KISS principles + anti-over-engineering