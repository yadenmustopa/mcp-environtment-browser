# Decisions Log — K1-K7 + Klarifikasi (CAPTURE)

> **JANGAN HAPUS FILE INI** — ini adalah capture diskusi K1-K7 yang
> menghasilkan strategi A. Agent masa depan butuh context ini untuk
> memahami **mengapa** keputusan diambil, bukan hanya **apa** yang diputuskan.
>
> Setiap entry = 1 klarifikasi. Format: pertanyaan → diskusi → keputusan →
> alasan → implikasi.

---

## K1 — Per-tab = metrik apa?

**Pertanyaan**: "Per-tab billing" — metriknya apa?
**Diskusi**: 4 opsi dievaluasi (browser tab dibuka / network request /
wall-clock session / action event).
**Keputusan**: Setiap `browser.new_page()` atau CDP target baru = 1 tab.
**Alasan**: Paling fair untuk user, mudah diverifikasi di server, mapping
langsung ke usage scrape.
**Implikasi**:
- Counter di client pakai wrapper Playwright (bukan native CDP listener)
- Server endpoint `/tab/increment` accept `amount: int` (default 1) untuk
  batch operations di Phase 2
- MCP tool `smart_connect_browser` jadi titik wajib hit counter

---

## K2 — Credential & browser di mana?

**Pertanyaan**: "Credential di local, browser di local" — konfirmasi.
**Diskusi**: 4 opsi dievaluasi (server farm / hybrid / pure local / dll).
**Keputusan**: **Local** — credential & browser di local user.
**Alasan**: User explicit bilang "tidak berat di server" + "masing-masing
local" — pertanda clear arsitektur client-heavy.
**Implikasi**:
- Server cuma license DB + counter (Strategi A)
- Tidak ada scraping engine di server
- Tidak ada credential di server (zero-knowledge untuk Phase 1)
- Browser pakai Playwright di local — fingerprint blocking risk (mitigasi:
  optional `--disable-blink-features=AutomationControlled`)

---

## K3 — Subscription tiers

**Pertanyaan**: Tier apa untuk Phase 1?
**Diskusi**: Beberapa model (per-tab / per-credential / per-target /
per-user).
**Keputusan**: **Nanti ada dashboard**, tapi Phase 1 = dev/free tier.
**Alasan**: Owner butuh validate model bisnis dulu sebelum lock tier.
**Implikasi**:
- Phase 1 license DB schema flexible (plan field bisa di-extend)
- Default Phase 1 = `plan="dev"`, `tabs_quota=10000` (untuk testing)
- Owner install server di popOS sendiri untuk uji
- Dashboard UI = Phase 3 (lihat roadmap)

---

## K4 — Anti-piracy strategi

**Pertanyaan**: "Kode utama di server" — strategi apa?
**Diskusi**: 4 strategi arsitektur dievaluasi (A/B/C/D).
**Keputusan**: Strategi A — server cuma license DB.
**Alasan**: Owner pilih "Quick split" bukan "Clean split" sesuai workflow
brainstorm → matrix scoring. Trade-off sadar: source visible ke developer.
**Implikasi**:
- Strategi A menjawab K4 partially — kode utama MCP masih di client (source
  visible ke developer)
- Tapi K5 (di bawah) menutup gap via distribusi binary + license gate
- Strategi D (Phase 2) = jawaban penuh untuk K4, di-roadmap

---

## K5 — "Kode penting" yang dilindungi

**Pertanyaan**: Layer mana yang harus dilindungi?
**Diskusi**: 4 layer dievaluasi (decryption flow / scraping workflow /
orchestration / browser primitive).
**Keputusan**: **Kode MCP utama** — agar tidak ditiru/di-copy.
**Alasan**: Owner fokus pada Intellectual Property dari MCP orchestration
logic + per-tab counter logic + license enforcement.
**Implikasi**:
- **Distribusi binary** via PyInstaller/Nuitka untuk end-user (bukan
  distribusi source `.py`)
- **License gate** sebagai enforcement — user tidak terdaftar = tidak bisa
  pakai fitur
- **Sadari**: PyInstaller bisa di-reverse-engineer dengan effort moderate.
  Strategi A sadar akan ini — anti-piracy = **bisnis model + binary distro**,
  BUKAN technical lock
