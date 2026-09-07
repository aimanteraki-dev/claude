# Annems AI Marketing Department — Phase 1

Sistem automasi marketing untuk **Annems Leadership Solution Sdn Bhd**.
Ia baca data iklan setiap hari, terangkan apa yang berlaku, jerit bila ada
masalah, dan sediakan creative bila diminta. Manusia buat keputusan — sistem
tak pernah publish, pause, atau ubah budget sendiri.

Spesifikasi penuh ada dalam [`CLAUDE.md`](CLAUDE.md). Kalau README ini
bercanggah dengan `CLAUDE.md`, **`CLAUDE.md` yang menang.**

---

## 1. Apa yang dibina (dan apa yang tidak)

**Phase 1 — siap:**

| Agent | Modul | Kerja |
|---|---|---|
| 1 — Pengumpul Data | `pipeline.py`, `collectors/` | Tarik Meta Insights + GHL, simpan ke Supabase |
| Metric Engine | `metrics.py` | Kira SEMUA nombor (CPL, CTR, CPM, CPC, CVR, CPQL, baseline) |
| 2 — Performance Analyst | `agents/analyst.py` | Diagnosis harian dalam BM |
| 3 — Monitoring / Alert | `agents/monitor.py` | Alert setiap 3 jam bila threshold pecah |
| Reporter | `agents/reporter.py` | Laporan pagi 07:00 + ringkasan Isnin |
| 4 — Penulis Iklan | `agents/ad_writer.py` | 2–3 pilihan creative (ayat + gambar + tag) |
| 5 — Creative QA | `agents/creative_qa.py` | Tapis creative sebelum sampai ke Aiman |

**Phase 2 — SENGAJA TAK DIBINA:**

Agent 6 (Learning Memory) dan Agent 7 (CRM Agent) **tidak wujud dalam repo ini**.
`CLAUDE.md` seksyen 4 letak dua syarat keras sebelum ia boleh dibina:

1. Day-90 review lulus (tiga kriteria dalam seksyen 7, Milestone 5), dan
2. Disiplin pipeline GHL disahkan — setiap lead ditanda dengan konsisten.

Table `learnings` sudah wujud dalam schema supaya gate itu nampak, tapi **tiada
kod yang menulis ke dalamnya**. Jangan bina Agent 7 atas data GHL yang bersepah;
ia akan bagi jawapan salah dengan penuh yakin.

**Juga tak dibina, ikut seksyen 9:** AI CMO, Marketing Strategist agent,
multi-tenant, dashboard/frontend, auto-publish, auto-pause, auto-budget, dan
automasi mesej pelanggan.

---

## 2. Dua prinsip yang menentukan seluruh reka bentuk

**a) LLM tak pernah kira nombor.**
Setiap metrik dikira dalam `metrics.py` — kod biasa, bukan model. LLM hanya
terima JSON yang sudah siap dikira dan tulis penjelasan. Prompt setiap agent
menyatakan larangan ini secara eksplisit. Bila satu nombor tak dapat dikira
(contoh: CPL dengan 0 lead), nilainya `None` dan laporan tunjuk `—`, **bukan
RM0.00**. Sifar palsu lebih bahaya daripada jurang yang jujur.

**b) Keputusan alert dibuat dalam kod, bukan oleh model.**
`monitor.evaluate_rules()` ialah fungsi tulen — tiada database, tiada network,
tiada LLM. Sebab itu ia boleh diuji terus dengan data simulasi. LLM cuma
kemaskan ayat alert, dan kalau ia gagal, mesej mentah (yang sudah lengkap
dengan nombor) tetap dihantar.

---

## 3. Setup

### 3.1 Prasyarat

