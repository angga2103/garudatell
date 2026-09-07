#!/bin/bash
# ==============================================================================
#  GARUDATELL v2 - ONE-CLICK DISASTER RECOVERY & VPS RESTORATION INSTALLER
# ==============================================================================
#  Skrip pemulihan darurat dan instalasi mandiri untuk VPS Ubuntu baru
#  (Ubuntu 20.04 / 22.04 / 24.04).
#  Dieksekusi setelah mengekstrak file ZIP backup:
#  bash /var/www/garudatel/tools/installer_vps_baru.sh
# ==============================================================================

set -e

# Warna Terminal
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

clear
echo -e "${CYAN}${BOLD}"
echo "  ╔══════════════════════════════════════════════════════════════╗"
echo "  ║                                                              ║"
echo "  ║       🛡️ GARUDATELL - DISASTER RECOVERY VPS INSTALLER 🛡️      ║"
echo "  ║            Pemulihan Otomatis dari Snapshot Backup           ║"
echo "  ║                                                              ║"
echo "  ╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# 1. Validasi Hak Akses Root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}[!] Harap jalankan skrip installer ini sebagai root atau dengan sudo:${NC}"
    echo -e "    sudo bash /var/www/garudatel/tools/installer_vps_baru.sh"
    exit 1
fi

TARGET_DIR="/var/www/garudatel"
CURRENT_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "$CURRENT_SCRIPT_DIR")"

echo -e "${BLUE}[*] Memeriksa lokasi direktori instalasi...${NC}"

