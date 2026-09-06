#!/bin/bash
set -e

echo "============================================================"
echo "🚀 SETUP & MENYALAKAN MESIN WHATSAPP BOT GARUDATEL (VPS AUTO)"
echo "============================================================"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"
echo "[*] Direktori Kerja: $DIR"

# 1. Cek Node.js (Minimal v18 atau v20 disarankan)
if ! command -v node >/dev/null 2>&1; then
    echo "[!] Node.js belum terinstall. Menginstall Node.js 20 LTS..."
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -y
        apt-get install -y curl
        curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
        apt-get install -y nodejs
    else
        echo "[ERROR] apt-get tidak tersedia. Harap install Node.js 20 secara manual."
        exit 1
    fi
fi
echo "[+] Node.js terdeteksi: $(node -v) di $(which node)"

# 2. Cek NPM
if ! command -v npm >/dev/null 2>&1; then
    echo "[!] Menginstall npm..."
    if command -v apt-get >/dev/null 2>&1; then
        apt-get install -y npm || true
    fi
fi
echo "[+] NPM terdeteksi: $(npm -v) di $(which npm)"

# 3. Cek PM2
if ! command -v pm2 >/dev/null 2>&1; then
    echo "[*] PM2 belum terpasang. Menginstall PM2 secara global via npm..."
    npm install -g pm2
fi
echo "[+] PM2 terdeteksi: $(pm2 -v) di $(which pm2)"

# 4. Install dependencies wa_bot jika belum ada atau belum lengkap
if [ ! -d "node_modules/@whiskeysockets/baileys" ] || [ ! -d "node_modules/express" ] || [ ! -d "node_modules/axios" ]; then
    echo "[*] Menginstall dependensi (Baileys, Express, Pino, Axios)..."
    npm install --omit=dev
else
    echo "[+] Dependensi node_modules sudah lengkap."
fi

# 5. Hentikan worker lama jika ada
echo "[*] Membersihkan instance lama..."
pm2 delete garudatel-wa-bot 2>/dev/null || true

# 6. Jalankan server_bot.js dengan PM2
echo "[*] Menjalankan server_bot.js via PM2..."
pm2 start server_bot.js --name garudatel-wa-bot --restart-delay=3000
pm2 save
# Konfigurasi auto-start PM2 saat VPS reboot
echo "[*] Mengonfigurasi auto-startup PM2 saat reboot sistem..."
pm2 startup systemd -u root --hp /root 2>/dev/null || pm2 startup 2>/dev/null || true
pm2 save

# 7. Verifikasi respon port 3000
echo "[*] Menunggu inisialisasi socket port 3000..."
sleep 3

SUCCESS=0
for i in {1..5}; do
    if command -v curl >/dev/null 2>&1; then
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3000/api/health || echo "000")
        if [ "$HTTP_CODE" = "200" ]; then
            SUCCESS=1
            break
        fi
    fi
    sleep 1
done

echo "============================================================"
if [ "$SUCCESS" = "1" ]; then
    echo "✅ SUKSES! MESIN WHATSAPP BOT BERHASIL DIAKTIFKAN DI PORT 3000!"
    echo "   Status: pm2 status"
    echo "   Log   : pm2 logs garudatel-wa-bot"
else
    echo "⚠️ Mesin telah distart di PM2. Jika port 3000 belum merespons, cek log:"
    echo "   pm2 logs garudatel-wa-bot --lines 20"
fi
echo "============================================================"
