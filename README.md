# 🦅 GarudaTel v2 - Platform PPOB, Pulsa & Top Up Game Modern

Platform web modern untuk penjualan produk digital Pulsa, Paket Data, Token PLN, E-Money, Voucher, dan Top Up Game secara otomatis, terintegrasi dengan Payment Gateway QRIS instan, provider H2H, WhatsApp gateway, dan Triple Bot Telegram.

---

## 🌟 Fitur Utama

### 1. Transaksi & Multi-Provider H2H
- **Digiflazz**: Pulsa, Paket Data, Token PLN, E-Money (Gopay, OVO, Dana, ShopeePay), dan Tagihan Pascabayar dengan sistem inquiry & payment otomatis.
- **VIP-Reseller**: Top up game populer (Mobile Legends, Free Fire, PUBG, Genshin Impact, dll.) dengan validasi ID server instan.
- **Auto Margin & Tiering**: Rumus keuntungan otomatis multi-tier berdasarkan harga modal produk.

### 2. Dual Payment Gateway (QRIS Otomatis)
- **Pakasir**: Generator QRIS instan tanpa biaya ribet, webhook otomatis tanpa delay.
- **PaymentKita**: Gateway alternatif dengan verifikasi callback terenkripsi.
- **Switcher Gateway 1-Klik**: Kemudahan beralih gateway utama langsung dari dashboard admin.
- **Deposit Manual E-Wallet**: Fitur transfer manual dengan kode unik dan integrasi pesan WhatsApp direct.

### 3. Triple Bot Telegram Terintegrasi
1. **Bot 1 : CS & Balas Inbox**
   - Menerima tiket bantuan dari member langsung ke chat Telegram admin.
   - Dilengkapi detail komprehensif (Ref ID, produk, SN, nomor tujuan, pesan keluhan) dan tautan direct WhatsApp pelapor.
2. **Bot 2 : Notifikasi Real-Time & Offsite Backup**
   - Mengirim alert instan setiap ada transaksi masuk, pembayaran QRIS lunas, transaksi berhasil/gagal, dan deposit manual.
   - Menerima file dokumen snapshot database SQLite fisik (`.db.gz`) secara terjadwal maupun manual.
3. **Bot 3 : Panel Kontrol Admin (Inline Keyboard Button)**
   - Akses kontrol cepat tanpa perlu membuka browser.
   - 10 Tombol Interaktif: Saldo Digiflazz, Omset Hari Ini, Trx Pending, Tiket CS, Sinkronisasi Produk, Buat OTP Darurat, Snapshot Backup Instan, dan Status VPS.
   - Perintah cepat: `/otp <nomor_wa>` untuk bypass verifikasi darurat.

### 4. Keamanan & Keandalan Tingkat Tinggi
- **Universal Manual OTP**: Solusi darurat jika SMS/WhatsApp gateway mengalami delay. Admin dapat meng-generate OTP darurat 15 menit via Bot Telegram atau Dashboard Admin yang otomatis meloloskan registrasi, login, atau reset kata sandi.
- **Proteksi CSRF Global**: Proteksi token CSRF pada seluruh formulir mutasi admin, dengan pengecualian aman (`@csrf.exempt`) khusus webhook pihak ketiga yang divalidasi dengan signature kriptografis.
- **SQLite WAL Mode**: Write-Ahead Logging & non-blocking concurrency mencegah error database locked saat lonjakan transaksi.
- **Rate Limiting**: Proteksi endpoint sensitif dengan Flask-Limiter.

---

## 🚀 Panduan Deployment VPS (One-Click Installer)

GarudaTel v2 dilengkapi dengan skrip instalasi interaktif satu klik yang mendukung integrasi **Cloudflare Zero Trust Tunnels**, sehingga domain Anda langsung terhubung ke VPS tanpa perlu membuka port publik atau IP statis.

### Persyaratan Minimal VPS
- OS: Ubuntu 20.04 / 22.04 LTS atau Debian 11 / 12
- RAM: 1 GB (Direkomendasikan 2 GB)
- Disk: 10 GB SSD
- Akses `root` atau `sudo`

### Langkah-Langkah Instalasi:

1. **Clone Repositori ke VPS**:
   ```bash
   git clone https://github.com/angga2103/garudatell.git /var/www/garudatel
   cd /var/www/garudatel
   ```

2. **Jalankan Skrip Instalasi**:
   ```bash
   sudo bash install.sh
   ```

