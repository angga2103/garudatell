"""
================================================================================
GARUDATEL v2 - BACKUP & RESTORE ENGINE (PORTABLE DISASTER RECOVERY)
================================================================================
Engine pencadangan mandiri dan pemulihan data untuk GarudaTel v2.
Fitur Utama:
1. Online SQLite WAL-safe Snapshot (Zero Downtime / Non-blocking).
2. Full Portable Archive (Siap diekstrak ke VPS baru & siap restore di VPS ini).
3. Single-File Storage Retention di VPS (Hanya menyimpan latest_backup.zip untuk hemat disk).
4. Safe Database Restoration dengan automated integrity check & safety rollback.
================================================================================
"""

import os
import sys
import shutil
import sqlite3
import zipfile
import json
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# Standardisasi Timezone WIB (Waktu Indonesia Barat / GMT+7)
WIB_TZ = timezone(timedelta(hours=7))

def get_wib_now():
    return datetime.now(WIB_TZ)

def format_wib(dt=None, fmt='%Y-%m-%d %H:%M:%S'):
    if dt is None:
        dt = get_wib_now()
    elif isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except Exception:
            return dt
    if hasattr(dt, 'tzinfo') and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc).astimezone(WIB_TZ)
    elif hasattr(dt, 'astimezone'):
        dt = dt.astimezone(WIB_TZ)
    return dt.strftime(fmt)


