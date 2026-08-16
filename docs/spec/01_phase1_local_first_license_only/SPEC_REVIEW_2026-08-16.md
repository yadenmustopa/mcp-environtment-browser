# Spec Review — Phase 1 (2026-08-16)

> **Tujuan**: Audit komprehensif spec Phase 1 sebelum owner approve dan
> implementasi kode dimulai. Review ini **BUKAN** menggantikan approval
> owner — sesuai `AGENTS.md` §4 + `roadmap_migration.md` "Catatan untuk
> Agent Masa Depan" #4: setiap perubahan ke spec = diskusi owner dulu,
> jangan silent update.
>
> **Metode**: grep-based cross-check 8 file (spec.md + 7 refactor/* +
> knowledge.md + roadmap_migration.md + state.json + README + QUICKREF).
> Setiap klaim punya file:line evidence.

---

## TL;DR

Spec sudah **substansial siap-implementasi**. Stack, K1-K7, strategi A,
acceptance criteria, distribusi binary, monitoring UI semuanya terkunci
dengan rationale jelas.

TAPI ada **3 inkonsistensi internal** yang **harus diputuskan owner**
sebelum implementasi (bukan patching sendiri, sesuai `roadmap_migration.md`
anti-pattern):

| # | Topik | Konflik | File:Line Evidence | Tingkat |
|---|---|---|---|---|
| **I1** | Jumlah MCP tools | **"10 tools"** vs **"13 tools"** | `00_overview.md:45,136` dan `10_mcp_server.md:13` bilang **10**. `spec.md:208-220` (tabel §6.4) list **13**. README + QUICKREF bilang **13**. | **HIGH** — angka di phase contract salah |
| **I2** | Jumlah MCP Prompts | **"2 Prompt"** vs **"3 Prompt"** | `spec.md:299` dan `10_mcp_server.md:427` bilang **"Hanya 2 Prompt"**. Tapi `spec.md:304/350/396` sendiri dokumentasikan **3** prompt (`oauth_confirmation_flow`, `browser_debug_workflow`, **`human_intervention_workflow`**). README + QUICKREF list **3**. Implementasi + test di `10_mcp_server.md:438-494, 552-571` hanya handle **2** (`human_intervention_workflow` hilang dari code path). | **HIGH** — code plan & spec table tidak match |
| **I3** | License endpoint set | Spec + 10_mcp_server vs 20_license_server mismatch | `spec.md:460-465` list 4 endpoint (`/health`, `/license/check`, `/tab/increment`, `/license/register`). `20_license_server.md:18-19, 23-130` punya **5** endpoint — termasuk `GET /tab/usage` (line 98-112) yang **tidak ada** di spec.md §6.5. | **MEDIUM** — extra endpoint tanpa spec decision |

Setelah 3 keputusan itu, spec **siap di-approve**.

---

## 1. Apa yang sudah BENAR ✅

### 1.1 K1-K7 vs Spec vs state.json — **SINKRON**

Cross-check `90_decisions_log.md` K1-K7 ↔ `spec.md` §2 ↔ `state.json.decisions`:

| ID | Topic | decisions_log | spec.md | state.json | Status |
|---|---|---|---|---|---|
| K1 | per-tab = `browser.new_page()` | K1 §K1 (line 17) | spec.md:47 | `K1_per_tab_metric` | ✅ SINKRON |
| K2 | credential & browser local | K2 §K2 (line 32) | spec.md:48 + §6.1 ASCII | `K2_credential_location`, `K2_browser_location` | ✅ SINKRON |
| K3 | Phase 1 = dev/free | K3 (line 49) | spec.md:49 | `K3_subscription_model` | ✅ SINKRON |
| K4 | Strategi A = license DB only | K4 (line 63) | spec.md:50, §4 | `K4_anti_piracy_strategy` | ✅ SINKRON |
| K5 | Binary distro + license gate | K5 (line 79) | spec.md:51, §6.4 line 177 | `K5_protected_layer` | ✅ SINKRON |
| K6 | Real-time per-tab hit server | K6 (line 99) | spec.md:52, §6.3 | `K6_counter_sync`, `K6_unregistered_user` | ✅ SINKRON |
| K7 | No TPM2 Phase 1 | K7 (line 115) | spec.md:53 | `K7_hardware_bound_key` | ✅ SINKRON |

### 1.2 Stack konsisten

`spec.md` §Stack (line 28-32) ↔ `AGENTS.md` §3 default decisions
↔ `knowledge.md` §1-7 ↔ `refactor/30_client_arch.md` ↔ `refactor/40_distribution.md`:

- Python 3.10+ ✅
- FastAPI ✅
- Click ✅
- Playwright ✅
- libsecret (via secretstorage) ✅
- MIT, branch master ✅

### 1.3 Strategi A rationale kuat

`spec.md` §4 matrix scoring `22/25` (juara). Trade-off sadar di §4
(yang Anda korbankan). `00_overview.md` §"Why Quick Split" alignment.
`roadmap_migration.md` §Anti-pattern (4 anti-patterns terdaftar) solid.

### 1.4 Acceptance criteria measurable

`spec.md` §7 = **10 quality gates**. §9 = **8 acceptance criteria** end-to-end.
Semuanya verifiable (test/FastAPI TestClient/locust). TIDAK ada yang vague.

### 1.5 Web monitoring companion — well-scoped

`spec.md` §6.6.1 stack decision matrix benar:
- Phase 1 vanilla JS + plain HTML ✅ (no framework lock-in)
- Phase 3 Vite + Svelte + Routify + Tailwind (deferred)
- Alasan "kenapa tidak X" untuk 4 alternatif tercatat

`AGENTS.md` §3 / `QUICKREF.md` default stack konsisten.

### 1.6 Phase 2+ deferral rapi

`spec.md` §8 (mitigasi), `roadmap_migration.md` Phase 2/3, `decisions_log.md`
§"Diskusi yang TIDAK Diputuskan" — semuanya **defensive deferral** (OAuth
auto-refresh, multi-tenant, TPM2, dll) tanpa over-engineering Phase 1.

### 1.7 Anti-over-engineering self-check konsisten

`95_anti_overengineering_guard.md` 7-point checklist +
`roadmap_migration.md` 4 anti-patterns + `AGENTS.md` §5 7 failure modes —
**3 source mutu** untuk KISS gate. Solid.

### 1.8 Honest gate status

`spec.md` §7 pakai `[ ]` (unchecked), `state.json.quality_gates` pakai
`"pending"` (bukan `"passed"`-premature) — sesuai `AGENTS.md` §8
"`skipped` ≠ `passed`".

---

## 2. Inkonsistensi Internal (WAJIB DISKUSI OWNER)

### I1 — Jumlah MCP Tools: 10 vs 13

**SUMBER KONFLIK**:

| Sumber | Klaim | Baris |
|---|---|---|
| `spec.md` §6.4 (tabel Tools) | **13 tools** (list `smart_list_credentials`, `smart_get_credential_meta`, `smart_set_credential`, `smart_delete_credential`, `smart_connect_browser`, `smart_list_sessions`, `smart_close_browser`, `smart_browser_action`, `smart_browser_console_log`, `smart_browser_network_log`, `smart_browser_inspect`, `smart_session_pause`, `smart_session_resume`) | spec.md:208-220 |
| `00_overview.md` (Scope Contract + Implementation Order) | **"10 MCP tools"** | 00_overview.md:45, 136 |
| `10_mcp_server.md` (Module Map comment) | **"exposes 10 tools"** | 10_mcp_server.md:13 |
| `README.md` | "13 MCP Tools + 3 MCP Prompts" | README.md:31 |
| `QUICKREF.md` | "13 Tools + 3 Prompts" | QUICKREF.md:27 |

**DIAGNOSIS**: spec.md konsisten dengan README/QUICKREF (13). File
`00_overview.md` + `10_mcp_server.md` Module Map comment keliru copy-paste
dari draft awal yang hanya punya 10 tool (sebelum pause/resume + meta di-
tambah). Hitung manual baris 208-220 spec.md = **13** tools.

**OPSI RESOLUSI** (perlu dipilih owner):

- **Opsi A** (canonical): spec.md = sumber kebenaran (13). Patch
  `00_overview.md` line 45, 136 dari "10" → "13". Patch
  `10_mcp_server.md` line 13 dari "10 tools" → "13 tools".
  Effort: 1 commit `docs(spec):` 3 line edits.

- **Opsi B** (de-scope): specs decide 13 terlalu banyak, drop sampai
  10. Tapi `smart_get_credential_meta`, `smart_session_pause`,
  `smart_session_resume` punya purpose kuat di §6.4 + knowledge
  → drop = lose functionality untuk user-replacement goal §6.4
  (CRITICAL untuk 2FA/CAPTCHA workflow). Tidak disarankan.

- **Opsi C** (re-brainstorm): rancang ulang tool set. **Tidak
  sesuai §2 AGENTS.md** — 13 tools punya rationale.

**REKOMENDASI**: **Opsi A**. Numerik doang, batch dengan opsi I2.

---

### I2 — Jumlah MCP Prompts: 2 vs 3

**SUMBER KONFLIK**:

| Sumber | Klaim | Baris |
|---|---|---|
| `spec.md` §6.4.1 opening | **"Hanya 2 Prompt"** (dari 4 goal, 2 di-defer ke Phase 2) | spec.md:299-302 |
| `spec.md` §6.4.1 Prompt 1 (`oauth_confirmation_flow`) | spec lengkap | spec.md:304-346 |
| `spec.md` §6.4.1 Prompt 2 (`browser_debug_workflow`) | spec lengkap | spec.md:350-394 |
| `spec.md` §6.4.1 Prompt 3 (`human_intervention_workflow`) | **spec lengkap juga!** | spec.md:396-456 |
| `10_mcp_server.md` §"Hanya 2 Prompt" + implementation | 2 prompt (`oauth`, `browser_debug`) — `human_intervention_workflow` TIDAK ada di code path | 10_mcp_server.md:427, 438-494, 552-571 |
| `README.md` | "3 MCP Prompts" (termasuk `human_intervention_workflow`) | README.md:31 |
| `QUICKREF.md` | "3 Prompts (oauth_confirmation_flow, browser_debug_workflow, human_intervention_workflow)" | QUICKREF.md:27 |

**DIAGNOSIS**: spec.md sendiri kontradiktif — opening bilang 2, tapi
mendokumentasikan 3 dengan Prompt 3 fully-specified (termasuk schema,
arguments, return messages, implementation note). `10_mcp_server.md` implementasi
+ test hanya handle 2. `human_intervention_workflow` hilang dari code path.
README/QUICKREF eksternal sudah menyebut 3.

`human_intervention_workflow` adalah goal utama user-replacement pattern
(`spec.md` §6.4 "Bedah tambahan tools (untuk user-replacement goal)").
Drop = lose core differentiator.

**OPSI RESOLUSI** (perlu dipilih owner):

- **Opsi A** (canonical 3 prompt): specs sudah keep 3 (sesuai §6.4.1
  Prompt 3 body). Patch `spec.md:299` opening dari "Hanya 2 Prompt"
  → "**3 Prompt**". Patch `10_mcp_server.md:427` sama. **Tambah**
  `human_intervention_workflow` ke `list_prompts()` + `get_prompt()` +
  test di `10_mcp_server.md:438-494, 552-571`. Effort: 1 commit
  `docs(spec):` + 1 commit `feat(mcp):` (Prompt 3 implementation +
  test). Total ~50-80 LOC.

- **Opsi B** (canonical 2 prompt, deprecate Prompt 3): Drop
  `human_intervention_workflow` dari spec (hapus §6.4.1 Prompt 3
  entirely). Update README + QUICKREF ke "2 Prompts". Lose core
  differentiator user-replacement goal. **Tidak disarankan**.

- **Opsi C** (re-brainstorm goals analysis): keep 2 asli (oauth + browser_debug),
  defer human_intervention ke Phase 2 dengan rationale "agent belum tentu
  detect visual challenge di Phase 1, validate use case dulu". Spec
  opener "Hanya 2 Prompt di Phase 1" akurat, tapi §6.4.1 Prompt 3 harus
  di-strikethrough atau dipindah ke Phase 2 section. Effort: medium,
  butuh update banyak file.

**REKOMENDASI**: **Opsi A**. Owner sudah invest 60+ baris spec untuk
Prompt 3 (termasuk 7-step pause/resume flow). Implementasi cost rendah
(50-80 LOC + 2 test cases — sama dengan Prompt 2). Sesuai AGENTS.md
§1 "tidak ada silent decision change".

---

### I3 — License Endpoint Set: 4 vs 5

**SUMBER KONFLIK**:

| Sumber | Klaim | Endpoint Listed |
|---|---|---|
| `spec.md` §6.5 (tabel) | **4 endpoint**: `/health` (GET), `/license/check` (POST), `/tab/increment` (POST), `/license/register` (POST) | spec.md:460-465 |
| `20_license_server.md` §Endpoints | **5 endpoint**: + `GET /tab/usage` (line 98-112) | 20_license_server.md:25-130 |
| `state.json.quality_gates` | Tidak list endpoint secara eksplisit | — |

**DIAGNOSIS**: `GET /tab/usage` (`20_license_server.md:98-112`) added
untuk agent/UI self-check usage. Schema lengkap (200 response, query
string auth). Tapi **tidak ada di spec.md §6.5** (dianggap SSOT contract)
dan tidak ada di `00_overview.md` Scope Contract. Inkonsistensi minor
karena endpoint read-only, tapi tetap membersarakan surface area tanpa
spec decision.

**OPSI RESOLUSI**:

- **Opsi A** (canonical 5): tambah `/tab/usage` ke `spec.md` §6.5 tabel.
  Justifikasi: read-only, untuk UI/self-check. Phase 1 dashboard akui
  monitoring perlu tahu usage tanpa increment. Effort: 1 baris di
  spec.md.

- **Opsi B** (canonical 4): hapus `GET /tab/usage` dari
  `20_license_server.md` sampai trigger konkret di Phase 1 (monitoring
  UI §6.6 belum pakai endpoint ini — hanya panggil
  `/api/sessions` di browser module).

**REKOMENDASI**: **Opsi B**. `spec.md` §6.6 monitoring panggil
`/api/sessions` (browser module local) — bukan `/tab/usage` (license
server). Endpoint read-only ini **speculative** tanpa caller di Phase 1.
Sesuai `95_anti_overengineering_guard.md` §"No Speculative Config" —
kalau belum dipakai 2+ caller = STOP. Effort: 1 commit hapus 15 baris
di `20_license_server.md:98-112`.

---

## 3. Missing Documentation (Minor, Non-Blocking)

### M1 — `01_phase1_local_first_license_only/refactor/45_monitoring.md` terdaftar di ls, tapi tidak ada di spec.md §10 "Cross-Reference"

`spec.md` §10 list 6 file refactor (00, 10, 20, 30, 40, 90). Tapi
`ls` di spec folder show **8 file refactor** termasuk
`45_monitoring.md` (339 lines) + `95_anti_overengineering_guard.md`
(164 lines). **Missing 45_monitoring.md** di spec.md Cross-Reference.
Effort: 1 baris append di `spec.md` §10. SIDE NOTE:
`95_anti_overengineering_guard.md` juga tidak ada di §10 (tapi
merujuk dari spec.md §6.4.1 line 301 — accepted ommission).

### M2 — `state.json` tidak punya `related_specs` atau `cross_refs` array

`state.json` punya `related_repos` (smart_agent, cua-driver) tapi tidak
ada pointer ke spec.md internal sections. Minor — file pakai path
string di spec.md §10 sudah cukup untuk navigasi manusia.

### M3 — Phase 2 §4 spec.md line 110 menyebut "credential vault logic reusable" tapi tidak ada blueprint

Sudah ada di `roadmap_migration.md:69-77` "Backward compatibility".
Sudah cukup. Non-issue.

### M4 — `40_distribution.md` + `45_monitoring.md` belum saya baca deep (hanya ls)

Sized 283 + 339 lines. Asumsi tidak ada inkonsistensi besar (perlu
sweep tambahan kalau owner approve), tapi **bukan blocker** untuk
approval saat ini.

---

## 4. Yang TIDAK Perlu Diskusi (Minor Cleanup, Owner Bisa Skip)

### C1 — spec.md punya typo karakter Mandarin/CJK di beberapa baris

- `spec.md:254` "Tab
- `spec.md:397` "User-Replacement Pattern"
- `spec.md:652` "Penting"
- `spec.md:697` "典型" (= karakter Mandarin untuk "typical")
- `spec.md:741` "Padding"
- `spec.md:744` "Pause tidak release browser"

Typo karakter non-ASCII tidak masalah untuk owner yang baca mixed-language,
tapi kalau mau bilingual formal ING-only = batch replace di
deadline implementasi. **TIDAK HIGH priority**.

### C2 — numbering section spec.md kadang berbahasa Indonesia campur

§1-3 English, §6.4.1 prompt templates mix. Acceptable per QUICKREF
"agent boleh jawab mix, tapi doc resmi = English" (AGENTS.md §8).
Bisa di-fix di cleanup pass atau di-defer.

---

## 5. Quality Gates Consistency

`spec.md` §7 = 10 quality gates:
1. Functional (semua tool end-to-end via Hermes)
2. Per-tab counter (simulasi 100 tabs)
3. License gate
4. Vault roundtrip
5. Web monitoring
6. Session identity (multi-tab clarity)
7. Click-to-act
8. Build
9. Tests ≥80% coverage
10. Docs README + install.sh

`state.json.quality_gates` = 7 keys:
- `functional_mcp_tools`
- `per_tab_counter_accurate`
- `license_gate_enforced`
- `vault_roundtrip`
- `build_success`
- `tests_pass`
- `docs_complete`

MISSING di state.json (ada di spec.md §7 tapi belum di-mirror ke
state.json): `web_monitoring`, `session_identity`, `click_to_act`.

Effort rendah: tambah 3 keys di state.json (status `"pending"`). Owner
disagree = skip — quality_gates state.json adalah ringkasan, spec.md
§7 adalah sumber.

---

## 6. Tanda Bahaya (Sesuai AGENTS.md §7) — CLEAN ✅

| Red Flag | Status |
|---|---|
| Tambah dependency baru tanpa trigger | ✅ Tidak ada — semua deps di spec konsisten dengan stack lock |
| File baru di `refactor/` tanpa update `spec.md` | ✅ Tidak ada |
| Schema/config berubah dari §6 | ⚠️ I3 (`/tab/usage` — endpoint extra tanpa spec) |
| MCP tool signature berubah dari `10_mcp_server.md` | ⚠️ I1 + I2 (jumlah mismatch) |
| License server endpoint signature berubah dari `20_license_server.md` | ⚠️ I3 (extra `/tab/usage`) |
| Counter mechanism berubah dari K6 | ✅ Tidak ada |
| Attempt import dari `smart_agent` | ✅ `knowledge.md` §7 eksplisit NOT REUSE |
| Implementasi Strategi D di Phase 1 | ✅ Tidak ada — Strategi A strict |
| Migration ke Phase 2/3 tanpa trigger | ✅ Tidak ada |

**3 red flag terkonsentrasi di I1 + I2 + I3** — semua resolvable.

---

## 7. Rekomendasi Tindakan (untuk Owner Approval)

### Tier 1 — WAJIB PUTUSKAN (block approval)

| ID | Opsi | Effort | Dampak |
|---|---|---|---|
| **I1** Tools 10 vs 13 | A (canonical 13, patch angka di overview+module map) | 1 commit, 3 line edits | Numeric konsistensi |
| **I2** Prompts 2 vs 3 | A (canonical 3, tambah implementasi Prompt 3 di 10_mcp_server.md) | 2 commits (docs + feat ~50-80 LOC + 2 tests) | Sesuai spec opening goal user-replacement |
| **I3** Endpoint set 4 vs 5 | B (hapus `/tab/usage` dari 20_license_server.md) | 1 commit, 15 baris removed | Anti-speculative endpoint |

### Tier 2 — Optional cleanup (non-blocking)

- M1: tambah `45_monitoring.md` ke spec.md §10 Cross-Reference
- §5: tambah 3 missing quality_gates keys ke state.json
- C1 + C2: cleanup typo/character batch (post-approval, pre-impl)

| **Tier 3** — Verify post-approval

- M4: deep sweep `40_distribution.md` + `45_monitoring.md` untuk
  inkonsistensi (bukan blocker approval, sanity-check pre-impl)

---

## 9. Companion Document: PLAN_PHASES.md

Detail task breakdown per phase (9 phase × done definition × mermaid
flow × commit spec × dependency graph) ada di companion
[`PLAN_PHASES.md`](./PLAN_PHASES.md). Dokumen ini dibangun goal-first:

- §1 Goal Tree (G0 root → G1-G8 leaf) — WHY
- §2 Master Flow (single mermaid end-to-end)
- §3 Detail per Phase 1-9 — file to create, source evidence
  (spec/refactor:line), tasks, done definition, commit, mermaid
- §4 Dependency Graph (sequence + parallelisasi)
- §5 Done Definition (Phase 1 closure 8 criteria + 10 quality gates)
- §6 Honest Risk Register (per-phase)
- §7 Rationale kenapa bukan batch besar (sesuai owner commit preference)

---

## 8. Honest Assessment — Status Spec

| Aspek | Status |
|---|---|
| **Strategi (A) & K1-K7 rationale** | SOLID (matrix scoring, capture diskusi lengkap) |
| **Stack lock** | SOLID (Python + FastAPI + Click + Playwright + libsecret, MIT) |
| **Scope IN/OUT** | SOLID (16 OUT OF SCOPE explicit di 00_overview, semuanya deferral valid) |
| **Acceptance criteria** | SOLID (8 measurable di §9 + 10 quality gates di §7) |
| **Implementation order** | SOLID (00_overview Quick Win Sequence 9 step) |
| **Test strategy** | SOLID (unit + integration + manual Hermes) |
| **Anti-over-engineering guard** | SOLID (3 layer: AGENTS §5, guard checklist, roadmap anti-pattern) |
| **Internal consistency** | ⚠️ 3 inkonsistensi materiil (I1, I2, I3) — all resolvable |
| **Phase 2/3 deferral** | SOLID (anti-pattern catalog + Decision Matrix) |
| **Ready for approval?** | **Ya, setelah 3 keputusan Tier 1** |

---

## Versi

- v1 (2026-08-16) — initial review based on grep sweep + cross-check
  8 source files. Owner belum respond.
