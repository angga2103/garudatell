"""
Skrip pencadangan penuh (Full Backup Snapshot) GarudaTel v2.
Menghasilkan backup database online (SQLite WAL-safe) dan source code proyek.
"""
import os
import sys
import shutil
import sqlite3
import datetime
import zipfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIMESTAMP = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
BACKUP_NAME = f"backup_pre_github_push_{TIMESTAMP}"
BACKUP_ROOT = os.path.join(BASE_DIR, "archive", BACKUP_NAME)
ZIP_FILE = os.path.join(BASE_DIR, "archive", f"{BACKUP_NAME}.zip")

def create_backup():
    print("=" * 65)
    print("  MEMULAI PROSES BACKUP LENGKAP GARUDATEL v2")
    print("=" * 65)
    print(f"Timestamp: {TIMESTAMP}")
    print(f"Lokasi Backup: {BACKUP_ROOT}")

    os.makedirs(BACKUP_ROOT, exist_ok=True)

    # 1. Backup Database SQLite Menggunakan API Online Backup (WAL Safe)
    db_source = os.path.join(BASE_DIR, "app", "garudatel.db")
    db_backup_dir = os.path.join(BACKUP_ROOT, "database")
    os.makedirs(db_backup_dir, exist_ok=True)
    db_target = os.path.join(db_backup_dir, f"garudatel_{TIMESTAMP}.db")

    if os.path.exists(db_source):
        print("\n[1/4] Mencadangkan Database SQLite (Online WAL-safe backup)...")
        src_conn = sqlite3.connect(db_source)
        dst_conn = sqlite3.connect(db_target)
        with dst_conn:
            src_conn.backup(dst_conn, pages=100, sleep=0.01)
        dst_conn.close()
        src_conn.close()
        db_size_mb = os.path.getsize(db_target) / (1024 * 1024)
        print(f"  [OK] Database berhasil dicadangkan: {db_target} ({db_size_mb:.2f} MB)")
    else:
        print("  [SKIP] Database file tidak ditemukan di app/garudatel.db")

    # 2. Backup Kode Sumber (app/)
    print("\n[2/4] Mencadangkan Folder app/ (Routes, Models, Templates, Static)...")
    app_source = os.path.join(BASE_DIR, "app")
    app_target = os.path.join(BACKUP_ROOT, "app")

    def ignore_patterns(path, names):
        ignored = []
        for name in names:
            if name in ['__pycache__', 'garudatel.db', 'garudatel.db-wal', 'garudatel.db-shm']:
                ignored.append(name)
            elif name.endswith('.pyc'):
                ignored.append(name)
        return ignored

    shutil.copytree(app_source, app_target, ignore=ignore_patterns)
    print("  [OK] Folder app/ berhasil dicadangkan tanpa file biner sementara.")

    # 3. Backup Folder tools/, tests/, dan Dokumen Penting
    print("\n[3/4] Mencadangkan tools/, tests/, dan Dokumentasi...")
    for folder in ['tools', 'tests']:
        src_folder = os.path.join(BASE_DIR, folder)
        dst_folder = os.path.join(BACKUP_ROOT, folder)
        if os.path.exists(src_folder):
            shutil.copytree(src_folder, dst_folder, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))

    for doc in ['AI_HANDOVER_RULES.md', 'run.py', 'config.py', 'install.sh', 'requirements.txt', '.env.example', '.env', 'README.md', '.gitignore']:
        src_file = os.path.join(BASE_DIR, doc)
        if os.path.exists(src_file):
            shutil.copy2(src_file, os.path.join(BACKUP_ROOT, doc))
    print("  [OK] Seluruh script tools, tests, dan dokumentasi berhasil disalin.")

    # 4. Membuat File Kompresi .zip untuk kemudahan arsip/pemindahan
    print("\n[4/4] Mengompresi seluruh backup ke format .zip...")
    with zipfile.ZipFile(ZIP_FILE, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(BACKUP_ROOT):
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, BACKUP_ROOT)
                zipf.write(file_path, os.path.join(BACKUP_NAME, rel_path))

    zip_size_mb = os.path.getsize(ZIP_FILE) / (1024 * 1024)
    print(f"  [OK] File Zip berhasil dibuat: {ZIP_FILE} ({zip_size_mb:.2f} MB)")

    print("\n" + "=" * 65)
    print(f"  >>> BACKUP LENGKAP SUKSES TERSIMPAN! <<<")
    print(f"  Folder: {BACKUP_ROOT}")
    print(f"  Arsip : {ZIP_FILE}")
    print("=" * 65 + "\n")

if __name__ == '__main__':
    create_backup()