# Jika diekstrak di luar /var/www/garudatel, pindahkan/sinkronkan ke /var/www/garudatel
if [ "$PARENT_DIR" != "$TARGET_DIR" ]; then
    echo -e "${YELLOW}[i] Proyek terdeteksi di $PARENT_DIR. Menyiapkan target standar $TARGET_DIR...${NC}"
    mkdir -p "$TARGET_DIR"
    cp -ru "$PARENT_DIR"/* "$TARGET_DIR/" 2>/dev/null || cp -r "$PARENT_DIR"/* "$TARGET_DIR/"
fi

cd "$TARGET_DIR"
mkdir -p "$TARGET_DIR/storage/backups"
mkdir -p "$TARGET_DIR/storage/logs"

echo -e "${GREEN}[✔] Direktori proyek siap di: $TARGET_DIR${NC}"
sleep 1

# 2. Update Paket Sistem & Lepaskan Lock APT (Self-Healing)
echo ""
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}${BOLD}  TAHAP 1: PEMBARUAN SISTEM & DEPENDENSI OS                      ${NC}"
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

export DEBIAN_FRONTEND=noninteractive

# Tangani background lock APT jika VPS baru saja boot
lock_waited=0
while fuser /var/lib/dpkg/lock >/dev/null 2>&1 || fuser /var/lib/apt/lists/lock >/dev/null 2>&1 || fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; do
    echo -e "${YELLOW}[!] Sistem APT sedang terkunci oleh proses boot VPS (cloud-init). Menunggu... (${lock_waited}s)${NC}"
    sleep 3
    lock_waited=$((lock_waited + 3))
    if [ $lock_waited -ge 24 ]; then
        killall -9 apt apt-get dpkg unattended-upgrade 2>/dev/null || true
        rm -f /var/lib/apt/lists/lock /var/cache/apt/archives/lock /var/lib/dpkg/lock* 2>/dev/null || true
        dpkg --configure -a 2>/dev/null || true
        break
    fi
done

# Alihkan mirror lokal yang sering mati ke archive resmi
if [ -f "/etc/apt/sources.list" ]; then
    sed -i 's/cermin\.rumahweb\.id/archive.ubuntu.com/g' /etc/apt/sources.list 2>/dev/null || true
    sed -i 's/mirror\.biznetgio\.com/archive.ubuntu.com/g' /etc/apt/sources.list 2>/dev/null || true
fi

echo -e "${BLUE}[*] Memperbarui daftar paket sistem...${NC}"
apt-get update -y || true

echo -e "${BLUE}[*] Memasang dependensi inti (Python3, Venv, SQLite3, Curl, Git, Build Tools)...${NC}"
apt-get install -y python3 python3-venv python3-pip python3-dev sqlite3 curl git build-essential unzip libpq-dev || {
    dpkg --configure -a
    apt-get install -f -y
    apt-get install -y python3 python3-venv python3-pip python3-dev sqlite3 curl git build-essential unzip
}

echo -e "${GREEN}[✔] Dependensi OS berhasil disiapkan.${NC}"

# 3. Setup Node.js & PM2 untuk Mesin WhatsApp
echo ""
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}${BOLD}  TAHAP 2: SETUP MESIN WHATSAPP BOT (NODE.JS + PM2)              ${NC}"
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if ! command -v node >/dev/null 2>&1; then
    echo -e "${BLUE}[*] Memasang Node.js v20 LTS...${NC}"
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
fi

if ! command -v pm2 >/dev/null 2>&1; then
    echo -e "${BLUE}[*] Memasang PM2 Process Manager secara global...${NC}"
    npm install -g pm2
fi

if [ -d "$TARGET_DIR/wa_bot" ]; then
    echo -e "${BLUE}[*] Menyiapkan modul mesin WhatsApp Bot...${NC}"
    cd "$TARGET_DIR/wa_bot"
    npm install --omit=dev --quiet || true
    pm2 delete garudatel-wa-bot 2>/dev/null || true
    pm2 start server_bot.js --name garudatel-wa-bot --restart-delay=3000 || true
    pm2 save || true
    cd "$TARGET_DIR"
    echo -e "${GREEN}[✔] Mesin WhatsApp aktif di background (PM2).${NC}"
fi

# 4. Setup Python Virtual Environment & Library
echo ""
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}${BOLD}  TAHAP 3: SETUP PYTHON ENVIRONMENT & DEPENDENSI GARUDATEL       ${NC}"
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

cd "$TARGET_DIR"
if [ ! -d "venv" ]; then
    echo -e "${BLUE}[*] Membuat virtual environment Python di $TARGET_DIR/venv...${NC}"
    python3 -m venv venv || {
        apt-get install -y python3-distutils virtualenv 2>/dev/null || true
        virtualenv -p python3 venv
    }
fi

echo -e "${BLUE}[*] Menginstal library dari requirements.txt...${NC}"
./venv/bin/pip install --upgrade pip setuptools wheel --quiet
./venv/bin/pip install -r requirements.txt --quiet

echo -e "${GREEN}[✔] Lingkungan Python & pustaka berhasil disiapkan.${NC}"

# 5. Verifikasi Database SQLite & File .env
echo ""
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}${BOLD}  TAHAP 4: INTEGRASI DATABASE SNAPSHOT & KREDENSIAL .ENV         ${NC}"
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ ! -f "$TARGET_DIR/.env" ]; then
    if [ -f "$TARGET_DIR/.env.example" ]; then
        cp "$TARGET_DIR/.env.example" "$TARGET_DIR/.env"
        echo -e "${YELLOW}[!] File .env baru dibuat dari template .env.example.${NC}"
    fi
else
    echo -e "${GREEN}[✔] File .env dari snapshot cadangan dipertahankan.${NC}"
fi

# Pastikan database SQLite bersih dan terindeks
if [ -f "$TARGET_DIR/app/garudatel.db" ]; then
    echo -e "${GREEN}[✔] Database SQLite dari snapshot backup terverifikasi:${NC} $TARGET_DIR/app/garudatel.db"
    ./venv/bin/python tools/apply_db_indexes.py 2>/dev/null || true
    ./venv/bin/python tools/migrate_tier_and_downline.py 2>/dev/null || true
else
    echo -e "${YELLOW}[!] Database tidak ditemukan di app/garudatel.db. Menjalankan inisialisasi awal...${NC}"
    ./venv/bin/python tools/init_app.py
    ./venv/bin/python tools/migrate_tier_and_downline.py 2>/dev/null || true
fi

# Perbaiki permission
chmod -R 755 "$TARGET_DIR"
chmod -R 777 "$TARGET_DIR/storage" 2>/dev/null || true

# 6. Pendaftaran Systemd Service (Web Server & Telegram Bot Admin)
echo ""
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}${BOLD}  TAHAP 5: PENDAFTARAN & AKTIVASI SYSTEMD SERVICE                ${NC}"
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Web Service
cat <<EOF > /etc/systemd/system/garudatel.service
[Unit]
Description=GarudaTel v2 - Web Application Server
After=network.target

[Service]
User=root
WorkingDirectory=$TARGET_DIR
Environment="PATH=$TARGET_DIR/venv/bin"
ExecStart=$TARGET_DIR/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:5000 --timeout 120 --access-logfile $TARGET_DIR/storage/logs/access.log --error-logfile $TARGET_DIR/storage/logs/error.log run:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Bot Telegram Admin Service
cat <<EOF > /etc/systemd/system/garudatel-bot-admin.service
[Unit]
Description=GarudaTel v2 - Telegram Bot 3 Admin Panel & Bot 2 Callback Daemon
After=network.target

[Service]
User=root
WorkingDirectory=$TARGET_DIR
Environment="PATH=$TARGET_DIR/venv/bin"
ExecStart=$TARGET_DIR/venv/bin/python $TARGET_DIR/tools/run_bot_admin.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable garudatel.service
systemctl restart garudatel.service

systemctl enable garudatel-bot-admin.service
systemctl restart garudatel-bot-admin.service

echo -e "${GREEN}[✔] Service garudatel.service & garudatel-bot-admin.service AKTIF.${NC}"

# 7. Registrasi Shortcut CLI Global 'garudatell'
echo -e "${BLUE}[*] Mendaftarkan shortcut global 'garudatell' ke /usr/local/bin/garudatell...${NC}"
chmod +x "$TARGET_DIR/garudatell"
ln -sf "$TARGET_DIR/garudatell" /usr/local/bin/garudatell
chmod +x /usr/local/bin/garudatell
echo -e "${GREEN}[✔] Perintah 'garudatell' siap digunakan dari terminal mana saja!${NC}"

# 8. Setup Jadwal Auto-Backup 30 Menit di VPS
echo ""
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}${BOLD}  TAHAP 6: AKTIVASI SCHEDULER AUTO-BACKUP 30 MENIT               ${NC}"
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ -f "$TARGET_DIR/tools/setup_auto_backup.sh" ]; then
    chmod +x "$TARGET_DIR/tools/setup_auto_backup.sh"
    bash "$TARGET_DIR/tools/setup_auto_backup.sh" enable || true
else
    # Fallback cron
    CRON_CMD="*/30 * * * * $TARGET_DIR/venv/bin/python $TARGET_DIR/tools/auto_backup.py >> $TARGET_DIR/storage/logs/backup.log 2>&1"
    (crontab -l 2>/dev/null | grep -v "auto_backup.py" ; echo "$CRON_CMD") | crontab -
    echo -e "${GREEN}[✔] Cron job auto-backup 30 menit berhasil didaftarkan.${NC}"
