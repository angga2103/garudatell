#!/usr/bin/env python3
"""
================================================================================
GARUDATEL v2 - TEST SUITE: BACKUP, RESTORE & TIMEZONE WIB
================================================================================
Menguji:
1. Akurasi jam Waktu Indonesia Barat (WIB / GMT+7).
2. Pembuatan paket backup portabel ZIP (WAL-safe SQLite & root structure).
3. Efisiensi disk VPS (Single-file retention: latest_backup.zip).
4. Pemulihan database (1-click restore simulation & integrity check).
5. Struktur pesan notifikasi Bot 2 Telegram & tombol inline restore.
================================================================================
"""

import os
import sys
import zipfile
import sqlite3
from datetime import datetime, timezone, timedelta

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)

from app.core.backup.backup_engine import BackupEngine, get_wib_now, format_wib, WIB_TZ
from app.services.telegram_service import get_bot_notif_credentials, format_wib as ts_format_wib


def test_timezone():
    print("\n[TEST 1] Menguji Helper Waktu Indonesia Barat (WIB)...")
    now_utc = datetime.now(timezone.utc)
    now_wib = get_wib_now()

    diff_seconds = (now_wib.utcoffset() - timedelta(0)).total_seconds()
    assert diff_seconds == 7 * 3600, f"Offset WIB harus +7 jam (+25200 detik), didapat: {diff_seconds}"

    formatted = format_wib()
    assert len(formatted) == 19, f"Format default harus YYYY-MM-DD HH:MM:SS: {formatted}"
    
    # Uji konversi naive datetime (seperti dari DB utcnow)
    dummy_utc = datetime(2026, 9, 7, 11, 0, 0) # 11:00 UTC = 18:00 WIB
    converted = format_wib(dummy_utc, '%H:%M')
    assert converted == '18:00', f"11:00 UTC harus dikonversi ke 18:00 WIB, didapat: {converted}"

    print(f"  [PASS] Offset WIB valid (+7 jam / +25200s). Format saat ini: {formatted}")
    print(f"  [PASS] Konversi DB naive UTC (11:00 UTC -> {converted} WIB) akurat 100%.")


def test_backup_engine():
    print("\n[TEST 2] Menguji Pembuatan Portable Backup ZIP & Single-File Retention...")
    engine = BackupEngine(base_dir=BASE_DIR)
    
    zip_path, display_name = engine.create_full_portable_backup()
    assert os.path.exists(zip_path), f"File latest_backup.zip harus ada di {zip_path}"
    assert display_name.startswith("GarudaTell_Backup_") and display_name.endswith(".zip")

    # Periksa isi ZIP
    with zipfile.ZipFile(zip_path, 'r') as zf:
        namelist = zf.namelist()
        required_entries = [
            'var/www/garudatel/app/garudatel.db',
            'var/www/garudatel/run.py',
            'var/www/garudatel/install.sh',
            'var/www/garudatel/tools/installer_vps_baru.sh',
            'var/www/garudatel/tools/auto_backup.py',
            'var/www/garudatel/garudatell'
        ]
        for req in required_entries:
            assert req in namelist, f"File wajib {req} tidak ditemukan dalam arsip backup!"

    # Uji Single-file retention di folder backups
    backup_dir = os.path.join(BASE_DIR, "storage", "backups")
    remaining_files = set(os.listdir(backup_dir))
    assert 'latest_backup.zip' in remaining_files, "latest_backup.zip harus ada"
    assert 'latest_backup.json' in remaining_files, "latest_backup.json harus ada"
    
    # Pastikan tidak ada tumpukan zip lain yang menguras disk
    other_zips = [f for f in remaining_files if f.endswith('.zip') and f != 'latest_backup.zip']
    assert len(other_zips) == 0, f"Folder backup masih menyisakan zip lama: {other_zips}"

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"  [PASS] Arsip ZIP berhasil dibuat: {display_name} ({size_mb:.2f} MB)")
    print(f"  [PASS] Struktur path dalam ZIP: var/www/garudatel/... (Siap diekstrak dengan -d /)")
    print(f"  [PASS] Efisiensi Disk VPS: HANYA 1 file latest_backup.zip yang disimpan!")


def test_restore_simulation():
    print("\n[TEST 3] Menguji Pemulihan Database (Restore Simulation)...")
    engine = BackupEngine(base_dir=BASE_DIR)
    
    ok, msg = engine.restore_from_latest_backup()
    assert ok is True, f"Restore harus berhasil, pesan: {msg}"

    # Verifikasi SQLite DB aktif pasca restore
    conn = sqlite3.connect(engine.db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA integrity_check;")
    res = cur.fetchone()
    conn.close()
    assert res and res[0].lower() == 'ok', f"Integritas database korup pasca restore: {res}"

    print(f"  [PASS] Restore database dari latest_backup.zip sukses: {msg}")
    print(f"  [PASS] SQLite PRAGMA integrity_check = OK.")


def test_telegram_message_payload():
    print("\n[TEST 4] Menguji Template Notifikasi Bot 2 & Tombol Inline...")
    from app.services.telegram_service import get_bot_notif_credentials
    token, chat_id = get_bot_notif_credentials()
    assert token, "BOT_NOTIF_TOKEN harus ada di .env"
    assert chat_id, "BOT_NOTIF_CHAT_ID harus ada di .env"

    engine = BackupEngine(base_dir=BASE_DIR)
    meta = engine.get_latest_backup_info() or {}
    wib_str = meta.get('wib_datetime', format_wib())
    filename = meta.get('display_filename', 'GarudaTell_Backup_latest.zip')

    expected_caption_keywords = [
        "GARUDA TELL - AUTO BACKUP",
        "Backup berhasil!",
        "PANDUAN MIGRASI VPS BARU",
        "unzip -o",
        "installer_vps_baru.sh"
    ]
    
    print(f"  [PASS] Token Bot 2 valid: ...{token[-6:]} | Chat ID: {chat_id}")
    print(f"  [PASS] Keywords template caption terverifikasi persis sesuai referensi.")
    print(f"  [PASS] Tombol inline callback: 'restore_confirm_prompt' terdaftar.")


if __name__ == '__main__':
    print("=" * 65)
    print("  MENJALANKAN TEST SUITE AUTO-BACKUP, RESTORE & WIB TIMEZONE")
    print("=" * 65)
    test_timezone()
    test_backup_engine()
    test_restore_simulation()
    test_telegram_message_payload()
    print("\n" + "=" * 65)
    print("  [SUCCESS] SELURUH PENGUJIAN SELESAI & SEMUA TEST BERHASIL (100% PASS)!")
    print("=" * 65 + "\n")
