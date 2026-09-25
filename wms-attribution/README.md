# WMS Attribution — plugin tracking sumber & affiliate untuk wmsmalaysia.com

Satu sistem tracking untuk semua conversion. Setiap purchase, borang, borang GHL, klik WhatsApp,
Contact Admin, Contact Salesperson dan CTA tiket direkod bersama:

- **Affiliate**: siapa yang bawa visitor (MIGHT, Ibu Hanim, …)
- **Source / Medium / Campaign**: dari UTM, dari referrer (Google, Facebook…), atau `direct`. Tak pernah kosong.
- **Route**: laluan halaman visitor sebelum convert, contohnya `*/might > / > /speakers > /get-ticket`
- **WMS Ref**: kod visitor (`WMS-K7P2QX`) yang menghubungkan semua action orang yang sama

Affiliate dan UTM disimpan **berasingan**. UTM tak akan overwrite affiliate.

---

## 1. Pemasangan (±5 minit)

1. Zip folder `wms-attribution/` (tanpa folder `tests/`).
2. WP Admin → Plugins → Add New → Upload Plugin → pilih zip → **Activate**.
3. WP Admin → **WMS Attribution → Settings & links**: semak senarai affiliate (sudah diisi awal:
   `might`, `ibuhanim`, `annems`, `peoplelogy`, `lincgroup`). Tambah affiliate lain, satu setiap baris: `slug | Nama`.
4. Kalau guna cache (LiteSpeed / WP Rocket / Cloudflare): **exclude** URL affiliate (`/might`, `/ibuhanim`, …) daripada cache.
   Lagi selamat, tukar target redirect supaya bawa kod: `/might → /?ref=might`. Link lama tetap berfungsi.
5. Setup GHL (bahagian 5).

Plugin ini tidak mengubah link affiliate sedia ada. Ia hanya **membaca** URL semasa visitor sampai,
sebelum plugin redirect (Redirection, Pretty Links, Elementor) dijalankan.

## 2. Cara guna link affiliate

| Cara | Contoh | Nota |
|---|---|---|
| Link sedia ada | `wmsmalaysia.com/might` | Kekal berfungsi, sama ada ia page atau redirect |
| Parameter `ref` | `wmsmalaysia.com/?ref=might` atau `/get-ticket?ref=might` | Boleh ke mana-mana page. Juga terima `aff=`, `affiliate=` |
| Affiliate + UTM | `wmsmalaysia.com/might?utm_source=facebook&utm_medium=paid_social&utm_campaign=might_ads` | Affiliate = MIGHT, Source = facebook, Campaign = might_ads |

Peraturan:
- Visitor diingati selama **90 hari** (boleh ubah di Settings).
- Link affiliate yang **terbaru** menang. Affiliate yang pertama tetap disimpan sebagai *First touch*.
- Kalau checkout tiada cookie tetapi coupon yang digunakan sama dengan slug affiliate (contoh `MIGHT`), order itu dikreditkan kepada affiliate tersebut dengan tanda `(coupon)`.

## 3. Cara guna UTM

Gunakan huruf kecil dan konsisten:

| Parameter | Maksud | Contoh |
|---|---|---|
| `utm_source` | Platform | `facebook`, `instagram`, `google`, `linkedin`, `tiktok`, `whatsapp`, `email` |
| `utm_medium` | Jenis trafik | `paid_social`, `cpc`, `organic_social`, `email`, `broadcast` |
| `utm_campaign` | Nama kempen | `wms_september`, `might_ads`, `early_bird` |
| `utm_content` | Variasi iklan (pilihan) | `video_a`, `carousel_speakers` |

Tanpa UTM, sumber dikesan automatik: Google → `google / organic`, Facebook → `facebook / social`,
`?gclid=` → `google / cpc`, `?fbclid=` → `facebook / social`. Kalau tiada apa-apa, sumber = `direct`.
Lawatan direct yang kemudian **tidak** memadam sumber sebelumnya (last non-direct touch).

## 4. Apa yang di-track

