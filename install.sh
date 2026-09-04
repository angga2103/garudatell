#!/bin/bash
# ==============================================================================
#  GARUDATEL v2 - ONE-CLICK INSTALLER & CLOUDFLARE ZERO TRUST DEPLOYMENT
# ==============================================================================
#  Skrip instalasi otomatis interaktif untuk VPS Ubuntu / Debian.
#  Mendukung integrasi Cloudflare Zero Trust Tunnels (tanpa port forwarding),
#  Gunicorn systemd daemon, dan Bot Admin Telegram daemon.
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

# Bersihkan layar
clear

echo -e "${CYAN}${BOLD}"
echo "  ╔══════════════════════════════════════════════════════════════╗"
echo "  ║                                                              ║"
echo "  ║          🦅 GARUDATEL v2 - ONE-CLICK VPS INSTALLER 🦅        ║"
echo "  ║             Cloudflare Zero Trust + Python Gunicorn          ║"
echo "  ║                                                              ║"
echo "  ╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# 1. Validasi Akses Root / Sudo
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}[!] Harap jalankan skrip ini dengan hak akses root atau sudo:${NC}"
    echo -e "    sudo bash install.sh"
    exit 1
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CURRENT_USER="${SUDO_USER:-$USER}"

echo -e "${BLUE}[*] Direktori Proyek:${NC} $PROJECT_DIR"
echo -e "${BLUE}[*] User Eksekusi:${NC} $CURRENT_USER"
echo ""

# 2. Input Interaktif: Cloudflare Zero Trust Tunnel
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}${BOLD}  TAHAP 1: KONFIGURASI CLOUDFLARE ZERO TRUST TUNNEL (DOMAIN)     ${NC}"
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "Cloudflare Zero Trust menghubungkan domain ke server VPS secara aman"
echo -e "tanpa perlu mengekspos IP publik atau membuka port firewall."
echo ""
echo -e "Buka dashboard Cloudflare: ${CYAN}Zero Trust -> Networks -> Tunnels -> Add a tunnel${NC}"
echo -e "Pilih tipe 'Cloudflared', lalu salin ${BOLD}Tunnel Token${NC} yang muncul."
echo -e "(Token biasanya string panjang diawali: ${PURPLE}eyJhIjoiMTgyYT...${NC})"
echo ""

read -p ">> Masukkan Token Cloudflare Zero Trust (atau tekan ENTER untuk lewati): " CF_TOKEN
CF_TOKEN=$(echo "$CF_TOKEN" | tr -d '\r\n ' | sed -e "s/'//g" -e 's/"//g')

read -p ">> Masukkan Domain Utama Anda (contoh: garudatel.com, opsional): " DOMAIN_NAME
DOMAIN_NAME=$(echo "$DOMAIN_NAME" | tr -d '\r\n ')

echo ""
echo -e "${GREEN}[✔] Konfigurasi awal diterima.${NC}"
sleep 1

# 3. Update Paket Sistem & Dependensi Dasar
echo ""
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}${BOLD}  TAHAP 2: PEMBARUAN SISTEM & DEPENDENSI OS                      ${NC}"
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}[*] Memperbarui indeks paket APT...${NC}"
apt-get update -y

echo -e "${BLUE}[*] Memasang dependensi sistem (Python3, venv, pip, curl, git, sqlite3)...${NC}"
apt-get install -y python3 python3-venv python3-pip git curl sqlite3 build-essential libpq-dev

echo -e "${GREEN}[✔] Paket sistem berhasil disiapkan.${NC}"

# 4. Pembuatan Virtual Environment & Instalasi Modul Python
echo ""
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}${BOLD}  TAHAP 3: SETUP PYTHON ENVIRONMENT & REQUIREMENTS               ${NC}"
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
cd "$PROJECT_DIR"

if [ ! -d "venv" ]; then
    echo -e "${BLUE}[*] Membuat virtual environment 'venv'...${NC}"
    python3 -m venv venv
else
    echo -e "${GREEN}[✔] Virtual environment sudah ada.${NC}"
fi

echo -e "${BLUE}[*] Mengupgrade pip & memasang dependensi dari requirements.txt...${NC}"
./venv/bin/pip install --upgrade pip setuptools wheel
./venv/bin/pip install -r requirements.txt

