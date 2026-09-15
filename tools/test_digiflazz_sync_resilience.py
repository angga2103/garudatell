"""
Test Suite: Ketahanan & Keamanan Sinkronisasi Produk Digiflazz (Anti-Wipeout & Automation)
1. Cooldown Guard (5.5 menit / 330s) mencegah pelanggaran rate limit Digiflazz
2. All-Or-Nothing & Circuit Breaker: Kegagalan prepaid tidak menghapus atau menonaktifkan produk
3. Soft-Disable: Produk usang hanya dinonaktifkan (is_active=False), BUKAN di-hard-delete
4. Auto-Detect Gangguan: RC 55 & RC 62 otomatis mematikan produk secara instan
5. Endpoint Cron Job: Autentikasi token rahasia & eksekusi aman
"""

import os
import sys
import json
import time
import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.product import Product
from app.models.margin import MarginTier
from app.services.digiflazz import (
    sync_products,
    auto_handle_product_disruption,
    get_sync_cooldown_status,
    set_last_sync_timestamp,
    COOLDOWN_SECONDS
)

class TestDigiflazzSyncResilience(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Siapkan produk dummy untuk pengujian
        self.prod_prepaid = Product.query.filter_by(sku_code='TEST_PULSA_10K').first()
        if not self.prod_prepaid:
            self.prod_prepaid = Product(
                sku_code='TEST_PULSA_10K',
                name='Pulsa Telkomsel 10K',
                category='Pulsa',
                brand='Telkomsel',
                base_price=10200.0,
                sell_price=11000.0,
                is_active=True
            )
            db.session.add(self.prod_prepaid)

        self.prod_prepaid.is_active = True

        self.prod_gangguan = Product.query.filter_by(sku_code='TEST_PLN_20K').first()
        if not self.prod_gangguan:
            self.prod_gangguan = Product(
                sku_code='TEST_PLN_20K',
                name='Token PLN 20K',
                category='PLN',
                brand='PLN',
                base_price=20100.0,
                sell_price=21000.0,
                is_active=True
            )
            db.session.add(self.prod_gangguan)
        self.prod_gangguan.is_active = True

        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        self.app_context.pop()

    def test_01_auto_detect_gangguan_rc55_and_rc62(self):
        """Uji apakah RC 55 dan 62 langsung menonaktifkan is_active=False di DB secara instan."""
        self.assertTrue(self.prod_gangguan.is_active)

        # Simulasi RC 55 (Produk Gangguan)
        auto_handle_product_disruption('TEST_PLN_20K', '55', 'Produk gangguan dari provider')
        prod = Product.query.filter_by(sku_code='TEST_PLN_20K').first()
        self.assertFalse(prod.is_active, "Produk harus otomatis dinonaktifkan saat RC 55")

        # Aktifkan kembali lalu uji RC 62 (Seller Gangguan)
        prod.is_active = True
        db.session.commit()
        self.assertTrue(prod.is_active)

        auto_handle_product_disruption('TEST_PLN_20K', '62', 'Seller sedang mengalami gangguan')
        prod = Product.query.filter_by(sku_code='TEST_PLN_20K').first()
        self.assertFalse(prod.is_active, "Produk harus otomatis dinonaktifkan saat RC 62")

    def test_02_all_or_nothing_prepaid_failure_prevents_wipeout(self):
        """Uji jika request prepaid gagal (misal rate limit), produk lama TIDAK BOLEH terhapus atau dinonaktifkan."""
        self.assertTrue(self.prod_prepaid.is_active)

        # Mock: Prepaid gagal (Rate Limit 5 menit), tapi Pasca sukses
        def mock_get_price_list(cmd='prepaid', code=None):
            if cmd == 'prepaid':
                return False, [], "RC 43: Terkena rate limit Digiflazz 5 menit"
            else:
                return True, [
                    {'buyer_sku_code': 'PLN_PASCA', 'product_name': 'PLN Pasca', 'buyer_product_status': True, 'seller_product_status': True, 'admin': 1000}
                ], "Sukses"

        with patch('app.services.digiflazz.get_price_list', side_effect=mock_get_price_list):
            ok, msg = sync_products(force=True)

            # Sinkronisasi harus ditolak karena All-Or-Nothing
            self.assertFalse(ok, "Sinkronisasi harus dibatalkan jika salah satu kategori gagal")
            self.assertIn("gagal", msg.lower())

            # Cek bahwa produk prepaid MASIH ADA dan TETAP AKTIF di database
            prod = Product.query.filter_by(sku_code='TEST_PULSA_10K').first()
            self.assertIsNotNone(prod, "Produk TIDAK BOLEH dihapus saat prepaid gagal!")
            self.assertTrue(prod.is_active, "Produk harus tetap aktif dan aman dari wipeout!")

    def test_03_soft_disable_not_hard_delete(self):
        """Uji bahwa produk usang yang tidak lagi ada di Digiflazz hanya di-soft-disable (is_active=False), bukan di-delete."""
        # Mock: Kedua kategori sukses, tapi TEST_PULSA_10K tidak ada dalam respon (discontinued)
        def mock_get_price_list_all_pass(cmd='prepaid', code=None):
            if cmd == 'prepaid':
                return True, [
                    {'buyer_sku_code': 'NEW_SKU_1', 'product_name': 'Produk Baru 1', 'buyer_product_status': True, 'seller_product_status': True, 'price': 5000}
                ], "Sukses"
            else:
                return True, [
                    {'buyer_sku_code': 'PLN_PASCA', 'product_name': 'PLN Pasca', 'buyer_product_status': True, 'seller_product_status': True, 'admin': 1000}
                ], "Sukses"

        with patch('app.services.digiflazz.get_price_list', side_effect=mock_get_price_list_all_pass):
            ok, msg = sync_products(force=True)
            self.assertTrue(ok, "Sinkronisasi harus sukses saat kedua kategori pass")

            # Cek produk lama: Harus tetap ada di DB (bukan None), tapi is_active = False
            prod = Product.query.filter_by(sku_code='TEST_PULSA_10K').first()
            self.assertIsNotNone(prod, "Produk usang TIDAK BOLEH di-hard-delete!")
            self.assertFalse(prod.is_active, "Produk usang harus dinonaktifkan (soft-disable)")

    def test_04_cooldown_guard(self):
        """Uji bahwa cooldown 5.5 menit menolak eksekusi berturut-turut tanpa force=True."""
        # Catat sync time sekarang
        set_last_sync_timestamp()

        # Mock testing env dinonaktifkan sesaat untuk menguji guard produksi
        self.app.config['TESTING'] = False
        try:
            with patch.dict(os.environ, {'FLASK_ENV': 'production'}):
                in_cooldown, remaining, _ = get_sync_cooldown_status()
                self.assertTrue(in_cooldown, "Cooldown harus aktif setelah set_last_sync_timestamp")
                self.assertGreater(remaining, 0)

                # Panggil sync_products tanpa force -> harus ditolak karena cooldown
                ok, msg = sync_products(force=False)
                self.assertFalse(ok, "Sinkronisasi harus ditolak saat cooldown aktif")
                self.assertIn("Cooldown Aktif", msg)

                # Panggil dengan force=True -> harus melewati cooldown
                with patch('app.services.digiflazz.get_price_list', return_value=(True, [], "Sukses")):
                    ok_f, _ = sync_products(force=True)
                    self.assertTrue(ok_f, "force=True harus mengizinkan bypass cooldown")
        finally:
            self.app.config['TESTING'] = True

    def test_05_cron_endpoint_security(self):
        """Uji endpoint cron /api/cron/sync-products: token salah ditolak 403, token benar diproses 200."""
        # 1. Tanpa token -> 403
        res_no_token = self.client.post('/api/cron/sync-products')
        self.assertEqual(res_no_token.status_code, 403)
        data_no = json.loads(res_no_token.data.decode('utf-8'))
        self.assertEqual(data_no['status'], 'error')

        # 2. Token salah -> 403
        res_bad_token = self.client.post('/api/cron/sync-products?key=token_salah_123')
        self.assertEqual(res_bad_token.status_code, 403)

        # 3. Token benar via query param -> 200
        with patch('app.services.digiflazz.get_price_list', return_value=(True, [], "Sukses")):
            res_ok = self.client.post('/api/cron/sync-products?key=ipay-cron-secret-2026&force=1')
            self.assertEqual(res_ok.status_code, 200)
            data_ok = json.loads(res_ok.data.decode('utf-8'))
            self.assertIn(data_ok['status'], ['success', 'cooldown'])

        # 4. Token benar via Header X-Cron-Key -> 200
        with patch('app.services.digiflazz.get_price_list', return_value=(True, [], "Sukses")):
            res_header = self.client.get('/api/cron/sync-products?force=1', headers={'X-Cron-Key': 'ipay-cron-secret-2026'})
            self.assertEqual(res_header.status_code, 200)
            data_h = json.loads(res_header.data.decode('utf-8'))
            self.assertIn(data_h['status'], ['success', 'cooldown'])

if __name__ == '__main__':
    unittest.main()

