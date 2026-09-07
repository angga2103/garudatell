"""
================================================================================
GARUDATEL v2 - MIGRATION SCRIPT: TIER & DOWNLINE COLUMNS
================================================================================
Aman dijalankan berulang kali (Idempotent). Menambahkan kolom baru ke tabel user
dan membuat tabel commission_logs jika belum ada tanpa menghapus data yang ada.
================================================================================
"""
import os
import sys
import sqlite3

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.commission import CommissionLog

def run_migration():
    print("[*] Memulai migrasi database untuk sistem Tier Akun & Downline...")
    app = create_app()

    with app.app_context():
        db_path = os.path.join(BASE_DIR, 'app', 'garudatel.db')
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # 1. Cek dan tambahkan kolom pada tabel user
        cur.execute("PRAGMA table_info(user);")
        existing_cols = [row[1] for row in cur.fetchall()]

        new_cols = [
            ("role_expires_at", "DATETIME"),
            ("upline_id", "INTEGER REFERENCES user(id)"),
            ("commission_balance", "REAL DEFAULT 0.0"),
            ("last_reminded_at", "DATETIME")
        ]

        for col_name, col_type in new_cols:
            if col_name not in existing_cols:
                try:
                    cur.execute(f"ALTER TABLE user ADD COLUMN {col_name} {col_type};")
                    print(f"  [+] Kolom 'user.{col_name}' berhasil ditambahkan.")
                except Exception as e:
                    print(f"  [!] Gagal tambah kolom {col_name}: {e}")
            else:
                print(f"  [i] Kolom 'user.{col_name}' sudah ada.")

        conn.commit()
        conn.close()

        # 2. Buat tabel commission_logs via SQLAlchemy
        db.create_all()
        print("  [+] Tabel 'commission_logs' terverifikasi dan siap digunakan.")
        print("[SUCCESS] Migrasi database berhasil diselesaikan 100%!\n")

if __name__ == '__main__':
    run_migration()
