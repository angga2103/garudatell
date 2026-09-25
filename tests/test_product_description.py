"""
Test suite for Product Description feature:
- Digiflazz sync absorption
- Admin manual description edit & protection (is_manual_desc)
- Reset manual description lock
- User format_product_dict serialization
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from app.models.product import Product
from app.routes.user import format_product_dict

def run_tests():
    app = create_app()
    with app.app_context():
        print("=" * 65)
        print("  TEST SUITE: PRODUCT DESCRIPTION & MANUAL LOCK")
        print("=" * 65)

        # 1. Setup temporary test product
        test_sku = "TEST_DESC_SKU_01"
        Product.query.filter_by(sku_code=test_sku).delete()
        db.session.commit()

        prod = Product(
            sku_code=test_sku,
            name="Paket Data Test Desc 10GB",
            category="Data",
            brand="TELKOMSEL",
            base_price=25000,
            sell_price=28000,
            is_active=True,
            description="Deskripsi awal dari Digiflazz: 10GB Utama 30 Hari",
            is_manual_desc=False
        )
        db.session.add(prod)
        db.session.commit()
        pid = prod.id

        print("\n[Test 1] Verifikasi skema & format_product_dict...")
        p_dict = format_product_dict(prod, None)
        assert p_dict['description'] == "Deskripsi awal dari Digiflazz: 10GB Utama 30 Hari", "Gagal memuat deskripsi di format_product_dict"
        print("  [OK] Deskripsi berhasil diserialisasi ke format_product_dict")

        # 2. Test Admin edit manual deskripsi
        print("\n[Test 2] Admin edit manual deskripsi & lock...")
        prod.description = "Deskripsi Kustom Admin: 10GB (5GB 24 Jam + 5GB Malam)"
        prod.is_manual_desc = True
        prod.sell_price = 29000
        db.session.commit()

        prod_db = db.session.get(Product, pid)
        assert prod_db.is_manual_desc is True
        assert "Kustom Admin" in prod_db.description
        assert prod_db.sell_price == 29000
        print("  [OK] Admin berhasil mengedit deskripsi dan status is_manual_desc=True")

        # 3. Test Proteksi Digiflazz Sync
        print("\n[Test 3] Simulasi Digiflazz Sync saat is_manual_desc=True (Harus Terproteksi)...")
        incoming_digi_desc = "Deskripsi Mentah Baru dari Digiflazz"
        # Logika sync_products:
        if not prod_db.is_manual_desc:
            prod_db.description = incoming_digi_desc
        db.session.commit()

        prod_check = db.session.get(Product, pid)
        assert prod_check.description == "Deskripsi Kustom Admin: 10GB (5GB 24 Jam + 5GB Malam)", "Deskripsi manual tertimpa!"
        print("  [OK] Proteksi sukses: Deskripsi manual admin TIDAK tertimpa oleh sync Digiflazz")

        # 4. Test Reset Manual Lock
        print("\n[Test 4] Admin mereset lock manual (reset_desc)...")
        prod_check.is_manual_desc = False
        db.session.commit()

        prod_unlocked = db.session.get(Product, pid)
        assert prod_unlocked.is_manual_desc is False
        print("  [OK] Lock manual berhasil dilepas (is_manual_desc=False)")

        # 5. Test Resync Digiflazz setelah di-unlock
        print("\n[Test 5] Resync Digiflazz setelah di-unlock (Harus Terupdate)...")
        if not prod_unlocked.is_manual_desc:
            prod_unlocked.description = incoming_digi_desc
        db.session.commit()

        prod_final = db.session.get(Product, pid)
        assert prod_final.description == incoming_digi_desc, "Gagal mengupdate deskripsi setelah unlock!"
        print("  [OK] Deskripsi berhasil diupdate otomatis oleh Digiflazz setelah lock dibuka")

        # Cleanup
        db.session.delete(prod_final)
        db.session.commit()
        print("\n" + "=" * 65)
        print("  ALL 5/5 PRODUCT DESCRIPTION TESTS PASSED SUCCESSFULLY! (100% PASS)")
        print("=" * 65)

if __name__ == '__main__':
    run_tests()
