#!/bin/bash
# ==============================================================================
#  GARUDATELL v2 - SCHEDULER AUTO-BACKUP 30 MENIT (CRON & TIMER MANAGER)
# ==============================================================================
#  Penggunaan:
#  bash tools/setup_auto_backup.sh enable   -> Aktifkan auto-backup 30 menit
#  bash tools/setup_auto_backup.sh disable  -> Nonaktifkan auto-backup
#  bash tools/setup_auto_backup.sh status   -> Cek status jadwal & log backup
#  bash tools/setup_auto_backup.sh run      -> Jalankan backup sekarang
# ==============================================================================

# Deteksi root path proyek
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
    DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
TOOLS_DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
PROJECT_DIR="$(dirname "$TOOLS_DIR")"

PYTHON_EXEC="$PROJECT_DIR/venv/bin/python"
if [ ! -f "$PYTHON_EXEC" ]; then
    PYTHON_EXEC="python3"
fi

SCRIPT_BACKUP="$PROJECT_DIR/tools/auto_backup.py"
LOG_FILE="$PROJECT_DIR/storage/logs/backup.log"
CRON_SCHEDULE="*/30 * * * *"
CRON_JOB="$CRON_SCHEDULE $PYTHON_EXEC $SCRIPT_BACKUP >> $LOG_FILE 2>&1"

# Warna
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

case "$1" in
    enable)
        echo -e "${BLUE}[*] Memasang jadwal auto-backup setiap 30 menit ke cron...${NC}"
        mkdir -p "$PROJECT_DIR/storage/logs"
        mkdir -p "$PROJECT_DIR/storage/backups"
        
        # Hapus entri lama jika ada, lalu tambahkan entri baru
        (crontab -l 2>/dev/null | grep -v "auto_backup.py" ; echo "$CRON_JOB") | crontab -
        echo -e "${GREEN}[✔] Auto-backup 30 menit BERHASIL DIAKTIFKAN!${NC}"
        echo -e "    Jadwal: ${CYAN}Setiap 30 menit (${CRON_SCHEDULE})${NC}"
        echo -e "    Perintah: ${YELLOW}$CRON_JOB${NC}"
        ;;

    disable)
        echo -e "${BLUE}[*] Menonaktifkan jadwal auto-backup di cron...${NC}"
        crontab -l 2>/dev/null | grep -v "auto_backup.py" | crontab -
        echo -e "${YELLOW}[✔] Auto-backup 30 menit berhasil dinonaktifkan.${NC}"
        ;;

    status)
        echo -e "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${CYAN}${BOLD}  STATUS SCHEDULER AUTO-BACKUP (30 MENIT)                        ${NC}"
        echo -e "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        
        CURRENT_CRON=$(crontab -l 2>/dev/null | grep "auto_backup.py" || true)
        if [ -n "$CURRENT_CRON" ]; then
            echo -e "  Status Scheduler : ${GREEN}● AKTIF (Berjalan setiap 30 menit)${NC}"
            echo -e "  Jadwal Cron      : ${YELLOW}$CURRENT_CRON${NC}"
        else
            echo -e "  Status Scheduler : ${RED}● NONAKTIF (Tidak terdaftar di crontab)${NC}"
        fi

        LATEST_ZIP="$PROJECT_DIR/storage/backups/latest_backup.zip"
        LATEST_JSON="$PROJECT_DIR/storage/backups/latest_backup.json"

        echo ""
        echo -e "${BOLD}Arsip Cadangan di VPS:${NC}"
        if [ -f "$LATEST_ZIP" ]; then
            ZIP_SIZE=$(du -h "$LATEST_ZIP" | cut -f1)
            ZIP_MOD=$(date -r "$LATEST_ZIP" "+%Y-%m-%d %H:%M:%S" 2>/dev/null || stat -c %y "$LATEST_ZIP" 2>/dev/null || echo "-")
            echo -e "  • File Aktif   : ${GREEN}$LATEST_ZIP${NC}"
            echo -e "  • Ukuran Disk  : ${YELLOW}$ZIP_SIZE${NC} (Hemat disk: hanya menyimpan 1 file terbaru)"
            echo -e "  • Waktu Dibuat : $ZIP_MOD"
            if [ -f "$LATEST_JSON" ]; then
                echo -e "  • Metadata     : $(cat "$LATEST_JSON" 2>/dev/null)"
            fi
        else
            echo -e "  ${YELLOW}[i] Belum ada file latest_backup.zip. Jalankan backup manual atau tunggu jadwal 30 menit.${NC}"
        fi

        echo ""
        echo -e "${BOLD}10 Baris Terakhir Log Auto-Backup ($LOG_FILE):${NC}"
        echo -e "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        if [ -f "$LOG_FILE" ] && [ -s "$LOG_FILE" ]; then
            tail -n 10 "$LOG_FILE"
        else
            echo -e "${YELLOW}(Belum ada catatan log backup)${NC}"
        fi
        echo -e "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ;;

    run)
        echo -e "${BLUE}[*] Menjalankan proses backup sekarang...${NC}"
        $PYTHON_EXEC "$SCRIPT_BACKUP"
        ;;

    *)
        echo "Penggunaan: $0 {enable|disable|status|run}"
        exit 1
        ;;
esac