class BackupEngine:
    def __init__(self, base_dir=None):
        if base_dir:
            self.base_dir = os.path.abspath(base_dir)
        else:
            # Root project dir (4 tingkat dari app/core/backup/backup_engine.py)
            self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))

        self.storage_dir = os.path.join(self.base_dir, "storage")
        self.backup_dir = os.path.join(self.storage_dir, "backups")
        os.makedirs(self.backup_dir, exist_ok=True)

        self.latest_backup_zip = os.path.join(self.backup_dir, "latest_backup.zip")
        self.latest_backup_json = os.path.join(self.backup_dir, "latest_backup.json")
        self.db_path = os.path.join(self.base_dir, "app", "garudatel.db")

    def _timestamp_wib(self):
        return get_wib_now().strftime("%Y%m%d_%H%M%S")

    def create_online_db_snapshot(self, target_path):
        """
        Membuat snapshot database SQLite yang bersih dan konsisten
        menggunakan SQLite Online Backup API (WAL mode safe).
        """
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"Database sumber tidak ditemukan di: {self.db_path}")

        os.makedirs(os.path.dirname(target_path), exist_ok=True)

        src_conn = sqlite3.connect(self.db_path)
        dst_conn = sqlite3.connect(target_path)
        try:
            with dst_conn:
                src_conn.backup(dst_conn, pages=100, sleep=0.01)
        finally:
            dst_conn.close()
            src_conn.close()

        logger.info(f"[BackupEngine] Online SQLite snapshot berhasil: {target_path}")
        return target_path

    def create_full_portable_backup(self):
        """
        Membuat arsip ZIP penuh portabel untuk migrasi VPS baru maupun restore instan.
        - Menyimpan salinan tunggal di storage/backups/latest_backup.zip
        - Memberi nama display: GarudaTell_Backup_YYYYMMDD_HHMMSS.zip
        - Membersihkan file cadangan sementara di VPS demi efisiensi disk.
        
        Returns:
            tuple: (latest_backup_zip_path, display_filename)
        """
        ts = self._timestamp_wib()
        display_name = f"GarudaTell_Backup_{ts}.zip"
        temp_zip = os.path.join(self.backup_dir, f"temp_{display_name}")

        # 1. Buat snapshot database bersih di folder temporary
        temp_snap_dir = os.path.join(self.backup_dir, f"_snap_{ts}")
        os.makedirs(temp_snap_dir, exist_ok=True)
        snap_db_path = os.path.join(temp_snap_dir, "garudatel.db")

        try:
            self.create_online_db_snapshot(snap_db_path)

            # 2. Kompresi seluruh source code penting dengan prefix /var/www/garudatel/
            # agar saat di-unzip di VPS baru dengan `unzip -o <zip> -d /` langsung terpasang rapi
            prefix_in_zip = "var/www/garudatel"

            with zipfile.ZipFile(temp_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # A. Tambahkan snapshot database sebagai var/www/garudatel/app/garudatel.db
                zipf.write(snap_db_path, f"{prefix_in_zip}/app/garudatel.db")

                # B. Tambahkan folder app/ (kecuali db biner dan cache)
                app_dir = os.path.join(self.base_dir, "app")
                for root, dirs, files in os.walk(app_dir):
                    dirs[:] = [d for d in dirs if d not in ['__pycache__', '.git']]
                    for file in files:
                        if file.endswith('.pyc') or file in ['garudatel.db', 'garudatel.db-wal', 'garudatel.db-shm']:
                            continue
                        full_p = os.path.join(root, file)
                        rel_p = os.path.relpath(full_p, self.base_dir)
                        zipf.write(full_p, f"{prefix_in_zip}/{rel_p.replace(os.sep, '/')}")

                # C. Tambahkan tools/
                tools_dir = os.path.join(self.base_dir, "tools")
                if os.path.exists(tools_dir):
                    for root, dirs, files in os.walk(tools_dir):
                        dirs[:] = [d for d in dirs if d not in ['__pycache__']]
                        for file in files:
                            if file.endswith('.pyc'):
                                continue
                            full_p = os.path.join(root, file)
                            rel_p = os.path.relpath(full_p, self.base_dir)
                            zipf.write(full_p, f"{prefix_in_zip}/{rel_p.replace(os.sep, '/')}")

                # D. Tambahkan wa_bot/ (tanpa node_modules dan cache auth)
                wa_dir = os.path.join(self.base_dir, "wa_bot")
                if os.path.exists(wa_dir):
                    for root, dirs, files in os.walk(wa_dir):
                        dirs[:] = [d for d in dirs if d in ['wa_bot']] or []
                        for file in files:
                            if file in ['package.json', 'package-lock.json', 'server_bot.js', 'setup_pm2.sh']:
                                full_p = os.path.join(root, file)
                                rel_p = os.path.relpath(full_p, self.base_dir)
                                zipf.write(full_p, f"{prefix_in_zip}/{rel_p.replace(os.sep, '/')}")

                # E. Tambahkan file konfigurasi root
                root_files = [
                    'run.py', 'config.py', 'install.sh', 'requirements.txt',
                    'garudatell', '.env', '.env.example', 'README.md', '.gitignore'
                ]
                for r_file in root_files:
                    f_path = os.path.join(self.base_dir, r_file)
                    if os.path.exists(f_path):
                        zipf.write(f_path, f"{prefix_in_zip}/{r_file}")

            # 3. Pindahkan file ke latest_backup.zip (Atomic replace)
            if os.path.exists(self.latest_backup_zip):
                try:
                    os.remove(self.latest_backup_zip)
                except Exception:
                    pass

            shutil.move(temp_zip, self.latest_backup_zip)
            file_size = os.path.getsize(self.latest_backup_zip)

            # 4. Tulis metadata backup terbaru
            meta = {
                "display_filename": display_name,
                "timestamp": ts,
                "wib_datetime": format_wib(fmt="%Y-%m-%d %H:%M:%S"),
                "size_bytes": file_size,
                "size_mb": round(file_size / (1024 * 1024), 2)
            }
            with open(self.latest_backup_json, 'w') as mf:
                json.dump(meta, mf, indent=2)

            # 5. Pembersihan sisa backup lama di VPS (Hanya menyimpan 1 file latest_backup.zip)
            self.prune_local_backups_keep_latest()

            logger.info(f"[BackupEngine] Portable backup berhasil dibuat: {display_name} ({meta['size_mb']} MB)")
            return self.latest_backup_zip, display_name

        finally:
            if os.path.exists(temp_snap_dir):
                shutil.rmtree(temp_snap_dir, ignore_errors=True)
            if os.path.exists(temp_zip):
                try:
                    os.remove(temp_zip)
                except Exception:
                    pass

    def prune_local_backups_keep_latest(self):
        """
        Membersihkan file cadangan lama di VPS.
        HANYA menyisakan 'latest_backup.zip' dan 'latest_backup.json'
        untuk menghemat ruang disk SSD VPS secara maksimal.
        """
        if not os.path.exists(self.backup_dir):
            return

        keep_files = {'latest_backup.zip', 'latest_backup.json', '.gitkeep'}
        for item in os.listdir(self.backup_dir):
            item_path = os.path.join(self.backup_dir, item)
            if item in keep_files:
                continue
            try:
                if os.path.isfile(item_path) or os.path.islink(item_path):
                    os.remove(item_path)
                elif os.path.isdir(item_path) and item.startswith(('_snap_', 'temp_')):
                    shutil.rmtree(item_path, ignore_errors=True)
            except Exception as e:
                logger.warning(f"[BackupEngine] Gagal menghapus file sisa {item_path}: {e}")

    def restore_from_latest_backup(self):
        """
        Memulihkan database SQLite dari latest_backup.zip dengan prosedur aman:
        1. Validasi keberadaan file backup.
        2. Membuat safety backup (rollback point) dari DB aktif.
        3. Mengekstrak database dari ZIP dan me-replace file database aktif.
        4. Membersihkan file WAL lama (-wal, -shm).
        5. Melakukan SQLite integrity check.
        6. Jika gagal, otomatis melakukan rollback ke database sebelum restore.
        
        Returns:
            tuple: (bool, str) -> (success, message)
        """
        if not os.path.exists(self.latest_backup_zip):
            return False, f"File backup terbaru '{self.latest_backup_zip}' tidak ditemukan di VPS!"

        safety_rollback_db = self.db_path + ".safety_pre_restore"

        # 1. Buat safety copy jika database aktif ada
        if os.path.exists(self.db_path):
            try:
                shutil.copy2(self.db_path, safety_rollback_db)
            except Exception as e:
                return False, f"Gagal membuat safety backup database sebelum restore: {e}"

        temp_extract_dir = os.path.join(self.backup_dir, "_restore_temp")
        os.makedirs(temp_extract_dir, exist_ok=True)

        try:
            # 2. Buka ZIP dan cari file database
            with zipfile.ZipFile(self.latest_backup_zip, 'r') as zipf:
                db_entry = None
                for name in zipf.namelist():
                    if name.endswith("app/garudatel.db"):
                        db_entry = name
                        break

                if not db_entry:
                    return False, "File 'garudatel.db' tidak ditemukan di dalam arsip ZIP backup!"

                extracted_db = zipf.extract(db_entry, temp_extract_dir)

            # 3. Timpa database aktif
            shutil.copy2(extracted_db, self.db_path)

            # 4. Hapus file WAL & SHM lama agar SQLite membuka DB yang baru di-restore
            for suffix in ['-wal', '-shm']:
                wal_f = self.db_path + suffix
                if os.path.exists(wal_f):
                    try:
                        os.remove(wal_f)
                    except Exception:
                        pass

            # 5. SQLite Integrity Check
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check;")
            res = cursor.fetchone()
            conn.close()

            if not res or res[0].lower() != 'ok':
                raise ValueError(f"Hasil integrity check database tidak valid: {res}")

            # 6. Sukses: Hapus file rollback keamanan
            if os.path.exists(safety_rollback_db):
                try:
                    os.remove(safety_rollback_db)
                except Exception:
                    pass

            meta_info = self.get_latest_backup_info()
            wib_info = meta_info.get('wib_datetime') if meta_info else 'Terbaru'
            msg = f"Database berhasil dipulihkan dari backup ({wib_info}). Integrity check OK."
            logger.info(f"[BackupEngine] {msg}")
            return True, msg

        except Exception as err:
            logger.error(f"[BackupEngine] Gagal restore: {err}. Memulai rollback...")
            # Lakukan rollback
            if os.path.exists(safety_rollback_db):
                try:
                    shutil.copy2(safety_rollback_db, self.db_path)
                    os.remove(safety_rollback_db)
                    logger.info("[BackupEngine] Rollback database aktif berhasil dilakukan.")
                except Exception as rb_err:
                    logger.critical(f"[BackupEngine] Rollback kritis gagal: {rb_err}")
            return False, f"Proses restore gagal dan telah di-rollback: {str(err)}"

        finally:
            if os.path.exists(temp_extract_dir):
                shutil.rmtree(temp_extract_dir, ignore_errors=True)

    def get_latest_backup_info(self):
        """Mengambil data metadata dari backup terbaru."""
        if os.path.exists(self.latest_backup_json):
            try:
                with open(self.latest_backup_json, 'r') as f:
                    return json.load(f)
            except Exception:
                pass

        if os.path.exists(self.latest_backup_zip):
            sz = os.path.getsize(self.latest_backup_zip)
            return {
                "display_filename": "latest_backup.zip",
                "timestamp": self._timestamp_wib(),
                "wib_datetime": format_wib(fmt="%Y-%m-%d %H:%M:%S"),
                "size_bytes": sz,
                "size_mb": round(sz / (1024 * 1024), 2)
            }

        return None

    # Backward compatibility methods
    def backup_database(self):
        zip_p, _ = self.create_full_portable_backup()
        return zip_p

    def backup_env(self):
        dst = os.path.join(self.backup_dir, f".env_{self._timestamp_wib()}")
        src = os.path.join(self.base_dir, ".env")
        if os.path.exists(src):
            shutil.copy2(src, dst)
            return dst
        return None

    def backup_source(self):
        zip_p, _ = self.create_full_portable_backup()
        return zip_p
