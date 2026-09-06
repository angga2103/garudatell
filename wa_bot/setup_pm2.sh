#!/bin/bash
set -e

echo "============================================================"
echo "🚀 SETUP & MENYALAKAN MESIN WHATSAPP BOT GARUDATEL VIA PM2"
echo "============================================================"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

echo "[*] Lokasi kerja: $DIR"

# 1. Pastikan dependencies terpasang
if [ ! -d "node_modules" ]; then
    echo "[*] Menginstall node_modules..."
    npm install --omit=dev
fi

# 2. Hentikan instance lama jika ada
pm2 delete garudatel-wa-bot 2>/dev/null || true

# 3. Jalankan server_bot.js di PM2
echo "[*] Menjalankan server_bot.js dengan PM2..."
pm2 start server_bot.js --name garudatel-wa-bot --restart-delay=3000

# 4. Simpan konfigurasi PM2
pm2 save

echo "============================================================"
echo "✅ MESIN WHATSAPP BOT BERHASIL DIAKTIFKAN DI PORT 3000!"
echo "   Periksa status dengan: pm2 status"
echo "   Periksa log dengan   : pm2 logs garudatel-wa-bot"
echo "============================================================"