- Python 3.11+
- Projek Supabase
- Meta app dengan akses `ads_read` ke ad account Annems
- GoHighLevel API key + location ID
- Telegram bot (dari [@BotFather](https://t.me/BotFather))
- OpenAI API key

### 3.2 Pasang

```bash
git clone <repo>
cd claude
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e .

cp .env.example .env      # isi semua nilai
```

### 3.3 Bina database

Buka Supabase SQL editor, paste isi [`db/schema.sql`](db/schema.sql), run.
Fail itu idempotent — selamat run berulang kali.

### 3.4 Sahkan sambungan

```bash
python -m annems healthcheck
```

Output sepatutnya `ok` untuk keempat-empat: supabase, meta, ghl, telegram.
Jangan teruskan kalau ada yang FAIL — sistem ini tak berguna atas data separuh.

### 3.5 Isi data sejarah

```bash
python -m annems backfill --days 14
```

Tanpa ini, semua baseline kosong pada hari pertama dan Agent 3 akan senyap
(memang sengaja — ia enggan menilai tanpa baseline yang cukup).

### 3.6 Deploy

Ikut [`deploy/CRON.md`](deploy/CRON.md) — ada jadual cron (dalam UTC, sudah
ditukar dari MYT) dan cara daftar webhook Telegram.

---

## 4. Arahan harian

```bash
python -m annems collect            # Agent 1 — tarik data semalam
python -m annems report             # Laporan pagi
python -m annems report --print-only  # Cetak sahaja, tak hantar Telegram
python -m annems weekly             # Ringkasan mingguan
python -m annems monitor-pull       # Tarik data hari ini (ringan)
python -m annems monitor --force    # Agent 3, abaikan had waktu
python -m annems creative -n 3      # Agents 4+5
python -m annems creative -n 2 --no-image   # Ayat sahaja, jimat kos
python -m annems import-tagging-log docs/Creative_Tagging_Log_Annems.xlsx
python -m annems healthcheck
```

Dalam Telegram: `/report`, `/weekly`, `/creative 3`, `/status`, `/alerts`, `/help`.

---

## 5. Panduan modul

### `config.py`
Satu-satunya tempat yang baca environment variables. Threshold dibaca dari
`config/thresholds.yaml`. Semua masa dalam `Asia/Kuala_Lumpur`.
**Kegagalan biasa:** `RuntimeError: Missing required environment variable` —
`.env` tak lengkap, atau Railway Variables tak diset.

### `metrics.py` — Metric Engine
Fungsi tulen, tiada I/O. Formula ditetapkan sekali di kepala fail supaya semua
laporan konsisten. `aggregate()` kira semula metrik terbitan dari jumlah mentah
— bukan purata daripada purata, supaya ad RM500 tak ditimbang sama dengan ad RM5.
**Kegagalan biasa:** tiada. Kalau nombor nampak pelik, ia datang dari data
sumber, bukan dari sini — cek `daily_metrics` mentah dulu.

### `db.py`
Semua akses Supabase. `agent_run()` ialah context manager yang log setiap run ke
table `agent_runs`, termasuk ralat. Kalau table audit rosak, kerja sebenar tetap
jalan (audit yang gagal tak boleh hentikan operasi).
**Kegagalan biasa:** `Invalid API key` — guna `service_role` key, bukan `anon`.

### `notify.py`
Telegram. Auto-pecah mesej melebihi 4096 aksara pada sempadan baris. Kalau
Markdown gagal parse, ia hantar semula sebagai teks biasa — mesej tak pernah
hilang senyap. `alert_failure()` tak pernah raise.
**Kegagalan biasa:** `chat not found` — chat ID salah, atau Aiman belum pernah
mesej bot itu dahulu.

### `collectors/meta.py`
Meta Insights, **read-only**. Kira lead dari beberapa `action_type` sekali gus
(`lead`, `onsite_conversion.lead_grouped`, `offsite_conversion.fb_pixel_lead`, …)
sebab nama bergantung pada cara conversion disetkan.
**Kegagalan biasa:** token tamat tempoh (error 190) — jana token baru yang
long-lived. Rate limit (error 17) — kurangkan kekerapan backfill.

### `collectors/ghl.py`
Lead + stage pipeline. Nama stage GHL dipetakan ke lima stage kanonik melalui
[`config/ghl_stages.yaml`](config/ghl_stages.yaml). Stage yang tak dikenali jadi
`new` **dan ditulis dalam log sebagai warning** — ia takkan senyap dikira
qualified.
**Kegagalan biasa:** CPQL nampak terlalu tinggi → stage GHL dinamakan semula
tapi `ghl_stages.yaml` tak dikemas kini. Ini kegagalan paling kerap dalam
keseluruhan sistem. Cek warning dalam log.

### `agents/analyst.py` — Agent 2
`build_data_pack()` kumpul dan kira semuanya; `detect_signals()` kenal pasti
corak secara mekanikal (fatigue / saturation / landing page / tracking); LLM cuma
namakan dan terangkan. Kalau data tak cukup, `data_cukup` jadi `false` dan
prompt arahkan model kata terus data belum cukup.
**Kegagalan biasa:** diagnosis kabur → biasanya memang data belum cukup hari.

### `agents/reporter.py`
Laporan pagi + mingguan. Semua nombor diformat dari nilai yang sudah dikira.
**Kegagalan biasa:** laporan penuh `—` → `collect` gagal malam sebelumnya. Cek
`/status` dalam Telegram.

### `agents/monitor.py` — Agent 3
Empat rule: `spend_no_leads`, `cpl_spike`, `ctr_drop`, `frequency_high`. Semua
threshold dalam `config/thresholds.yaml` sahaja. Ada cooldown supaya satu ad
sakit tak alert setiap 3 jam.
**Kegagalan biasa:** terlalu banyak alert → naikkan threshold atau
`cooldown_hours`. Tiada alert langsung → baseline belum cukup
(`min_days_for_baseline`), atau di luar `active_hours`.

### `agents/ad_writer.py` — Agent 4
Jana creative bertag. `validate_tags()` tolak apa-apa creative yang concept /
angle / format / awareness-nya tiada dalam `config/brand.yaml`. Ini bukan
kerenah — nama yang konsisten hari ini yang buat Learning Memory berguna nanti.
**Kegagalan biasa:** `Agent 4 produced no validly tagged creatives` — model reka
nama concept baru. Run semula; kalau berulang, longgarkan senarai concept dalam
`brand.yaml` (dengan sengaja, bukan sebab malas).

### `agents/creative_qa.py` — Agent 5
Enam dimensi, skor 0–10. `risiko_polisi_iklan` dan `artifak_ai` kena capai 8;
selebihnya 7. FAIL → satu kali pembetulan → kalau gagal lagi, tetap sampai ke
Aiman tapi bertanda `FLAGGED`. Tiada creative hilang senyap.

### `agents/creative_factory.py`
Sambung Agent 4 + 5 + Telegram + rekod approval. Tak pernah tulis ke Meta.

### `tagging_log.py`
Import spreadsheet manual ke table `creatives`. Baris contoh dilangkau. Konsep
tersalah eja **ditolak dengan nombor baris**, bukan diterima diam-diam.
Kolum "Catatan / Learning" **sengaja tak diimport** — rekod pembelajaran milik
Agent 6 (Phase 2).
**Kegagalan biasa:** `konsep 'X' tak dikenali` — betulkan ejaan dalam
spreadsheet, atau tambah concept itu ke `config/brand.yaml`.

### `bot.py`
Webhook Telegram (FastAPI). Sahkan secret token pada setiap request, dan hanya
dua chat ID yang dibenarkan. Butang Approve/Reject **rekod keputusan sahaja** —
ia tak publish apa-apa.

---

## 6. Matriks approval (dikuatkuasakan dalam kod)

| Tindakan | Approval |
|---|---|
| Jana laporan / analisis / alert | AUTO |
| Jana draf creative + gambar | AUTO |
| Tag / klasifikasi / simpan data | AUTO |
| Publish ad ke Meta | MANUSIA (Aiman) — dan **manual dalam Ads Manager** |
| Pause ad | MANUSIA — manual dalam Ads Manager |
| Ubah budget | MANUSIA — manual dalam Ads Manager |
| Hantar mesej ke pelanggan | **Tiada dalam skop V1 langsung** |

V1 guna Meta API **read-only**. Tiada kod dalam repo ini yang boleh tulis ke
Meta, jadi auto-publish bukan sekadar dimatikan — ia memang tak wujud.

---

## 7. Ujian

```bash
python -m pytest -q          # 89 ujian, tiada network, tiada database
```

Liputan sengaja ditumpu pada bahagian yang **membuat keputusan**:

- `test_metrics.py` — pembahagi sifar jadi `None`, baseline tak masuk hari yang
  dinilai, agregat kira semula dari jumlah mentah, `rank_ads` buang bunyi bising
- `test_monitor_rules.py` — setiap threshold diuji pecah **dan** tak pecah; setiap
  alert wajib ada nombor + diagnosis + cadangan (larangan "prestasi menurun")
- `test_analyst_signals.py` — fatigue vs saturation vs landing page vs tracking
- `test_tagging_log.py` — validator + workbook sebenar dalam `docs/`
- `test_ghl_stages.py` — pemetaan stage + attribution tanpa teka
- `test_reporter_format.py` — nombor hilang jadi `—`, bukan RM0.00

Yang **tidak** diuji secara automatik: panggilan sebenar ke Meta, GHL, OpenAI,
Telegram. Itu disahkan melalui `healthcheck` dan syarat `CLAUDE.md` seksyen 8 —
run end-to-end dengan data API sebenar tiga hari berturut-turut sebelum
mengisytiharkan mana-mana milestone siap.

---

## 8. Keputusan yang dibuat semasa pembinaan

Dua perkara tak dinyatakan dengan konsisten dalam dokumen sumber. Keputusan dan
sebabnya, supaya boleh dipertikai kemudian:

1. **Telegram, bukan WhatsApp.** Dokumen Word sebut WhatsApp; `CLAUDE.md`
   seksyen 3 letak Telegram dalam stack yang "fixed — do not substitute" dan
   beri sebabnya (jauh lebih ringkas daripada WhatsApp Business API). Spec
   teknikal menang. Semua penghantaran mesej melalui `notify.py` sahaja, jadi
   menambah WhatsApp kemudian bermakna menukar satu modul.

2. **Tagging Log kekal manual, diimport ke `creatives`.** Spreadsheet ialah
   sumber input Aiman; `tagging_log.py` memuatkannya ke database supaya
   `angle_performance()` boleh sambung prestasi ad kepada concept/angle.
   Penyambungnya ialah **nama ad Meta**, jadi satu lajur ditambah pada schema:
   `creatives.meta_ad_name`. Ini satu-satunya penyimpangan dari `CLAUDE.md`
   seksyen 5 — tanpanya, tiada cara menyambung data bertag kepada nombor
   prestasi.

---

## 9. Day-90 review (Milestone 5 — keputusan manusia, bukan kod)

Selepas 90 hari live, semak tiga kriteria ini:

1. Laporan pagi betul-betul dibaca dan diguna setiap hari.
2. Sekurang-kurangnya **3 keputusan creative** berubah kerana data sistem.
3. Trend CPQL dapat diukur dengan jelas.

Ketiga-tiga lulus → barulah pertimbangkan Phase 2 (Agent 6 + 7).
Ada yang gagal → berhenti dan nilai semula. **Kill criteria itu nyata.** Sistem
yang tak dipakai ialah liabiliti, bukan aset.
