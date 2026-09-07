#!/usr/bin/env python3
"""
================================================================================
GARUDATEL v2 - AUTO BACKUP RUNNER (30 MENIT SCHEDULER)
================================================================================
Menjalankan pencadangan otomatis berkala (setiap 30 menit):
1. Membuat snapshot database SQLite online (WAL mode safe).
2. Mengemas arsip portabel mandiri (GarudaTell_Backup_YYYYMMDD_HHMMSS.zip).
3. Mengirimkan dokumen backup ke Bot 2 (Notifikasi & Backup) Telegram
   dilengkapi tombol inline '🔄 Restore Data ke VPS Ini' dan panduan migrasi.
4. Menyimpan satu salinan 'latest_backup.zip' di VPS dan membersihkan arsip lama
   demi menghemat kapasitas penyimpanan SSD server.
================================================================================
"""

import os
import sys
import logging
from datetime import datetime

# Set path root proyek
BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)

# Setup Logging
LOG_DIR = os.path.join(BASE_DIR, "storage", "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "backup.log")

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [AutoBackup] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding='utf-8')
    ]
)
logger = logging.getLogger("AutoBackup")

from app.core.backup.backup_engine import BackupEngine, format_wib
from app.services.telegram_service import send_backup_notification


def run_auto_backup():
    logger.info("=======================================================")
    logger.info("  MEMULAI PROSES AUTO-BACKUP BERKALA (30 MENIT)")
    logger.info("=======================================================")

    engine = BackupEngine(base_dir=BASE_DIR)

    try:
        # 1. Buat Arsip Backup Portabel & Snapshot SQLite WAL
        logger.info("Mempersiapkan snapshot database SQLite dan arsip portabel...")
        latest_zip, display_name = engine.create_full_portable_backup()
        file_size_mb = os.path.getsize(latest_zip) / (1024 * 1024)
        logger.info(f"Arsip cadangan berhasil dibuat: {display_name} ({file_size_mb:.2f} MB)")

        # 2. Kirim Dokumen ke Bot 2 Telegram
        logger.info("Mengunggah dokumen backup ke Telegram Bot 2 (Notifikasi & Backup)...")
        ok, res_text = send_backup_notification(
            backup_file_path=latest_zip,
            status="SUKSES",
            display_filename=display_name
        )

        if ok:
            logger.info(f"[OK] AUTO-BACKUP SUKSES: {display_name} terkirim ke Telegram!")
        else:
            logger.warning(f"[WARN] Backup lokal selesai, tetapi gagal kirim ke Telegram: {res_text}")

        # 3. Log metadata
        meta = engine.get_latest_backup_info()
        logger.info(f"Status Penyimpanan VPS: 1 file aktif di storage/backups/latest_backup.zip")
        logger.info("Proses auto-backup 30 menit selesai dengan tertib.\n")
        return True

    except Exception as e:
        logger.error(f"[ERROR] KENDALA AUTO-BACKUP: {str(e)}", exc_info=True)
        try:
            send_backup_notification(
                backup_file_path=None,
                status="GAGAL",
                details=f"Gagal saat proses pencadangan otomatis: {str(e)}"
            )
        except Exception:
            pass
        return False


if __name__ == '__main__':
    success = run_auto_backup()
    sys.exit(0 if success else 1)