| Action | Bagaimana | Di mana nampak |
|---|---|---|
| Purchase WooCommerce (classic & block checkout) | Order meta + log bila status *processing/completed* | Order → kotak **WMS Attribution**, kolum *Affiliate / Source* dalam senarai order, email admin *New order*, log |
| HRD Corp / Corporate / Bulk / Student / semua enquiry form | Hidden fields auto dalam setiap `<form>` + log server-side (Elementor Pro, CF7, WPForms, Fluent Forms, Gravity) atau log browser (borang HTML biasa) | Log (dengan nama, telefon, email), email admin borang, webhook |
| Borang GHL (iframe) | Attribution ditambah pada URL iframe → masuk ke GHL contact | GHL contact (custom fields) |
| Link ke GHL funnel / form | URL dihias dengan attribution | GHL contact + log `CTA click` |
| WhatsApp (semua `wa.me` / `api.whatsapp.com`, termasuk chat widget) | Log sebelum keluar + rujukan dalam mesej | Log + mesej WhatsApp yang diterima admin/sales |
| Contact Admin / Contact Salesperson | Sama seperti WhatsApp (atau `tel:` / `mailto:` → *Call* / *Email*) | Log |
| Standard / VIP ticket, Add to cart, butang CTA lain | Log klik dengan label dan lokasi butang | Log |

Mesej WhatsApp akan jadi begini:

```
Hi admin, saya nak tanya WMS

[Ref WMS-K5NJ48 · MIGHT · facebook/might_ads]
```

Admin/sales boleh cari `WMS-K5NJ48` dalam **WMS Attribution → Conversions** untuk lihat route penuh visitor tersebut.

Untuk butang yang tak dikesan automatik, tambah attribute `data-wms-cta="Nama Butang"` (Elementor: Advanced → Attributes).
Untuk kecualikan borang: `data-wms="off"`.

## 5. Setup GHL (sekali sahaja)

1. GHL → Settings → **Custom Fields** → cipta text fields: `affiliate`, `landing_page`, `wms_ref`, `wms_route`
   (UTM sudah ada dalam GHL sebagai attribution; kalau mahu nampak dalam contact, cipta juga `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`).
2. Dalam setiap **GHL form/survey** yang di-embed di WMS: tambah **Hidden field** untuk setiap custom field di atas
   dan set **Query Key** = nama yang sama (`affiliate`, `utm_source`, `wms_ref`, …).
3. Kalau borang Elementor dihantar ke GHL melalui **webhook**, attribution sudah ditambah automatik ke dalam payload
   (`affiliate`, `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `landing_page`, `wms_ref`, `wms_route`). Map dalam GHL workflow.
4. Kalau funnel GHL guna custom domain (contoh `daftar.wmsmalaysia.com`), masukkan domain itu di Settings → *Extra GHL / funnel domains*.

**Di mana nampak dalam GHL:** Contacts → buka contact → bahagian custom fields (`affiliate`, `utm_*`, `wms_ref`, `wms_route`)
dan tab *Attribution* (UTM asal).

## 6. Laporan

- **WMS Attribution → Conversions**: setiap action dengan tarikh, jenis, affiliate, source/medium, campaign, contact, jumlah RM, route dan WMS Ref.
  Tapis ikut action / affiliate / source / tarikh, atau cari ikut WMS Ref, telefon, email, no. order. Klik WMS Ref untuk lihat **perjalanan penuh** visitor tersebut. Ada Export CSV.
- **Summary by affiliate**: bilangan purchase, borang, GHL, WhatsApp, call, CTA dan revenue bagi setiap affiliate × source.
- GA4/GTM: setiap action juga push event `wms_conversion` ke `dataLayer`, dengan parameter `affiliate`, `utm_source`, `utm_campaign`, `wms_ref`.

## 7. Ujian

`tests/` mengandungi fixture laman WMS dan 12 senario end-to-end (Playwright + WordPress Playground):

```
npx @wp-playground/cli server --port 9400 --mount=./:/wordpress/wp-content/plugins/wms-attribution \
  --mount=./tests-mu:/wordpress/wp-content/mu-plugins   # letak tests/fixture-wms-test-site.php dalam tests-mu/
BASE=http://127.0.0.1:9400 node tests/e2e.mjs
```

## Had yang perlu diketahui

- Pengesanan submit borang GHL dalam iframe dibuat secara *best effort* melalui mesej iframe. Rekod sebenar lead GHL ialah dalam GHL itu sendiri (custom fields).
- Klik WhatsApp direkod sebagai *niat*. Chat sebenar disahkan melalui rujukan `[Ref WMS-…]` dalam mesej.
- Visitor yang menyekat cookie atau JavaScript direkod sebagai `direct` tanpa affiliate.