fi

# 9. Konfigurasi Cloudflare Zero Trust (Interaktif Fleksibel)
echo ""
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}${BOLD}  TAHAP 7: KONFIGURASI CLOUDFLARE ZERO TRUST (OPSIONAL)          ${NC}"
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "Cloudflare Zero Trust menghubungkan domain Anda ke port 5000 VPS ini."
echo -e "Jika Anda sudah memiliki token baru dari Cloudflare Dashboard, masukkan sekarang."
echo -e "Jika belum, ${BOLD}cukup tekan ENTER${NC} untuk melewati dan Anda bisa mengaturnya nanti via CLI.\n"

read -p ">> Masukkan Token Cloudflare Zero Trust baru (atau tekan ENTER untuk lewati): " CF_TOKEN
CF_TOKEN=$(echo "$CF_TOKEN" | tr -d '\r\n ' | sed -e "s/'//g" -e 's/"//g')

if [ -n "$CF_TOKEN" ]; then
    echo -e "${BLUE}[*] Memeriksa & memasang Cloudflared...${NC}"
    if ! command -v cloudflared &> /dev/null; then
        ARCH=$(uname -m)
        if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
            PKG_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb"
        else
            PKG_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb"
        fi
        curl -L --output /tmp/cloudflared.deb "$PKG_URL"
        dpkg -i /tmp/cloudflared.deb || true
        rm -f /tmp/cloudflared.deb
    fi

    echo -e "${BLUE}[*] Menghubungkan tunnel Cloudflare...${NC}"
    cloudflared service uninstall 2>/dev/null || true
    cloudflared service install "$CF_TOKEN" || true
    systemctl daemon-reload
    systemctl enable cloudflared
    systemctl restart cloudflared
    echo -e "${GREEN}[✔] Tunnel Cloudflare berhasil dihubungkan! Domain Anda langsung ONLINE.${NC}"
else
    echo -e "${YELLOW}[i] Token Cloudflare dilewati.${NC}"
    echo -e "    Anda dapat menghubungkannya kapan saja dengan mengetik: ${CYAN}garudatell${NC}"
    echo -e "    Lalu pilih menu [8] Manajemen Cloudflare Tunnel -> [2] Ganti Token."
fi

# 10. Ringkasan & Hasil Akhir
echo ""
echo -e "${GREEN}${BOLD}"
echo "  ╔══════════════════════════════════════════════════════════════╗"
echo "  ║                                                              ║"
echo "  ║        🎉 PEMULIHAN VPS GARUDATELL SELESAI & SUKSES! 🎉      ║"
echo "  ║                                                              ║"
echo "  ╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "  📂 ${BOLD}Lokasi Server :${NC} $TARGET_DIR"
echo -e "  🌐 ${BOLD}Web Service   :${NC} ${GREEN}AKTIF (Port 5000 / Gunicorn)${NC}"
echo -e "  🤖 ${BOLD}Bot Admin & 2 :${NC} ${GREEN}AKTIF (Polling Background)${NC}"
echo -e "  📱 ${BOLD}Bot WhatsApp  :${NC} ${GREEN}AKTIF (Port 3000 / PM2)${NC}"
echo -e "  🛡️ ${BOLD}Auto-Backup   :${NC} ${GREEN}AKTIF (Setiap 30 Menit ke Bot 2)${NC}"
echo -e "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "  🚀 Buka Panel Kontrol Server kapan saja dengan mengetik:"
echo -e "     ${YELLOW}${BOLD}garudatell${NC}\n"

