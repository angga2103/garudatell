# Standard Operating Procedure (SOP): Panduan Deployment & Pemeliharaan Produksi GarudaTel v2

Dokumen ini adalah panduan standar industri untuk melakukan *deployment*, pemeliharaan berkala, dan penanganan insiden darurat aplikasi **GarudaTel v2** pada server produksi Linux (Ubuntu 22.04 / 24.04 LTS).

---

## 🖥️ 1. Spesifikasi Server Minimum

| Komponen | Spesifikasi Rekomendasi |
| :--- | :--- |
| **Sistem Operasi** | Ubuntu 22.04 LTS / 24.04 LTS |
| **CPU** | 1–2 vCPU |
| **RAM** | 2 GB (Minimum 1 GB dengan 1 GB Swap) |
| **Penyimpanan** | 20 GB SSD / NVMe |
| **Python** | Python 3.10, 3.11, atau 3.12 |
| **Web Server** | Nginx (Reverse Proxy) + Gunicorn (WSGI Server) |

---

## 🚀 2. Langkah-Langkah Deployment Baru

### Langkah 1: Persiapan Environment Sistem
```bash
# Update sistem paket
sudo apt update && sudo apt upgrade -y

# Install dependensi yang diperlukan
sudo apt install -y python3-venv python3-pip nginx sqlite3 certbot python3-certbot-nginx git
```

### Langkah 2: Setup Direktori Aplikasi & Virtual Environment
```bash
# Navigasi ke direktori aplikasi
cd /root/garudatel_v2

# Buat virtual environment python
python3 -m venv venv
source venv/bin/activate

# Install seluruh paket dependensi produksi
pip install --upgrade pip
pip install -r requirements.txt
```

### Langkah 3: Konfigurasi Kunci Lingkungan (.env)
Pastikan file `.env` di direktori root sudah terisi dengan kredensial aman:
```ini
# Production Secret Key (64 karakter hex)
SECRET_KEY=39d3530fff01af616d63de37dbc0591aea5f67b9fa3ffc3cc26e323b90bcd623

# Kredensial Provider Digiflazz
DIGI_USER=username_anda
DIGI_KEY=api_key_production
DIGI_URL=https://api.digiflazz.com/v1

# Kredensial Payment Gateway PaymentKita (QRIS)
PAYMENTKITA_MERCHANT_ID=merchant_id_anda
PAYMENTKITA_SECRET=secret_key_anda

# WhatsApp Bot API Endpoint
WA_BOT_URL=http://127.0.0.1:3000/api/send
```

---

## ⚙️ 3. Konfigurasi Systemd Service (Auto-Start & Healing)

Salin konfigurasi service ke `/etc/systemd/system/garudatel.service`:

```ini
[Unit]
Description=GarudaTel v2 Gunicorn Application Service
After=network.target

[Service]
User=root
Group=root
WorkingDirectory=/root/garudatel_v2
Environment="PATH=/root/garudatel_v2/venv/bin"
ExecStart=/root/garudatel_v2/venv/bin/gunicorn -w 3 -b 127.0.0.1:5000 --access-logfile /root/garudatel_v2/storage/logs/gunicorn_access.log --error-logfile /root/garudatel_v2/storage/logs/gunicorn_error.log wsgi:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Aktifkan service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable garudatel.service
sudo systemctl start garudatel.service
sudo systemctl status garudatel.service
```

---

## 🔒 4. Konfigurasi Reverse Proxy Nginx & SSL Gratis

1. Salin konfigurasi Nginx:
   ```bash
   sudo cp /root/garudatel_v2/deployment/nginx_garudatel.conf /etc/nginx/sites-available/garudatel
   sudo ln -s /etc/nginx/sites-available/garudatel /etc/nginx/sites-enabled/
   ```

2. Tes sintaks dan reload Nginx:
   ```bash
   sudo nginx -t
   sudo systemctl reload nginx
   ```

3. Dapatkan Sertifikat SSL Gratis (Let's Encrypt):
   ```bash
   sudo certbot --nginx -d garudatel.com -d www.garudatel.com
   ```

---

## 💾 5. Konfigurasi Backup Otomatis (Cron Job)

Database SQLite berjalan dalam mode **WAL (Write-Ahead Logging)**, sehingga backup dapat berjalan bersamaan dengan transaksi aktif tanpa resiko database terkunci.

Tambahkan skrip backup ke crontab root:
```bash
sudo crontab -e
```
Tambahkan baris berikut (dijalankan setiap pukul 02:00 pagi WIB):
```cron
0 2 * * * /bin/bash /root/garudatel_v2/tools/backup_database.sh >> /root/garudatel_v2/storage/logs/backup.log 2>&1
```

---

## 📊 6. Monitoring & Pemantauan Sistem

### A. Healthcheck Uptime Otomatis
Aplikasi dilengkapi endpoint monitoring kesehatan sistem yang dapat di-ping setiap menit:
- **URL**: `https://garudatel.com/health`
- **Output Sehat (HTTP 200)**:
  ```json
  {
    "status": "healthy",
    "database": "connected",
    "version": "2.0.0",
    "environment": "production"
  }
  ```
- Dapat dihubungkan ke layanan seperti Uptime Kuma, Pingdom, atau Datadog.

### B. Memantau Log Realtime
```bash
# Log aplikasi transaksi
tail -f /root/garudatel_v2/storage/logs/garudatel.log

# Log service Gunicorn
sudo journalctl -u garudatel.service -f

# Log Nginx
sudo tail -f /var/log/nginx/garudatel_error.log
```

---

## 🆘 7. Prosedur Tanggap Darurat & Rollback

### Restart Cepat Service
```bash
sudo systemctl restart garudatel.service
```

### Mengembalikan Database dari Backup (Restore)
Jika database mengalami kendala:
```bash
# 1. Hentikan service
sudo systemctl stop garudatel.service

# 2. Backup database yang bermasalah terlebih dahulu
mv /root/garudatel_v2/app/garudatel.db /root/garudatel_v2/app/garudatel.db.corrupted

# 3. Ekstrak backup terakhir
cd /root/garudatel_v2/storage/backups
gunzip -k garudatel_TERAKHIR.db.gz
cp garudatel_TERAKHIR.db /root/garudatel_v2/app/garudatel.db

# 4. Nyalakan service kembali
sudo systemctl start garudatel.service
```

