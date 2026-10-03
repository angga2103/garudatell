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
   - Tombol Interaktif: Saldo Digiflazz, Omset Hari Ini, Trx Pending, Tiket CS, Sinkronisasi Produk, Buat OTP Darurat, Status/Pairing WhatsApp, Snapshot Backup Instan, dan Status VPS.
   - Perintah cepat: `/otp <nomor_wa>` untuk bypass verifikasi darurat dan pairing nomor WhatsApp langsung via chat.

### 4. Bot WhatsApp Gateway (Baileys Multi-Device & PM2 Auto-Recovery)
- **Mesin Baileys Multi-Device**: Pengiriman kode OTP pendaftaran/login dan notifikasi transaksi secara otomatis via WhatsApp.
- **Pairing Code Stabil**: Mendukung penautan Companion Device dengan nomor telepon tanpa QR timeout (menggunakan platform browser `Browsers.ubuntu('Chrome')` dan soket stabilizer 3000ms).
- **Integrasi Telegram Alarm**: Saat sesi terputus atau logout, bot otomatis mengirimkan alarm ke Telegram dengan tombol interaktif `📱 TAUTKAN NOMOR BARU`.
- **PM2 Process Manager**: Dikelola penuh dengan PM2 auto-recovery dan auto-start saat reboot server VPS (`pm2 startup` & `pm2 save`).

### 5. Keamanan & Keandalan Tingkat Tinggi
- **Universal Manual OTP**: Solusi darurat jika SMS/WhatsApp gateway mengalami kendala. Admin dapat meng-generate OTP darurat 10-15 menit via Bot Telegram atau Dashboard Admin dengan tautan direct WhatsApp otomatis.
- **Universal Manual OTP & Approval CS/Admin**: Solusi darurat jika bot WhatsApp offline/terputus. Tombol bantuan manual otomatis muncul di halaman login/daftar, permohonan diteruskan langsung ke Bot Telegram CS dan Panel Web Admin (`/admin/otp_manual`) dengan fitur persetujuan (Approve 10 menit + direct link WhatsApp), penolakan (Reject) disertai alasan, serta hak akses pemulihan (Unblock).
- **Lupa Password Otomatis**: Fitur self-service pemulihan akun berbasis validasi silang Username & No. WhatsApp terdaftar dengan verifikasi OTP otomatis atau via bantuan manual.
- **Proteksi Anti-Brute-Force OTP**: Batas maksimal 3 kali kesalahan input sebelum kode OTP dihanguskan secara permanen untuk mencegah eksploitasi brute-force.
- **Proteksi CSRF Global**: Proteksi token CSRF pada seluruh formulir mutasi admin, dengan pengecualian aman (`@csrf.exempt`) khusus webhook pihak ketiga yang divalidasi dengan signature kriptografis.
- **SQLite WAL Mode**: Write-Ahead Logging & non-blocking concurrency mencegah error database locked saat lonjakan transaksi.
- **Rate Limiting**: Proteksi endpoint sensitif dengan Flask-Limiter.

