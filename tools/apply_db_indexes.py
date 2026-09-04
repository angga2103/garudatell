"""
Script to apply high-performance SQLite indexes to GarudaTel database.
"""
import sys
import os
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.product import Product
from app.models.transaction import Transaction

def apply_indexes():
    app = create_app()
    with app.app_context():
        print("=" * 60)
        print("  PENERAPAN INDEX DATABASE SQLITE UNTUK PERFORMA TINGGI  ")
        print("=" * 60)

        # 1. Benchmark Sebelum Index
        t0 = time.perf_counter()
        for _ in range(20):
            _ = Product.query.filter_by(category='Games', is_active=True).all()
        t_before = (time.perf_counter() - t0) * 1000 / 20.0
        print(f"Rata-rata waktu query Games SEBELUM Index: {t_before:.2f} ms")

        # 2. Daftar Index yang akan diterapkan
        indexes_sql = [
            "CREATE INDEX IF NOT EXISTS idx_product_category ON product (category);",
            "CREATE INDEX IF NOT EXISTS idx_product_brand ON product (brand);",
            "CREATE INDEX IF NOT EXISTS idx_product_is_active ON product (is_active);",
            "CREATE INDEX IF NOT EXISTS idx_product_cat_brand_active ON product (category, brand, is_active);",
            "CREATE INDEX IF NOT EXISTS idx_transaction_user_id ON \"transaction\" (user_id);",
            "CREATE INDEX IF NOT EXISTS idx_transaction_status ON \"transaction\" (status);",
            "CREATE INDEX IF NOT EXISTS idx_transaction_created_at ON \"transaction\" (created_at);",
            "CREATE INDEX IF NOT EXISTS idx_transaction_user_created ON \"transaction\" (user_id, created_at);",
            "CREATE INDEX IF NOT EXISTS idx_notifications_target_created ON notifications (target_user_id, created_at);",
            "CREATE INDEX IF NOT EXISTS idx_support_tickets_user_status ON support_tickets (user_id, status);",
            "CREATE INDEX IF NOT EXISTS idx_point_log_user_created ON point_log (user_id, created_at);"
        ]

        print("\nMenerapkan Index ke SQLite Database...")
        for sql in indexes_sql:
            idx_name = sql.split()[5]
            db.session.execute(db.text(sql))
            print(f"  [OK] Index terpasang: {idx_name}")
        db.session.commit()

        # Jalankan PRAGMA optimize
        db.session.execute(db.text("PRAGMA optimize;"))
        db.session.commit()
        print("  [OK] PRAGMA optimize dieksekusi.")

        # 3. Benchmark Setelah Index
        t1 = time.perf_counter()
        for _ in range(20):
            _ = Product.query.filter_by(category='Games', is_active=True).all()
        t_after = (time.perf_counter() - t1) * 1000 / 20.0
        print(f"\nRata-rata waktu query Games SESUDAH Index: {t_after:.2f} ms")
        speedup = ((t_before - t_after) / t_before * 100) if t_before > 0 else 0
        print(f"Peningkatan Kecepatan: {speedup:.1f}% lebih cepat!")

if __name__ == '__main__':
    apply_indexes()

