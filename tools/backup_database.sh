#!/usr/bin/env bash
# ==============================================================================
# GarudaTel v2 - Automated SQLite Database Backup Script
# Mendukung SQLite WAL mode (Zero Downtime / Non-blocking)
# Pasang di crontab: 0 2 * * * /bin/bash /root/garudatel_v2/tools/backup_database.sh
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
DB_PATH="${BASE_DIR}/app/garudatel.db"
BACKUP_DIR="${BASE_DIR}/storage/backups"
TIMESTAMP="$(date +'%Y%m%d_%H%M%S')"
BACKUP_FILE="${BACKUP_DIR}/garudatel_${TIMESTAMP}.db"
RETENTION_DAYS=7

# Pastikan folder backup tersedia
mkdir -p "${BACKUP_DIR}"

echo "[$(date)] Memulai proses backup database GarudaTel..."

if [ ! -f "${DB_PATH}" ]; then
    echo "[$(date)] ERROR: Database file tidak ditemukan di ${DB_PATH}!"
    exit 1
fi

# Gunakan sqlite3 .backup agar aman dijalankan saat transaksi sedang berlangsung
if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "${DB_PATH}" ".backup '${BACKUP_FILE}'"
else
    # Fallback cp jika sqlite3 cli tidak terpasang
    cp "${DB_PATH}" "${BACKUP_FILE}"
fi

# Kompresi file backup untuk menghemat disk storage
if command -v gzip >/dev/null 2>&1; then
    gzip -f "${BACKUP_FILE}"
    FINAL_BACKUP="${BACKUP_FILE}.gz"
else
    FINAL_BACKUP="${BACKUP_FILE}"
fi

FILE_SIZE=$(du -h "${FINAL_BACKUP}" | cut -f1)
echo "[$(date)] Backup sukses: ${FINAL_BACKUP} (Ukuran: ${FILE_SIZE})"

# Hapus backup yang lebih tua dari 7 hari
echo "[$(date)] Membersihkan backup kadaluarsa (> ${RETENTION_DAYS} hari)..."
find "${BACKUP_DIR}" -name "garudatel_*.db*" -type f -mtime +${RETENTION_DAYS} -delete

echo "[$(date)] Selesai. Seluruh proses backup berhasil!"