### 6. Open API Gateway B2B & Integrasi POS IPAY
- **Standar API H2H / B2B Modern**: Gateway transaksi PPOB, pulsa, token listrik, voucher, dan top up game langsung untuk mesin Kasir Web POS ([Ipay-POS](https://github.com/angga2103/Ipay-POS)).
- **Dual Auth & Anti-Tamper Security**: Header autentikasi `X-API-KEY` digabung dengan kalkulasi signature kriptografis MD5 (`md5(merchant_id + secret_key + ref_id)`) untuk mencegah spoofing atau manipulasi data.
- **Idempotency Guard**: Anti-dobel transaksi berbasis `ref_id`. Request berulang dengan `ref_id` sama tidak akan memotong saldo ganda ataupun menduplikasi order ke provider.
- **Safe Universal Digiflazz Import**: Arsitektur import cerdas bersyarat (`try from digiflazz ... except ...`) yang tahan terhadap perbedaan path root/service di berbagai lingkungan server.
- **Atomic Concurrency Balance Check & Auto-Refund**: Penguncian baris akun (`SELECT FOR UPDATE`) mencegah race condition / double spending. Jika transaksi ditolak provider, saldo dikembalikan instan 100% ke akun merchant.
- **Real-Time Webhook Dispatcher**: Mengirim callback status transaksi (`success` / `failed`) langsung ke endpoint Web POS secara otomatis.

---

## 🔌 Open API Gateway & Integrasi Ekosistem Web POS

GarudaTel v2 terintegrasi secara native dengan ekosistem **[Ipay-POS](https://github.com/angga2103/Ipay-POS)** (Aplikasi Kasir Web POS Konter HP Modern dengan Pembukuan Akuntansi Buku Besar, Cloudflare Zero Trust, dan Dynamic Auto-Backup). Melalui Open API Gateway ini, kasir dapat menjual pulsa, kuota data, voucher game, dan membayar tagihan langsung dari antarmuka POS dengan memotong saldo deposit merchant iPay.

### 1. Manajemen Kredensial API Merchant
Admin atau Member dapat mengaktifkan dan mengelola kredensial API melalui menu **Dashboard Admin > API Gateway** (`/admin/merchant_api`):
- **Merchant ID**: Pengenal unik merchant (contoh: `MCH-000001`).
- **Secret Key**: Kunci rahasia 32 karakter untuk kalkulasi signature MD5 anti-tamper.
- **API Key**: Token autentikasi yang dikirimkan via HTTP Header `X-API-KEY`.
- **Webhook URL**: URL callback penerima notifikasi status dari POS (contoh: `https://pos.domain-anda.com/api/ppob/webhook`).

### 2. Format Header & Rumus Signature Keamanan
Setiap request ke endpoint transaksi wajib menyertakan header dan signature:
```http
Content-Type: application/json
X-API-KEY: your_merchant_api_key_here
```

**Formula Perhitungan MD5 Signature**:
- **Cek Saldo (POST)**: `MD5(merchant_id + secret_key + "balance")`
- **Inquiry & Transaksi (POST)**: `MD5(merchant_id + secret_key + ref_id)`

### 3. Daftar Endpoint REST API v1

| Metode | Endpoint | Deskripsi & Kegunaan |
| :--- | :--- | :--- |
| `GET / POST` | `/api/v1/profile/balance` | Cek sisa saldo akun merchant & verifikasi koneksi API |
| `GET` | `/api/v1/profile/deposit/info` | Ambil info saluran deposit (DANA, GoPay, ShopeePay, Bank, QRIS) |
| `POST` | `/api/v1/profile/deposit/create` | Buat tiket deposit dari POS & generate link konfirmasi WhatsApp |
| `POST` | `/api/v1/transaction/inquiry` | Cek nama pelanggan & jumlah tagihan pascabayar (PLN, PDAM, BPJS) |
| `POST` | `/api/v1/transaction/create` | Eksekusi transaksi prabayar & pascabayar (Atomic & Idempotent) |
| `GET / POST` | `/api/v1/transaction/status` | Cek status transaksi spesifik berdasarkan parameter `ref_id` |
| `GET` | `/api/v1/products` | Sinkronisasi katalog produk aktif & harga jual sesuai tier akun |

### 4. Contoh Payload Eksekusi Transaksi (`POST /api/v1/transaction/create`)
```json
{
  "buyer_sku_code": "xld5",
  "customer_no": "087812345678",
  "ref_id": "POS-TRX-1740000000-123",
  "sign": "5d41402abc4b2a76b9719d911017c592"
}
```
**Respon Berhasil (`200 OK`)**:
```json
{
  "status": "success",
  "data": {
    "ref_id": "POS-TRX-1740000000-123",
    "status": "success",
    "sn": "021938210391203",
    "buyer_sku_code": "xld5",
    "customer_no": "087812345678",
    "price": 5800,
    "message": "Transaksi Berhasil"
  },
  "message": "Transaksi Berhasil"
}
```

### 5. Webhook Callback Otomatis ke Web POS
Saat status transaksi diperbarui oleh provider (Digiflazz / VIP-Reseller), GarudaTel secara otomatis mengirimkan callback HTTP POST ke Web POS:
```json
{
  "ref_id": "POS-TRX-1740000000-123",
  "status": "success",
  "sn": "021938210391203",
  "sku_code": "xld5",
  "price": 5800
}
```

### 6. Repositori Terkait
- **Web POS Konter IPAY**: [https://github.com/angga2103/Ipay-POS](https://github.com/angga2103/Ipay-POS)


## 🚀 Panduan Deployment VPS (One-Click Installer)

GarudaTel v2 dilengkapi dengan skrip instalasi interaktif satu klik yang secara otomatis memasang seluruh dependensi: Python Gunicorn, Cloudflare Zero Trust Tunnels, serta **Node.js 20 LTS + PM2 untuk Bot WhatsApp Baileys**.

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
   - Skrip akan meminta **Token Cloudflare Zero Trust Tunnel** (opsional).
   - Masukkan Domain Anda (misal: `garudatel.com`).
   - Skrip akan otomatis:
     - Menginstal dependensi Python & virtual environment.
     - Mengonfigurasi `.env` dengan `SECRET_KEY` unik.
     - Menginisialisasi database SQLite & akun default admin.
     - Meregistrasi `systemd` service (`garudatel.service` dan `garudatel-bot-admin.service`).
     - **Menginstal Node.js 20 LTS, PM2, dan dependensi WhatsApp Bot Baileys secara otomatis di background**.
     - Mengonfigurasi `pm2 startup` agar mesin WhatsApp langsung aktif kembali saat VPS reboot.
     - Menghubungkan Cloudflare Zero Trust Tunnel (port 5000).

4. **Login ke Panel Admin & Tautkan WhatsApp**:
   - Akses: `https://domain-anda.com/admin/login`
   - Username Default: `admin`
   - Password Default: `admin123`
   - Buka menu **Konfigurasi Bot WhatsApp** di Dashboard Admin, masukkan nomor WhatsApp Anda, lalu klik **Minta Kode Pairing** (atau gunakan tombol di Bot Telegram Admin).

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
  🌐 Web Server    : ● RUNNING  │  🤖 Bot Admin : ● RUNNING  │  📱 Bot WA : ● ACTIVE  │  ☁️ Tunnel : ● CONNECTED
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  [1] Cek Status Server Web        (sudo systemctl status garudatel)
  [2] Restart Server Web           (sudo systemctl restart garudatel)
  [3] Pantau Log Error (Live)      (tail -f storage/logs/error.log)
  [4] Cek Status Bot 3 Admin       (sudo systemctl status garudatel-bot-admin)
  [5] Manajemen Bot WhatsApp (PM2) (Status, Restart, Log Baileys)
  [6] Backup Database Manual       (Snapshot WAL SQLite -> Telegram)
  [7] Pengujian Otomatis Sistem    (Jalankan test_telegram_and_otp.py)
  [8] Manajemen Cloudflare Tunnel  (Status & Ganti Token Zero Trust)
  [9] Cek Pembaruan (Git Update)   (Git Fetch, Pull & Auto-Restart)
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

# Cek status Bot WhatsApp (PM2)
pm2 status garudatel-wa-bot

# Restart Bot WhatsApp
pm2 restart garudatel-wa-bot

# Pantau log Baileys WhatsApp secara live
pm2 logs garudatel-wa-bot

# Pantau log error Flask secara live
tail -f storage/logs/error.log

# Cek status Bot 3 Admin
sudo systemctl status garudatel-bot-admin

# Snapshot backup database cepat ke Telegram
./venv/bin/python -c "from app.services.telegram_service import perform_database_backup; print(perform_database_backup())"

# Jalankan pengujian otomatis sistem Telegram & OTP
./venv/bin/python tools/test_telegram_and_otp.py

# Jalankan pengujian otomatis Open API Gateway & integrasi POS
./venv/bin/python tools/test_merchant_api.py
```

---

## 📄 Lisensi
Hak Cipta © 2026 GarudaTel. Seluruh hak cipta dilindungi undang-undang.

