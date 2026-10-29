# ==============================================================================
# TOOL CLI: TERAPKAN HARGA CERDAS & SAFETY GUARD KE SELURUH PRODUK DI VPS
# ==============================================================================
# Menjalankan sinkronisasi tabel margin_tiers dan perhitungan ulang harga jual
# seluruh produk di database berdasarkan Pricing Engine Cerdas.
# ==============================================================================

import sys
import os

# Pastikan path root terdaftar
basedir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if basedir not in sys.path:
    sys.path.insert(0, basedir)

from app import create_app
from app.extensions import db
from app.models.margin import MarginTier
from app.models.product import Product
from app.services.pricing_service import calculate_smart_price, enforce_manual_price_safety_guard

app = create_app()

def run_smart_pricing_migration():
    with app.app_context():
        print("=== 1. MENYELARASKAN TABEL MARGIN_TIERS ===")
        tiers_data = [
            (1, 0.0, 12000.0, 400.0),
            (2, 12000.01, 50000.0, 700.0),
            (3, 50000.01, 100000.0, 1100.0),
            (4, 100000.01, 500000.0, 1800.0),
            (5, 500000.01, 99999999.0, 3000.0)
        ]

        for lvl, min_p, max_p, mrg in tiers_data:
            tier = MarginTier.query.filter_by(level=lvl).first()
            if not tier:
                tier = MarginTier(level=lvl, min_price=min_p, max_price=max_p, margin=mrg)
                db.session.add(tier)
            else:
                tier.min_price = min_p
                tier.max_price = max_p
                tier.margin = mrg

        db.session.commit()
        print("Tabel margin_tiers berhasil diperbarui dengan 5 level kontinu.")

        print("\n=== 2. MENGHITUNG ULANG HARGA JUAL KATALOG PRODUK ===")
        tiers = MarginTier.query.order_by(MarginTier.level.asc()).all()
        products = Product.query.all()

        auto_updated = 0
        manual_kept = 0
        safety_floor_triggered = 0

        for p in products:
            if getattr(p, 'is_manual_margin', False):
                # Proteksi Safety Floor pada produk manual
                is_trig, alert = enforce_manual_price_safety_guard(p, p.base_price)
                if is_trig:
                    safety_floor_triggered += 1
                    print(f"⚠️ [SAFETY FLOOR] {p.sku_code} ({p.name}): modal Rp {p.base_price:,.0f} > jual manual. Dinaikkan ke Rp {p.sell_price:,.0f}")
                else:
                    manual_kept += 1
            else:
                new_price = calculate_smart_price(p, tiers)
                if new_price > 0 and new_price != p.sell_price:
                    p.sell_price = new_price
                    auto_updated += 1

        db.session.commit()
        print(f"\nREKAPITULASI:")
        print(f"- Produk Otomatis Diperbarui: {auto_updated}")
        print(f"- Produk Manual Dipertahankan: {manual_kept}")
        print(f"- Produk Manual Safety Floor: {safety_floor_triggered}")
        print(f"- Total Produk: {len(products)}")
        print("\nBERHASIL: Seluruh harga produk telah tersinkronisasi dengan strategi harga cerdas!")

if __name__ == '__main__':
    run_smart_pricing_migration()
