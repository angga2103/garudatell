#!/bin/bash
# =====================================================================
# GARUDATEL V2 - PRODUCTION DEPLOYMENT SCRIPT (GUNICORN)
# =====================================================================
# File: start_production.sh
# Deskripsi: Script untuk menjalankan aplikasi Flask dengan Gunicorn
# Tanggal: 30 Agustus 2026
# =====================================================================

echo "============================================"
echo "  GARUDATEL V2 - PRODUCTION STARTUP"
echo "============================================"

# 1. AKTIVASI VIRTUAL ENVIRONMENT (jika ada)
if [ -d "venv" ]; then
    echo "[INFO] Aktivasi virtual environment..."
    source venv/bin/activate
fi

# 2. CEK GUNICORN TERINSTALL
if ! command -v gunicorn &> /dev/null; then
    echo "[ERROR] Gunicorn tidak terinstall!"
    echo "[FIX] Jalankan: pip install gunicorn"
    exit 1
fi

# 3. CEK FILE .env
if [ ! -f ".env" ]; then
    echo "[WARNING] File .env tidak ditemukan!"
    echo "[INFO] Pastikan konfigurasi API sudah diatur."
fi

# 4. KONFIGURASI GUNICORN
WORKERS=4                  # Jumlah worker process (sesuaikan dengan CPU core)
BIND_ADDRESS="0.0.0.0:5000"  # IP dan Port
TIMEOUT=120                # Timeout untuk request (dalam detik)
LOG_LEVEL="info"           # Level log: debug, info, warning, error, critical
ACCESS_LOG="logs/access.log"
ERROR_LOG="logs/error.log"

# 5. BUAT FOLDER LOGS (jika belum ada)
mkdir -p logs

# 6. JALANKAN GUNICORN
echo "[INFO] Starting Gunicorn dengan konfigurasi:"
echo "  - Workers: $WORKERS"
echo "  - Bind: $BIND_ADDRESS"
echo "  - Timeout: $TIMEOUT seconds"
echo "  - Access Log: $ACCESS_LOG"
echo "  - Error Log: $ERROR_LOG"
echo ""

gunicorn \
    --workers $WORKERS \
    --bind $BIND_ADDRESS \
    --timeout $TIMEOUT \
    --log-level $LOG_LEVEL \
    --access-logfile $ACCESS_LOG \
    --error-logfile $ERROR_LOG \
    --reload \
    wsgi:app

# Note:
# - Hapus flag --reload untuk production (auto-reload hanya untuk dev)
# - Untuk daemon mode, gunakan: gunicorn --daemon ...
# - Untuk systemd service, lihat file garudatel.service
