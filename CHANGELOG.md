# GarudaTel ChangeLog

All notable changes to the GarudaTel platform will be documented in this file.

---

## [GT-2.0.2] - 2026-10-14

### ⚡ Performance & Optimization
- **Digiflazz In-Memory SKU Mapping**: Refactor fungsi `sync_products()` di `app/services/digiflazz.py` menggunakan in-memory dictionary lookup ($O(1)$) untuk memetakan seluruh SKU produk. Mengeliminasi siklus *autoflush lockup* SQLite dan ribuan query N+1, memangkas durasi sinkronisasi 1.000 SKU dari belasan menit menjadi **0,21 detik**.
- **In-Memory Obsolete Product Filtering**: Menghapus query `WHERE NOT IN (...)` ribuan parameter pada tahap *circuit breaker* produk usang untuk mencegah error `too many SQL variables` pada SQLite.
- **Pascabayar Seeder In-Memory**: Mengoptimalkan seeder katalog produk pascabayar nasional dengan in-memory map.

### 🛡️ Reliability & Telegram Bot Hardening
- **Bulletproof Background Runner**: Membungkus worker thread sinkronisasi manual (`async_sync_runner`) di `app/services/telegram_service.py` dengan blok `try ... except ... finally`, menjamin notifikasi status selalu terkirim ke Telegram dan koneksi database dibersihkan via `db.session.remove()`.
- **Entity Parse Error Auto-Fallback**: Menambahkan *auto-fallback plain-text* pada `_send_message` dan `_edit_message` jika API Telegram menolak entitas HTML akibat karakter khusus atau pesan error traceback.
- **Digiflazz Adaptive Timeout**: Menaikkan batas timeout request pricelist Digiflazz menjadi `timeout=(15, 60)` untuk unduhan payload besar tanpa putus koneksi.

### 🔍 Features & UX
- **Pencarian Produk Nonaktif Per Seller di Bot 3 Admin**: Menambahkan perintah `/cari nama_produk` dan formulir pencarian interaktif pada Bot 3 Telegram Admin untuk memudahkan pencarian dan re-aktivasi 1-klik produk nonaktif tanpa harus membuka katalog seller satu per satu.
- **Serial Number (SN) Formatting**: Merapikan pemformatan tampilan Serial Number (SN) untuk transaksi kuota data internet, token PLN, voucher game, dan pulsa agar terstruktur rapi di layar web dan saat disalin (*click-to-copy*) ke clipboard.
- **Master Recovery Key & POS SSO**: Menambahkan pembuatan Master Recovery Key otomatis, reset Password & PIN via WhatsApp, serta 1-Click SSO Open POS di panel `/admin/merchant_api`.
- **Anti-Wipeout Soft-Disable**: Proteksi produk lokal dari penghapusan keras (*no hard delete*) dan isolasi gembok admin (`is_admin_disabled`) agar produk nonaktif tidak teraktifkan kembali oleh auto-sync provider.

### 🖥️ DevOps & Environment
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