- **Untuk developer** (owner + contributor): source visible OK (MIT)
- **Untuk end-user**: hanya terima binary + license key

---

## K6 — Counter sync model

**Pertanyaan**: Real-time per-tab hit server atau batch?
**Diskusi**: 3 opsi dievaluasi (sync per-tab / batch / hybrid).
**Keputusan**: **Setiap `browser.new_page()` langsung hit server**.
**Alasan**: Owner explicit "kalau user tidak terdaftar di layanan maka agent
tidak bisa menggunakan fitur mcp tersebut" — butuh real-time gate.
**Implikasi**:
- License check + increment = 2 HTTP call per tab
- HTTP timeout 2 detik (fail-fast — agent tahu kalau server mati)
- Cache license check 5 menit (Phase 2) untuk hemat call
- Tidak ada offline mode Phase 1 (kalau server mati = stop)

---

## K7 — Hardware-bound key (TPM2)

**Pertanyaan**: Perlu TPM2-bound key atau simple saja dulu?
**Diskusi**: 3 opsi (server-derived / TPM2-bound / hybrid).
**Keputusan**: **Tidak untuk phase awal. Simple dulu, ada phase migrasi
nanti.**
**Alasan**: Owner explicit "buat simple saja buat memastikan apakah bisa
atau tidak". TPM2 over-engineering untuk validasi pasar.
**Implikasi**:
- Phase 1 pakai `secretstorage` (libsecret) tanpa master key tambahan
- Phase 2 migrasi ke server-derived master key
- Phase 3 mungkin TPM2-bound untuk enterprise tier

---

## Stack — Bahasa & Lisensi

**Pertanyaan**: Bahasa implementasi + lisensi repo?
**Diskusi**: 3 stack dievaluasi (Python / Node.js / Go hybrid), 4 lisensi.
**Keputusan**:
- **Stack**: Python (FastAPI + Click + MCP stdio + Playwright) — score 27/30
- **Lisensi**: MIT — score 5/5 (paling cocok untuk Strategi A)
- **Branch default**: `master` (sesuai permintaan owner)
**Alasan**: Python menang karena reuse smart_agent ecosystem + Playwright
mature + familiar. MIT karena Strategi A sudah jawab K5 via binary + license
gate, source restriction tidak perlu.
**Implikasi**:
- `pip install` workflow untuk user
- `pyproject.toml` standard Python
- Conventional commits mulai dari `feat:` untuk setiap feature

---

## Cross-cutting Decisions

### D1 — Folder path repo
**Keputusan**: `/mnt/nvme/my-job/github/yadenmustopa/mcp-environtment-browser`
**Alasan**: Paralel dengan repo owner lain (smart_agent, mabar-new), pattern
konsisten.

### D2 — Server target install (Phase 1)
**Keputusan**: popOS lokal (owner sendiri), untuk uji Hermes Agent.
**Alasan**: Owner explicit. Production deploy = Phase 2/3.

### D3 — Cross-platform (Phase 1)
**Keputusan**: Linux only Phase 1. Windows/macOS adapter = Phase 2/3.
**Alasan**: Owner pakai popOS. Cross-platform = nice-to-have, bukan
must-have untuk validasi.

### D4 — Naming convention
**Keputusan**:
- Python package: `mcp_env_browser` (underscore)
- CLI command: `mcp-env-browser` (hyphen)
- MCP server name: `mcp-env-browser`
- Spec slug: `01_phase1_local_first_license_only`

**Alasan**: Konsisten dengan ekosistem Python + Nix package naming.

---

## Diskusi yang TIDAK Diputuskan (Defer)

Daftar topik yang muncul di diskusi tapi **tidak diputuskan di Phase 1**
(untuk agent masa depan):

- **OAuth auto-refresh flow** — muncul di requirement awal. Phase 1 hanya
  support `oauth_token` type tanpa auto-refresh. Phase 2 implement.
- **Multi-user / team accounts** — Phase 3.
- **Per-target rate limit** — Phase 3.
- **SSO/SAML** — Phase 3.
- **Audit log retention** — Phase 2 (compliance trigger).

---

## Version Log

- v1 (2026-08-16) — initial capture, K1-K7 + D1-D4 + Defer list