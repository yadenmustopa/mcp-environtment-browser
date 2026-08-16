# Roadmap Migrasi — Strategi A → Strategi D → Fase 3

> Dokumen ini untuk **agent masa depan** yang baca repo ini dan bertanya
> "arah pengembangan ke mana?" Jawabannya ada di sini.
>
> **JANGAN ubah strategi tanpa diskusi ulang dengan owner (yadenmustopa)**.
> Setiap fase punya trigger yang jelas.

---

## Phase 1 (sekarang) — Strategi A: Local-First + License-Server-Only

**Status**: 📝 DRAFT spec
**Trigger selesai**: Acceptance criteria di `spec.md` §9 terpenuhi

### Karakteristik
- Client = full source + Playwright + libsecret vault + MCP stdio
- Server = FastAPI license DB + per-tab counter only
- Credential & browser = 100% local (K2)
- Per-tab counter = real-time hit server (K6)
- Anti-piracy = distribusi binary + license gate (K5)

### Kapan harus migrasi
- ✅ User base > 100 (license DB mulai tidak feasible manual)
- ✅ Bypass attempts terdeteksi (intercept HTTP, fake quota)
- ✅ Butuh multi-tenant (per-user data isolation)
- ✅ Compliance/security butuh server-side credential (regulated industry)

---

## Phase 2 — Strategi D: Hybrid Credential-From-Server + Local Browser

**Status**: 📋 ROADMAP (belum mulai)
**Trigger mulai**: Salah satu kondisi Phase 1 terpenuhi
**Estimasi effort**: 3-4x Phase 1

### Apa yang berubah
- **Credential vault** pindah ke server (master key server-side)
- Client download **encrypted session key** per login
- Browser tetap local (K2 tidak berubah)
- Workflow scripts di-sign per session (anti-tampering workflow)

### Karakteristik baru
```
┌─────────────────────────────────────────────────────────────────────┐
│ Agent                                                              │
│   │                                                                  │
│   │ MCP stdio                                                       │
│   ▼                                                                  │
│ ┌──────────────────────────────────────────┐                          │
│ │ mcp-env-browser (LOCAL — binary only)    │                          │
│ │ ├── MCP server (stdio)                   │                          │
│ │ ├── Browser executor (Playwright)        │                          │
│ │ └── License + credential client ────┐    │                          │
│ └──────────────────────────────────────┼────┘                          │
│                                        │ HTTPS                          │
│                                        ▼                                │
│ ┌──────────────────────────────────────────┐                          │
│ │ credential-server (REMOTE — main code)  │                          │
│ │ ├── FastAPI                              │                          │
│ │ ├── Master key KDF                       │                          │
│ │ ├── Encrypted vault (per-user)           │                          │
│ │ ├── License DB                           │                          │
│ │ └── Workflow scripts (signed, ephemeral) │                          │
│ └──────────────────────────────────────────┘                          │
└─────────────────────────────────────────────────────────────────────┘
```

### Backward compatibility
- MCP tool signature TIDAK berubah — agent existing tetap works
- Cuma tambah layer auth: `X-Session-Key` header di HTTP
- Local cache credential encrypted blob, decrypt pakai session key

### Yang tetap sama
- Browser local (K2)
- Per-tab counter real-time (K6)
- Multi-agent (MCP stdio)

---

## Phase 3 — Multi-Tenant + Per-Target Rate Limit + Dashboard

**Status**: 📋 ROADMAP (jauh)
**Trigger mulai**: Phase 2 stabil + business validated
**Estimasi effort**: 2-3x Phase 2

### Apa yang ditambah

- **Dashboard UI** (web, **embedded di CLI process** — bukan separate app) untuk
  plan management — pakai Vite + Svelte + Routify + Tailwind. 1 unified URL
  (`localhost:9876`) untuk monitoring + dashboard. User tidak ribet 2 app.
- **Per-target rate limit** — quota per domain (mis: 1000 tabs/bulan untuk
  TikTok, unlimited untuk internal app)
- **Team/Org accounts** — multi-user dengan role (admin, member, viewer)
- **Audit log** — semua akses credential di-log untuk compliance
- **SSO integration** — SAML/OIDC untuk enterprise customer

