# Anti-Over-Engineering Guard

> Auto-check (mental checklist) yang harus dijalankan agent/developer
> **sebelum** menambah kode, dependency, atau abstraksi baru.

---

## 🚨 Golden Rule

> **Default ke opsi paling sederhana yang memenuhi goal.**
> Owner workflow (verified): "schema terlalu gemuk tidak acceptable".
> K7 (Phase 1): "buat simple saja buat memastikan apakah bisa atau tidak".

---

## 7-Point Checklist (Jalankan Sebelum Setiap Perubahan)

Jawab **ya/tidak** untuk setiap pertanyaan. Kalau ada **⚠️ ya**, jangan
lanjutkan dulu.

### 1. Trigger
> Apakah perubahan ini di-trigger oleh bug nyata atau requirement eksplisit?

- ✅ **Ya** = OK
- ⚠️ **Tidak / "future-proof" / "best practice"** = STOP, diskusi owner

### 2. Simplest Alternative
> Apakah ada cara **lebih sederhana** untuk achieve tujuan yang sama?

- ✅ **Ya, dan saya pakai** = OK
- ⚠️ **Tidak yakin / ada yang lebih simple** = cari dulu, bandingkan

### 3. No Premature Abstraction
> Apakah saya menambah **file/kelas/abstraksi** yang tidak dipakai oleh 2+ caller?

- ✅ **Tidak** = OK
- ⚠️ **Ya, "just in case"** = STOP, hardcode dulu

### 4. Dependency Discipline
> Apakah saya menambah **dependency baru** yang belum dipakai di tempat lain?

- ✅ **Tidak** = OK
- ⚠️ **Ya, transitive / "might be useful"** = STOP, justify dengan use case konkret

### 5. Schema Minimalism
> Apakah schema/config **lebih gemuk** dari yang dibutuhkan?

- ✅ **Tidak, minimal fields** = OK
- ⚠️ **Ya, "extensible for future"** = STOP, KISS: 1 JSON > 8 fields

### 6. No Speculative Optimization
> Apakah saya menambahkan **layer caching/rate-limit/retry** tanpa trigger konkret?

- ✅ **Tidak** = OK
- ⚠️ **Ya, "for performance"** = STOP, ukur dulu baru optimize

### 7. No Speculative Config
> Apakah saya membuat **config option** yang owner belum minta?

- ✅ **Tidak** = OK
- ⚠️ **Ya, "in case user wants"** = STOP, hardcode dulu

---

## Decision Flowchart

```
                    Mau tambah kode/dependency/abstraksi?
                              │
                              ▼
                Trigger eksplisit dari owner/bug nyata?
                              │
              ┌───────────────┴───────────────┐
              │                               │
             TIDAK                          YA
              │                               │
              ▼                               ▼
         Ada cara                       Tambah OK
         lebih simple?                       │
              │                               ▼
        ┌─────┴─────┐                  Lulus 7-point
        │           │                  checklist?
    YA (pakai)  TIDAK                      │
        │      (diskusi)            ┌──────┴──────┐
        ▼           │              │             │
    Pakai          ▼             YA            TIDAK
    simpler    Tanya owner         │             │
    alt.        dulu               ▼             ▼
        │                         │          STOP,
        ▼                         ▼          diskusi
      Done                   Implementation   owner
```

---

## Examples — Kapan Diskusi Owner Diperlukan

### ✅ BOLEH tanpa diskusi

| Situasi | Alasan |
|---|---|
| Bug fix: `httpx` raise exception bukan `dict` | Trigger: bug nyata |
| Tambah type hint di existing function | Internal improvement, tidak改变 behavior |
| Ganti `dict` → `TypedDict` untuk existing config | Clarify existing, bukan tambah field |
| Tambah pytest untuk existing function | Coverage up |
| Update doc typo | Doc clarity |

### ⚠️ STOP — diskusi owner dulu

| Situasi | Alasan |
|---|---|
| "Tambah `smart_oauth_refresh` tool untuk auto-refresh token" | Premature — belum ada user konkret |
| "Extract `VaultBackend` Protocol + factory untuk Windows/Mac adapter" | Premature abstraction — belum butuh Windows/Mac |
| "Tambah `MCP_CACHE_LICENSE_TTL` config option untuk caching 5 menit" | Speculative optimization — K6 explicit real-time |
| "Pakai Postgres + Redis instead of SQLite" | Database over-engineering — Phase 1 SQLite cukup |
| "Tambah dependency `pydantic-settings` untuk config management" | Dependency bloat — pakai JSON file sudah cukup |
| "Refactor `executor.py` jadi `BaseExecutor` + 3 subclass per browser type" | Premature abstraction — Phase 1 Chromium only |
| "Buat microservice: auth-service, billing-service, rate-service" | Microservice sprawl — monolith FastAPI cukup |

---

## Override Conditions (Kapan Owner Pre-Approved)

Situasi di mana agent **tidak perlu diskusi**, karena sudah disetujui di
spec atau AGENTS.md:

- ✅ Implementasi sesuai `refactor/10_mcp_server.md` (10 tools yang sudah listed)
- ✅ Implementasi sesuai `refactor/20_license_server.md` (endpoints yang sudah listed)
- ✅ Bug fix yang tidak改变 signature di spec
- ✅ Test coverage up sesuai target 80%
- ✅ Conventional commit message dengan scope
- ✅ Doc clarification non-decision

**Kalau di luar list di atas → diskusi owner dulu.**

---

## Tanda Anda Sedang Over-Engineering

Self-check 6 red flags:

1. 🚩 File baru yang **tidak ada di `refactor/` plan**
2. 🚩 Dependency baru **tidak di pyproject.toml spec** (`30_client_arch.md`)
3. 🚩 MCP tool baru **tidak ada di `10_mcp_server.md`**
4. 🚩 Endpoint baru **tidak ada di `20_license_server.md`**
5. 🚩 Config field baru **tidak ada di `30_client_arch.md` §Config File**
6. 🚩 Abstraction baru yang tidak dipakai 2+ caller

Kalau ada 1+ red flag, **STOP — diskusi owner**.

---

## Catatan Owner (Dari Memory Session)

> Workflow owner: brainstorming → matrix scoring → plan di `docs/spec/<slug>/refactor/`
> (multi-file) → approval → implementation.
>
> Tuan Yaden KISS preference kuat: schema "terlalu gemuk" tidak acceptable.
> Kalau 1 JSON bisa encapsulate 8 field individual, pakai 1 JSON.

---

## Versi

- v1 (2026-08-16) — initial, 7-point checklist + decision flowchart + examples