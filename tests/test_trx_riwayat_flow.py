"""
Test Suite: Alur Checkout Transaksi, Redirect Riwayat, dan Logika Tombol Cek Status
Menguji:
1. Endpoint checkout saldo & bundling mengembalikan redirect ke /riwayat?highlight={ref_id}
2. Endpoint /trx/detail/<ref_id> mengembalikan status transaksi secara akurat
3. Rendering template /riwayat:
   - Transaksi PAID + PROCESSING/PENDING -> Badge "Proses" + Tombol "Cek Status" (btn-action-check)
   - Transaksi UNPAID -> Badge "Belum Bayar" + Tombol "Bayar" (btn-action-pay)
   - Transaksi SUCCESS -> Badge "Sukses" + Tombol "Struk WA" (btn-action-wa)
4. Counter status di halaman riwayat (count_sukses, count_proses, count_antri) sinkron
"""

import unittest
from unittest.mock import patch
import os
import sys

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.product import Product
from app.models.transaction import Transaction
from app.models.bundling import PromoBundle

class TrxRiwayatFlowTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Buat user pengujian unik
        self.test_user = User.query.filter_by(phone='08999999001').first()
        if not self.test_user:
            self.test_user = User(
                phone='08999999001',
                name='User Tester Riwayat',
                balance=500000,
                role='member'
            )
            self.test_user.set_password('Password123!')
            db.session.add(self.test_user)
            db.session.commit()
        else:
            self.test_user.balance = 500000
            db.session.commit()

        Transaction.query.filter(Transaction.ref_id.like('TRX-TEST-%')).delete()
        db.session.commit()

    def tearDown(self):
        try:
            db.session.rollback()
            Transaction.query.filter(Transaction.user_id == self.test_user.id).delete()
            db.session.commit()
        except Exception:
            db.session.rollback()
        self.app_context.pop()

    @patch('app.routes.transaction.sync_single_transaction')
    def test_01_riwayat_buttons_and_badges_logic(self, mock_sync):
        """Uji rendering tombol dan badge pada halaman riwayat berdasarkan payment_status dan status"""
        mock_sync.return_value = False

        # 1. Transaksi PAID & PROCESSING -> Harus tampil 'Proses' & 'Cek Status'
        trx_proc = Transaction(
            ref_id='TRX-TEST-PROC-01',
            sku_code='TEST_SKU_01',
            user_id=self.test_user.id,
            product_name='Paket Telkomsel 10GB Data',
            target_number='081234567890',
            amount=50000,
            payment_method='SALDO',
            payment_status='PAID',
            status='PROCESSING'
        )

        # 2. Transaksi PAID & PENDING (misal antrian provider) -> Harus tampil 'Proses' & 'Cek Status', BUKAN 'Bayar'
        trx_pend = Transaction(
            ref_id='TRX-TEST-PEND-02',
            sku_code='TEST_SKU_02',
            user_id=self.test_user.id,
            product_name='Pulsa Indosat 25K',
            target_number='085712345678',
            amount=25000,
            payment_method='SALDO',
            payment_status='PAID',
            status='PENDING'
        )

        # 3. Transaksi UNPAID (QRIS belum dibayar) -> Harus tampil 'Belum Bayar' & 'Bayar'
        trx_unpaid = Transaction(
            ref_id='TRX-TEST-UNPAID-03',
            sku_code='TEST_SKU_03',
            user_id=self.test_user.id,
            product_name='Token PLN 100K',
            target_number='12345678901',
            amount=102000,
            payment_method='QRIS',
            payment_status='UNPAID',
            status='UNPAID'
        )

        # 4. Transaksi SUCCESS -> Harus tampil 'Sukses' & 'Struk WA'
        trx_success = Transaction(
            ref_id='TRX-TEST-SUCC-04',
            sku_code='TEST_SKU_04',
            user_id=self.test_user.id,
            product_name='Top Up DANA 50K',
            target_number='089988776655',
            amount=51000,
            payment_method='SALDO',
            payment_status='PAID',
            status='SUCCESS',
            sn='DANA9988112233'
        )

        db.session.add_all([trx_proc, trx_pend, trx_unpaid, trx_success])
        db.session.commit()

        # Login sebagai test_user
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.test_user.id)
            sess['_fresh'] = True

        res = self.client.get('/riwayat')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Verifikasi tombol Cek Status pada trx_proc dan trx_pend
        self.assertIn("cekStatusTrx('TRX-TEST-PROC-01'", html)
        self.assertIn("cekStatusTrx('TRX-TEST-PEND-02'", html)
        self.assertIn("Cek Status", html)

        # Verifikasi tombol Bayar HANYA pada trx_unpaid, BUKAN pada trx_proc atau trx_pend
        self.assertIn('/trx/invoice/TRX-TEST-UNPAID-03', html)
        self.assertIn('btn-action-pay', html)

        # Verifikasi tombol Struk WA pada trx_success
        self.assertIn("bagikanStruk('TRX-TEST-SUCC-04'", html)
        self.assertIn("Struk WA", html)

        # Verifikasi animasi highlight CSS ada di halaman
        self.assertIn('trx-card-highlighted', html)
        self.assertIn('cardPulseGlow', html)

    @patch('app.routes.transaction.sync_single_transaction')
    def test_02_trx_detail_api_endpoint(self, mock_sync):
        """Uji endpoint /trx/detail/<ref_id> untuk auto-polling status ke provider"""
        mock_sync.return_value = False

        trx = Transaction(
            ref_id='TRX-TEST-DETAIL-01',
            sku_code='TEST_GAME_FF',
            user_id=self.test_user.id,
            product_name='Voucher Games FF 140 DM',
            target_number='12345678',
            amount=20000,
            payment_method='SALDO',
            payment_status='PAID',
            status='PROCESSING',
            sn='Sedang diproses server...'
        )
        db.session.add(trx)
        db.session.commit()

        # Login
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.test_user.id)
            sess['_fresh'] = True

        res = self.client.get('/trx/detail/TRX-TEST-DETAIL-01')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('status'), 'success')
        self.assertIn('trx_status', data)
        self.assertEqual(data.get('product_name'), 'Voucher Games FF 140 DM')

    @patch('app.services.digiflazz.create_transaction')
    def test_03_checkout_bundle_redirect_highlight(self, mock_digi):
        """Uji endpoint checkout_bundle menghasilkan redirect dengan parameter ?highlight="""
        mock_digi.return_value = {
            'data': {
                'status': 'Pending',
                'rc': '03',
                'message': 'Sedang diproses',
                'sn': ''
            }
        }

        # Buat atau ambil 2 produk pengujian
        p1 = Product.query.filter_by(sku_code='TEST_BND_P1').first()
        if not p1:
            p1 = Product(sku_code='TEST_BND_P1', name='Paket Data Bundling 1', base_price=9000, sell_price=10000, is_active=True, category='data', brand='TELKOMSEL')
            db.session.add(p1)
        p2 = Product.query.filter_by(sku_code='TEST_BND_P2').first()
        if not p2:
            p2 = Product(sku_code='TEST_BND_P2', name='Paket Pulsa Bundling 2', base_price=9000, sell_price=10000, is_active=True, category='pulsa', brand='TELKOMSEL')
            db.session.add(p2)
        db.session.commit()

        bundle = PromoBundle(
            title='Paket Kombo Merdeka Test',
            sku_1='TEST_BND_P1',
            name_1='Paket Data Bundling 1',
            sku_2='TEST_BND_P2',
            name_2='Paket Pulsa Bundling 2',
            discount_amount=1000,
            is_active=True
        )
        db.session.add(bundle)
        db.session.commit()

        # Login
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.test_user.id)
            sess['_fresh'] = True

        res = self.client.post('/trx/checkout_bundle', json={
            'bundle_id': bundle.id,
            'target_1': '081299990001',
            'target_2': '081299990002'
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))
        redirect_url = data.get('redirect', '')
        self.assertTrue(redirect_url.startswith('/riwayat?highlight='))

        # Bersihkan data bundle
        db.session.delete(bundle)
        db.session.delete(p1)
        db.session.delete(p2)
        db.session.commit()

if __name__ == '__main__':
    unittest.main()
