#!/usr/bin/env python3
"""
================================================================================
GARUDATEL v2 - INITIALIZATION & SEEDER SCRIPT
================================================================================
Menyiapkan database awal untuk instalasi VPS baru atau fresh install:
1. Membuat semua tabel database SQLite (db.create_all())
2. Membuat akun admin default (username: admin, password: admin123)
3. Mengisi pengaturan MarginTier & Setting Poin default
4. Menyiapkan folder-folder storage runtime
================================================================================
"""

import sys
import os

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.admin import Admin
from app.models.margin import MarginTier
from app.models.setting import Setting

def init_app():
    print("[*] Menginisialisasi GarudaTel v2...")
    app = create_app()

    with app.app_context():
        # 1. Pastikan tabel terbuat
        db.create_all()
        print("  [OK] Tabel database SQLite berhasil diverifikasi/dibuat.")

        # 2. Buat folder-folder storage
        folders = [
            os.path.join(BASE_DIR, 'storage', 'logs'),
            os.path.join(BASE_DIR, 'storage', 'backups'),
            os.path.join(BASE_DIR, 'storage', 'temp'),
            os.path.join(BASE_DIR, 'storage', 'cache'),
        ]
        for f in folders:
            os.makedirs(f, exist_ok=True)
            gitkeep = os.path.join(f, '.gitkeep')
            if not os.path.exists(gitkeep):
                open(gitkeep, 'a').close()
        print("  [OK] Folder penyimpanan runtime siap.")

        # 3. Akun Admin Default
        existing_admin = Admin.query.first()
        if not existing_admin:
            default_admin = Admin(username='admin')
            default_admin.set_password('admin123')
            db.session.add(default_admin)
            db.session.commit()
            print("  [OK] Akun Admin default dibuat: username='admin' | password='admin123'")
        else:
            print(f"  [OK] Akun Admin sudah ada: '{existing_admin.username}'")

        # 4. Inisialisasi Margin Tier Default
        if MarginTier.query.count() == 0:
            defaults = [
                MarginTier(level=1, min_price=0, max_price=10000, margin=200),
                MarginTier(level=2, min_price=10001, max_price=50000, margin=500),
                MarginTier(level=3, min_price=50001, max_price=100000, margin=1000),
                MarginTier(level=4, min_price=100001, max_price=500000, margin=2500),
                MarginTier(level=5, min_price=500001, max_price=99999999, margin=5000)
            ]
            db.session.bulk_save_objects(defaults)
            db.session.commit()
            print("  [OK] MarginTier default berhasil diisi.")

        # 5. Inisialisasi Pengaturan Poin Default
        settings = [
            ('point_rate', '10', 'Nilai rupiah per 1 poin (contoh: 10 = Rp 10/poin)'),
            ('point_reward_per_trx', '1', 'Jumlah poin yang diperoleh member per transaksi sukses')
        ]
        for key, default_val, desc in settings:
            st = Setting.query.filter_by(key=key).first()
            if not st:
                new_st = Setting(key=key, value=default_val, description=desc)
                db.session.add(new_st)
        db.session.commit()
        print("  [OK] Pengaturan sistem default berhasil diisi.")

    print("\n[SUCCESS] Inisialisasi GarudaTel v2 Selesai 100%!")

if __name__ == '__main__':
    init_app()