echo -e "${GREEN}[✔] Seluruh pustaka Python berhasil terpasang.${NC}"

# 5. Konfigurasi File Lingkungan (.env)
echo ""
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}${BOLD}  TAHAP 4: GENERASI KEAMANAN & FILE .env                         ${NC}"
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo -e "${BLUE}[*] Menyalin template .env.example menjadi .env...${NC}"
        cp .env.example .env
    else
        touch .env
    fi

    # Buat Secret Key acak
    RANDOM_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    if grep -q "^SECRET_KEY=" .env; then
        sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$RANDOM_SECRET/" .env
    else
        echo "SECRET_KEY=$RANDOM_SECRET" >> .env
    fi
    echo -e "${GREEN}[✔] File .env berhasil dibuat dengan SECRET_KEY unik.${NC}"
else
    echo -e "${GREEN}[✔] File .env yang sudah ada dipertahankan.${NC}"
fi

# 6. Inisialisasi Database SQLite & Akun Default Admin
echo ""
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}${BOLD}  TAHAP 5: INISIALISASI DATABASE & AKUN ADMIN DEFAULT           ${NC}"
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
./venv/bin/python tools/init_app.py

# Set hak akses kepemilikan folder
chown -R "$CURRENT_USER:$CURRENT_USER" "$PROJECT_DIR"
chmod -R 755 "$PROJECT_DIR"
chmod -R 777 "$PROJECT_DIR/storage" 2>/dev/null || true

# 7. Pembuatan Systemd Service untuk Aplikasi Web (Gunicorn)
echo ""
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}${BOLD}  TAHAP 6: REGISTRASI SYSTEMD SERVICE                            ${NC}"
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

GUNICORN_SERVICE_FILE="/etc/systemd/system/garudatel.service"
echo -e "${BLUE}[*] Menulis konfigurasi service $GUNICORN_SERVICE_FILE...${NC}"

cat <<EOF > "$GUNICORN_SERVICE_FILE"
[Unit]
Description=GarudaTel v2 - Web Application Server
After=network.target

[Service]
User=$CURRENT_USER
WorkingDirectory=$PROJECT_DIR
Environment="PATH=$PROJECT_DIR/venv/bin"
ExecStart=$PROJECT_DIR/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:5000 --timeout 120 --access-logfile $PROJECT_DIR/storage/logs/access.log --error-logfile $PROJECT_DIR/storage/logs/error.log run:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Service Bot 3 Admin
BOT_SERVICE_FILE="/etc/systemd/system/garudatel-bot-admin.service"
echo -e "${BLUE}[*] Menulis konfigurasi service $BOT_SERVICE_FILE...${NC}"

cat <<EOF > "$BOT_SERVICE_FILE"
[Unit]
Description=GarudaTel v2 - Telegram Bot 3 Admin Panel
After=network.target

[Service]
User=$CURRENT_USER
WorkingDirectory=$PROJECT_DIR
Environment="PATH=$PROJECT_DIR/venv/bin"
ExecStart=$PROJECT_DIR/venv/bin/python $PROJECT_DIR/tools/run_bot_admin.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable garudatel.service
systemctl restart garudatel.service
echo -e "${GREEN}[✔] Service garudatel.service aktif dan berjalan di background.${NC}"

systemctl enable garudatel-bot-admin.service
systemctl restart garudatel-bot-admin.service
echo -e "${GREEN}[✔] Service garudatel-bot-admin.service aktif.${NC}"

