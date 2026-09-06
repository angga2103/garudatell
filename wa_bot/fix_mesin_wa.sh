#!/bin/bash
echo "============================================================"
echo "🛠️ RESET & RESTART MESIN WHATSAPP BOT GARUDATEL"
echo "============================================================"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

# 1. Matikan proses bot
pm2 stop garudatel-wa-bot 2>/dev/null || true

# 2. Hapus memori sesi yang macet
echo "[*] Membersihkan memori sesi lama..."
rm -rf auth_info_baileys

# 3. Nyalakan kembali PM2
echo "[*] Menyalakan ulang PM2..."
pm2 restart garudatel-wa-bot 2>/dev/null || pm2 start server_bot.js --name garudatel-wa-bot --restart-delay=3000
pm2 save

echo "============================================================"
echo "✅ MESIN WHATSAPP BERHASIL DIRESET & DIRESTART!"
echo "   Silakan buka Admin Panel untuk meminta kode pairing baru."
echo "============================================================"