### Karakteristik baru

- **Dashboard pages**: overview, usage, billing, subscription, settings
- **Auth**: JWT (issued by license server), session cookie di localhost
- **Backend**: tambah billing service (Stripe/Lemon Squeezy), webhook handler
- **Workflow**: tambah analytics + alerting

### Stack Progression

| Phase | Stack | Alasan |
|---|---|---|
| Phase 1 | vanilla JS + plain HTML | 1 page polling, no framework lock-in |
| Phase 3 | Vite + Svelte + Routify + Tailwind | Multi-page, auth, complex state — stack besar = worth it |

Refactor effort Phase 1 → Phase 3: ~2-3 jam (monitoring logic sederhana, port ke Svelte component mudah).

---

## Decision Matrix — Kapan Migrasi?

| Sinyal | Phase 1 OK? | Migrasi Phase 2? | Migrasi Phase 3? |
|---|---|---|---|
| User < 100, dev/testing | ✅ | ❌ | ❌ |
| User 100-1000, license DB manual feasible | ✅ | ⚠️ (monitor) | ❌ |
| User > 1000, multi-tenant demand | ❌ | ✅ | ❌ |
| Bypass attempts terdeteksi | ❌ | ✅ | ❌ |
| Compliance butuh server-side credential | ❌ | ✅ | ❌ |
| Team/Org account diminta | ❌ | ❌ | ✅ |
| Dashboard/Self-service plan | ❌ | ❌ | ✅ |
| > 10k tabs/bulan per customer | ❌ | ⚠️ | ✅ |

---

## Anti-Pattern yang Dihindari

Saat agent (atau developer) membaca roadmap ini dan mulai implementasi
Phase 2/3, **JANGAN** jatuh ke pola ini:

### ❌ Anti-pattern 1: Premature optimization
**Gejala**: Langsung implement Strategi D karena "future-proof"
**Mengapa salah**: Phase 1 sudah cukup untuk validasi pasar. Strategi D 3-4x
effort = 3-4x waktu validasi

### ❌ Anti-pattern 2: Coupled dengan smart_agent
**Gejala**: Import library dari smart_agent, share database, share schema
**Mengapa salah**: smart_agent = sister project dengan goal berbeda. Coupled
= 2 project harus rilis bersamaan

### ❌ Anti-pattern 3: Skip Phase 1, langsung Phase 2
**Gejala**: "Mending langsung Strategi D sekalian"
**Mengapa salah**: Phase 1 = validasi model bisnis (per-tab billing acceptable?).
Kalau Phase 1 gagal, Phase 2 juga gagal. Tanpa validasi = double loss

### ❌ Anti-pattern 4: Vendor lock-in
**Gejala**: Pakai proprietary SDK untuk license server
**Mengalah salah**: Stack harus open (FastAPI + SQLite + libsecret). Kalau
mau pindah cloud provider, harusnya plug-and-play

---

## Catatan untuk Agent Masa Depan

> **Baca ini SEBELUM implementasi apa pun di repo ini.**

1. **Repo status = planning**. Implementasi baru jalan setelah spec di-approve
   oleh owner (`yadenmustopa`)
2. **Stack MIT + Python + FastAPI + Playwright + libsecret**. Jangan switch
   tanpa diskusi
3. **Branch default `master`**. Conventional commits kalau sudah mulai commit
4. **Setiap perubahan ke spec atau roadmap** → diskusi dengan owner dulu.
   Jangan silent update
5. **K1-K7 di `refactor/90_decisions_log.md` adalah keputusan user**. Hormati,
   jangan re-interpret
6. **KISS principle** (sesuai workflow owner): 1 JSON column > 8 field
   individual. 1 file purpose > multi-file premature abstraction
7. **Owner workflow**: brainstorming → matrix scoring 4 strategi → plan di
   `docs/spec/<slug>/refactor/` (multi-file) → approval → implementation.
   Ikuti pola yang sama untuk sub-task baru

---

## Versi Dokumen

- v1 (2026-08-16) — initial, capture K1-K7 + Phase 1 plan