# 8. Konfigurasi Cloudflare Zero Trust (Jika Token Diisi)
echo ""
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}${BOLD}  TAHAP 7: AKTIVASI CLOUDFLARE ZERO TRUST TUNNEL                 ${NC}"
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ -n "$CF_TOKEN" ]; then
    echo -e "${BLUE}[*] Memeriksa instalasi 'cloudflared'...${NC}"
    if ! command -v cloudflared &> /dev/null; then
        echo -e "${BLUE}[*] Mengunduh & memasang cloudflared daemon resmi...${NC}"
        ARCH=$(uname -m)
        if [ "$ARCH" = "x86_64" ]; then
            PKG_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb"
        elif [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
            PKG_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb"
        else
            PKG_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb"
        fi

        curl -L --output /tmp/cloudflared.deb "$PKG_URL"
        dpkg -i /tmp/cloudflared.deb
        rm -f /tmp/cloudflared.deb
        echo -e "${GREEN}[✔] Cloudflared berhasil diinstal.${NC}"
    fi

    echo -e "${BLUE}[*] Menghubungkan tunnel dengan token Cloudflare...${NC}"
    cloudflared service install "$CF_TOKEN" || true
    systemctl enable cloudflared
    systemctl restart cloudflared
    echo -e "${GREEN}[✔] Cloudflare Tunnel aktif! Domain Anda kini terhubung ke port 5000.${NC}"
else
    echo -e "${YELLOW}[!] Token Cloudflare dilewati. Anda dapat menghubungkan tunnel nanti dengan perintah:${NC}"
    echo -e "    sudo cloudflared service install <TOKEN_ANDA>"
fi

# 9. Ringkasan & Instruksi Akhir
echo ""
echo -e "${GREEN}${BOLD}"
echo "  ╔══════════════════════════════════════════════════════════════╗"
echo "  ║                                                              ║"
echo "  ║        🎉 INSTALASI GARUDATEL v2 BERHASIL DISELESAIKAN! 🎉    ║"
echo "  ║                                                              ║"
echo "  ╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

echo -e "${BOLD}STATUS SISTEM & INFORMASI LOGIN:${NC}"
echo -e "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ -n "$DOMAIN_NAME" ]; then
    echo -e "  🌐 URL Website      : ${CYAN}https://${DOMAIN_NAME}/${NC}"
    echo -e "  🔑 URL Panel Admin  : ${CYAN}https://${DOMAIN_NAME}/admin/login${NC}"
else
    echo -e "  🌐 Akses Lokal/IP   : ${CYAN}http://127.0.0.1:5000/${NC}"
    echo -e "  🔑 URL Panel Admin  : ${CYAN}http://127.0.0.1:5000/admin/login${NC}"
fi
echo -e "  👤 Username Admin   : ${BOLD}admin${NC}"
echo -e "  🔐 Password Admin   : ${BOLD}admin123${NC}"
echo -e "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -e "${BOLD}LANGKAH BERIKUTNYA DI PANEL ADMIN:${NC}"
echo -e "1. Buka URL Panel Admin di browser Anda dan login."
echo -e "2. Ganti password default di menu Akun demi keamanan."
echo -e "3. Masuk ke ${BOLD}Dashboard Admin${NC} lalu masukkan API Key provider Anda:"
echo -e "   • ${CYAN}Digiflazz${NC}      : Username & API Key (Pulsa, PLN, Data, E-Money)"
echo -e "   • ${CYAN}VIP-Reseller${NC}   : API ID & API Key (Top Up Games & Voucher)"
echo -e "   • ${CYAN}Pakasir / PK${NC}   : Project & API Key (Payment Gateway QRIS)"
echo -e "   • ${CYAN}Bot Telegram${NC}   : Token Bot 1 (CS), Bot 2 (Notif), Bot 3 (Admin)"
echo -e "4. Hubungkan WhatsApp Bot melalui menu QR Code WhatsApp jika diperlukan."
echo ""
echo -e "${BOLD}PERINTAH PENTING UNTUK PEMELIHARAAN (CLI):${NC}"
echo -e "• Cek status server web : ${YELLOW}sudo systemctl status garudatel${NC}"
echo -e "• Restart server web    : ${YELLOW}sudo systemctl restart garudatel${NC}"
echo -e "• Cek log error web     : ${YELLOW}tail -f storage/logs/error.log${NC}"
echo -e "• Cek status Bot Admin  : ${YELLOW}sudo systemctl status garudatel-bot-admin${NC}"
echo -e "• Backup Database cepat : ${YELLOW}./venv/bin/python -c 'from app.services.telegram_service import perform_database_backup; print(perform_database_backup())'${NC}"
echo ""
echo -e "${GREEN}${BOLD}Selamat menggunakan GarudaTel v2! 🚀${NC}"
