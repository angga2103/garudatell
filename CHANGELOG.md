# GarudaTel ChangeLog

All notable changes to the GarudaTel platform will be documented in this file.

---

## [GT-2.0.2] - 2026-10-14

### ⚡ Performance & Optimization
- **Digiflazz In-Memory SKU Mapping**: Refactor fungsi `sync_products()` di `app/services/digiflazz.py` menggunakan in-memory dictionary lookup ($O(1)$) untuk memetakan seluruh SKU produk. Mengeliminasi siklus *autoflush lockup* SQLite dan ribuan query N+1, memangkas durasi sinkronisasi 1.000 SKU dari belasan menit menjadi **0,21 detik**.
- **In-Memory Obsolete Product Filtering**: Menghapus query `WHERE NOT IN (...)` ribuan parameter pada tahap *circuit breaker* produk usang untuk mencegah error `too many SQL variables` pada SQLite.
- **Pascabayar Seeder In-Memory**: Mengoptimalkan seeder katalog produk pascabayar nasional dengan in-memory map.

### 🛡️ Reliability & Telegram Bot Hardening
- **Fix Background Sync Threading NameError**: Memperbaiki bug kritis hilangnya `import threading` di tingkat modul `telegram_service.py` yang menyebabkan klik tombol *"🔄 Sync Digiflazz"* di Bot 3 Admin terhenti senyap (*freeze*) pada pesan `"⏳ Sedang menarik data..."`.
- **In-Place Loading Message Update**: Mengubah alur respon sinkronisasi Bot 3 dari pengiriman pesan baru menjadi *auto-edit* langsung pada pesan loading awal ke status hasil akhir (atau pesan kesalahan ramah) dengan tombol kembali interaktif.
- **Circuit Breaker Failure Telegram Alert**: Menambahkan pengiriman notifikasi otomatis ke Bot 3 Admin jika sinkronisasi Digiflazz terkena limitasi frekuensi provider (RC 83) atau kendala jaringan, mencegah bot diam tanpa kabar.
- **Eliminasi Bulk Lock Redundant**: Menghapus eksekusi bulk UPDATE ORM produk gembok admin di callback thread bot yang memicu risiko penguncian database SQLite.
- **Entity Parse Error Auto-Fallback**: Menambahkan *auto-fallback plain-text* pada `_send_message` dan `_edit_message` jika API Telegram menolak entitas HTML akibat karakter khusus atau pesan error traceback.
- **Digiflazz Adaptive Timeout**: Menaikkan batas timeout request pricelist Digiflazz menjadi `timeout=(15, 60)` untuk unduhan payload besar tanpa putus koneksi.

### 🔍 Features & UX
- **Pencarian Produk Nonaktif Per Seller di Bot 3 Admin**: Menambahkan perintah `/cari nama_produk` dan formulir pencarian interaktif pada Bot 3 Telegram Admin untuk memudahkan pencarian dan re-aktivasi 1-klik produk nonaktif tanpa harus membuka katalog seller satu per satu.
- **Serial Number (SN) Formatting**: Merapikan pemformatan tampilan Serial Number (SN) untuk transaksi kuota data internet, token PLN, voucher game, dan pulsa agar terstruktur rapi di layar web dan saat disalin (*click-to-copy*) ke clipboard.
- **Master Recovery Key & POS SSO**: Menambahkan pembuatan Master Recovery Key otomatis, reset Password & PIN via WhatsApp, serta 1-Click SSO Open POS di panel `/admin/merchant_api`.
- **Anti-Wipeout Soft-Disable**: Proteksi produk lokal dari penghapusan keras (*no hard delete*) dan isolasi gembok admin (`is_admin_disabled`) agar produk nonaktif tidak teraktifkan kembali oleh auto-sync provider.

### 🖥️ DevOps & Automation
- **Dedicated Standalone Cron Runner (`tools/cron_sync_products.py`)**: Script CLI mandiri untuk eksekusi sinkronisasi Digiflazz dan pemindaian saldo minim toko mitra langsung dari crontab Linux dengan logging terstruktur ke `storage/logs/cron_sync.log`.
- **Crontab Manager Script (`tools/setup_auto_sync_cron.sh`)**: Utilitas 1-klik (`enable`, `disable`, `status`, `run`) untuk mempermudah pendaftaran dan monitoring jadwal auto-sync 30 menit di crontab VPS Linux.
- **Installer Auto-Sync Integration**: Memperbarui `tools/installer_vps_baru.sh` agar otomatis mengaktifkan scheduler auto-sync produk saat pertama kali instalasi VPS baru.
- **Standardisasi Path VPS**: Memperbarui dan menyelaraskan seluruh dokumentasi SOP (`DEPLOYMENT_SOP.md`, `AI_HANDOVER_RULES.md`, `deployment/nginx_garudatel.conf`, `tools/backup_database.sh`) ke path instalasi resmi Linux VPS: `/var/www/garudatel`.

---

## [GT-2.0.1] - 2026-09-21

### 🔒 Security & Hardening
- **Account Takeover Prevention**: Validasi token kriptografis berbatas 5 menit dengan pengecekan `compare_digest` pada alur reset password `/profil`.
- **Credential Sanitization**: Mengamankan penyimpanan password dan menghapus plaintext credentials di file JSON sementara.
- **WhatsApp Bot Microservice Hardening**: Mengikat host Baileys ke `127.0.0.1` dan menerapkan middleware autentikasi `X-Internal-Token` (`WA_BOT_SECRET_TOKEN`).
- **Webhook Security**: Verifikasi signature HMAC ketat pada callback Digiflazz dan PaymentKita.
- **OWASP HTTP Security Headers**: Penerapan header global `X-Frame-Options`, `nosniff`, dan `Referrer-Policy`.
- **SQLite WAL Mode & Concurrency**: Mode `journal_mode=WAL` dan `busy_timeout=10000ms` untuk transaksi non-blocking.
- **Healthcheck & Automated Backup**: Endpoint `/health` dan skrip pencadangan rotasi 7 hari `tools/backup_database.sh`.

---

## [GT-2.0.0] - 2026-09-01

### 🚀 Initial Core Foundation
- Arsitektur Monolithic MVC Flask 3.0 dengan SQLAlchemy ORM.
- Integrasi provider multi-H2H: Digiflazz (Prepaid & Pasca) dan VIP-Reseller (Games & Voucher).
- Dual payment gateway QRIS otomatis (Pakasir & PaymentKita) dan Deposit Manual E-Wallet.
- Triple Bot Telegram terintegrasi (Bot 1 CS, Bot 2 Notifikasi & Backup, Bot 3 Panel Admin).
- WhatsApp Gateway multi-device (Baileys Node.js microservice) via PM2.
