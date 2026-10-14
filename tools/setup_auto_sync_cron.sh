#!/bin/bash
# ==============================================================================
#  GARUDATELL v2 - SCHEDULER AUTO-SYNC PRODUK DIGIFLAZZ (CRON MANAGER)
# ==============================================================================
#  Penggunaan:
#  bash tools/setup_auto_sync_cron.sh enable   -> Aktifkan auto-sync produk (30 menit)
#  bash tools/setup_auto_sync_cron.sh disable  -> Nonaktifkan auto-sync produk di cron
#  bash tools/setup_auto_sync_cron.sh status   -> Cek status jadwal cron & log sinkronisasi
#  bash tools/setup_auto_sync_cron.sh run      -> Jalankan sinkronisasi produk sekarang
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

SCRIPT_SYNC="$PROJECT_DIR/tools/cron_sync_products.py"
LOG_FILE="$PROJECT_DIR/storage/logs/cron_sync.log"
CRON_SCHEDULE="*/30 * * * *"
CRON_JOB="$CRON_SCHEDULE $PYTHON_EXEC $SCRIPT_SYNC >> $LOG_FILE 2>&1"

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
        echo -e "${BLUE}[*] Mendaftarkan jadwal auto-sync produk setiap 30 menit ke crontab...${NC}"
        mkdir -p "$PROJECT_DIR/storage/logs"
        
        # Hapus entri lama jika ada, lalu tambahkan entri baru
        (crontab -l 2>/dev/null | grep -v "cron_sync_products.py" ; echo "$CRON_JOB") | crontab -
        echo -e "${GREEN}[✔] Auto-sync produk 30 menit BERHASIL DIAKTIFKAN!${NC}"
        echo -e "    Jadwal: ${CYAN}Setiap 30 menit (${CRON_SCHEDULE})${NC}"
        echo -e "    Perintah: ${YELLOW}$CRON_JOB${NC}"
        echo -e "    Log File: ${CYAN}$LOG_FILE${NC}"
        ;;

    disable)
        echo -e "${BLUE}[*] Menonaktifkan jadwal auto-sync produk di crontab...${NC}"
        crontab -l 2>/dev/null | grep -v "cron_sync_products.py" | crontab -
        echo -e "${YELLOW}[✔] Auto-sync produk berhasil dinonaktifkan dari crontab.${NC}"
        ;;

    status)
        echo -e "${CYAN}${BOLD}=== STATUS AUTO-SYNC PRODUK DIGIFLAZZ ===${NC}"
        echo -e "Project Directory: $PROJECT_DIR"
        echo -e "Python Binary    : $PYTHON_EXEC"
        echo -e "Script Runner    : $SCRIPT_SYNC"
        echo -e "Log File         : $LOG_FILE"
        echo ""
        echo -e "${BOLD}1. Status Entri Crontab:${NC}"
        CRON_ACTIVE=$(crontab -l 2>/dev/null | grep "cron_sync_products.py")
        if [ -n "$CRON_ACTIVE" ]; then
            echo -e "   ${GREEN}[AKTIF / TERDAFTAR]${NC} -> $CRON_ACTIVE"
        else
            echo -e "   ${RED}[TIDAK AKTIF]${NC} Belum terdaftar di crontab pengguna."
            echo -e "   Jalankan: ${YELLOW}bash tools/setup_auto_sync_cron.sh enable${NC} untuk mengaktifkannya."
        fi
        echo ""
        echo -e "${BOLD}2. Catatan Log Terakhir (${LOG_FILE}):${NC}"
        if [ -f "$LOG_FILE" ]; then
            tail -n 15 "$LOG_FILE"
        else
            echo -e "   ${YELLOW}(File log belum terbentuk atau belum ada eksekusi cron)${NC}"
        fi
        ;;

    run)
        echo -e "${BLUE}[*] Menjalankan sinkronisasi produk langsung sekarang...${NC}"
        mkdir -p "$PROJECT_DIR/storage/logs"
        $PYTHON_EXEC "$SCRIPT_SYNC" --force
        ;;

    *)
        echo -e "${BOLD}Panduan Penggunaan:${NC}"
        echo "  bash tools/setup_auto_sync_cron.sh enable   -> Pasang auto-sync setiap 30 menit"
        echo "  bash tools/setup_auto_sync_cron.sh disable  -> Hapus jadwal dari crontab"
        echo "  bash tools/setup_auto_sync_cron.sh status   -> Cek status jadwal dan log"
        echo "  bash tools/setup_auto_sync_cron.sh run      -> Eksekusi sinkronisasi sekarang"
        exit 1
        ;;
esac