3. **Ikuti Panduan di Terminal**:
   - Skrip akan meminta **Token Cloudflare Zero Trust Tunnel**.
     *(Dapatkan token di Cloudflare Dashboard -> Zero Trust -> Networks -> Tunnels -> Add a tunnel -> cloudflared)*
   - Masukkan Domain Anda (misal: `garudatel.com`).
   - Skrip akan otomatis menginstal dependensi Python, membuat virtual environment, mengonfigurasi `.env` dengan `SECRET_KEY` acak, menyiapkan database SQLite, membuat akun admin awal, meregistrasi `systemd` service (`garudatel.service` dan `garudatel-bot-admin.service`), serta menjalankan Cloudflare Tunnel.

4. **Login ke Panel Admin**:
   - Akses: `https://domain-anda.com/admin/login`
   - Username Default: `admin`
   - Password Default: `admin123`
   *(Segera ubah password setelah login pertama kali di menu Pengaturan Akun).*

---

## ⚙️ Konfigurasi Environment (`.env`)

Konfigurasi dapat diatur melalui file `.env` atau langsung diisi melalui form **Dashboard Admin**:

```ini
# Flask Security
SECRET_KEY=isi_dengan_random_hex_64_karakter

# Payment Gateway Aktif ('pakasir' atau 'paymentkita')
ACTIVE_PAYMENT_GATEWAY=pakasir

# Digiflazz H2H
DIGI_USER=username_digiflazz
DIGI_KEY=api_key_digiflazz
DIGI_URL=https://api.digiflazz.com/v1

# Pakasir QRIS
PAKASIR_PROJECT=nama_project
PAKASIR_API_KEY=api_key_pakasir

# VIP-Reseller Games
VIP_API_ID=api_id_vip
VIP_API_KEY=api_key_vip

# Telegram Bots
BOT_CS_TOKEN=token_bot_cs
BOT_CS_CHAT_ID=chat_id_admin
BOT_NOTIF_TOKEN=token_bot_notif
BOT_NOTIF_CHAT_ID=chat_id_admin
BOT_ADMIN_TOKEN=token_bot_admin
BOT_ADMIN_CHAT_ID=chat_id_admin
```

---

## 🛠️ Antarmuka CLI Manajemen Cepat (`garudatell`)

GarudaTel v2 menyediakan antarmuka CLI interaktif berbasis Bash yang dapat dipanggil **kapan saja dari direktori mana saja** di terminal VPS:

```bash
garudatell
```

Antarmuka menu interaktif akan langsung terbuka:
```text
  ╔══════════════════════════════════════════════════════════════╗
  ║             🦅 GARUDATELL - VPS CONTROL PANEL 🦅             ║
  ║              Management Suite & Operation Center             ║
  ╚══════════════════════════════════════════════════════════════╝
  📂 Lokasi Proyek : /var/www/garudatel
  🌐 Server Web    : ● RUNNING  │  🤖 Bot Admin : ● RUNNING  │  ☁️ Tunnel : ● CONNECTED
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  [1] Cek Status Server Web        (sudo systemctl status garudatel)
  [2] Restart Server Web           (sudo systemctl restart garudatel)
  [3] Pantau Log Error (Live)      (tail -f storage/logs/error.log)
  [4] Cek Status Bot 3 Admin       (sudo systemctl status garudatel-bot-admin)
  [5] Backup Database Manual       (Snapshot WAL SQLite -> Telegram)
  [6] Pengujian Otomatis Sistem    (Jalankan test_telegram_and_otp.py)
  [7] Manajemen Cloudflare Tunnel  (Status & Ganti Token Zero Trust)
  [8] Cek Pembaruan (Git Update)   (Git Fetch, Pull & Auto-Restart)
  [0] Keluar (Exit)
```

Cukup ketikkan angka pilihan Anda untuk mengeksekusi operasi tanpa perlu mengingat perintah panjang.

---

### Perintah Pemeliharaan Manual (Opsional):

```bash
# Cek status server web
sudo systemctl status garudatel

# Restart server web
sudo systemctl restart garudatel

# Pantau log error secara live
tail -f storage/logs/error.log

# Cek status Bot 3 Admin
sudo systemctl status garudatel-bot-admin

# Snapshot backup database cepat ke Telegram
./venv/bin/python -c "from app.services.telegram_service import perform_database_backup; print(perform_database_backup())"

# Jalankan pengujian otomatis sistem
./venv/bin/python tools/test_telegram_and_otp.py
```

---

## 📄 Lisensi
Hak Cipta © 2026 GarudaTel. Seluruh hak cipta dilindungi undang-undang.

