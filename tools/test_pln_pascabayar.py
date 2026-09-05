import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

import unittest
from unittest.mock import patch
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.product import Product
from app.models.transaction import Transaction

class TestPLNPascabayar(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Buat user pengetesan
        self.test_user = User.query.filter_by(phone='081299990001').first()
        if not self.test_user:
            self.test_user = User(
                name='Test PLN User',
                phone='081299990001',
                balance=500000.0,
                is_active=True
            )
            self.test_user.set_password('Password123!')
            db.session.add(self.test_user)
            db.session.commit()
        else:
            self.test_user.balance = 500000.0
            db.session.commit()

        # Pastikan produk PLN Pascabayar ada di DB
        self.pln_pasca = Product.query.filter_by(sku_code='post685486').first()
        if not self.pln_pasca:
            self.pln_pasca = Product(
                sku_code='post685486',
                name='Pln Pascabayar',
                category='Pascabayar',
                brand='PLN PASCABAYAR',
                base_price=4000.0,
                sell_price=4200.0,
                is_active=True
            )
            db.session.add(self.pln_pasca)
            db.session.commit()

    def tearDown(self):
        try:
            if hasattr(self, 'test_user') and self.test_user:
                from app.models.point_log import PointLog
                PointLog.query.filter_by(user_id=self.test_user.id).delete()
                Transaction.query.filter(Transaction.ref_id.like('GT-PASCA-TEST%')).delete()
                User.query.filter_by(id=self.test_user.id).delete()
                db.session.commit()
        except Exception:
            db.session.rollback()
        self.app_context.pop()

    def login_client(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.test_user.id)
            sess['_fresh'] = True

    def test_01_kategori_pln_page_displays_cek_tagihan(self):
        res = self.client.get('/kategori/pln')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('CEK TAGIHAN', html)
        self.assertIn('pascaModal', html)
        self.assertIn('cekTagihanPascaModal', html)

    def test_02_inquiry_bill_requires_login(self):
        res = self.client.post('/trx/inquiry_bill', json={
            'sku_code': 'post685486',
            'customer_no': '530000000001'
        })
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertTrue(data.get('requires_login'))

    def test_03_inquiry_bill_validation_errors(self):
        self.login_client()
        res = self.client.post('/trx/inquiry_bill', json={
            'sku_code': 'post685486',
            'customer_no': ''
        })
        self.assertEqual(res.status_code, 400)
        res2 = self.client.post('/trx/inquiry_bill', json={
            'sku_code': 'post685486',
            'customer_no': '12345'
        })
        self.assertEqual(res2.status_code, 400)

    @patch('app.services.digiflazz.is_pln_cutoff_time', return_value=False)
    @patch('app.services.digiflazz.inquiry_pasca')
    def test_04_inquiry_bill_success_calculation(self, mock_inq, mock_cutoff):
        self.login_client()
        mock_inq.return_value = (True, {
            'rc': '00',
            'customer_name': 'BUDI SANTOSO',
            'customer_no': '530000000001',
            'admin': 2500,
            'price': 152500,
            'desc': {
                'tarif': 'R1',
                'daya': 1300,
                'lembar_tagihan': 1,
                'tagihan': {
                    'detail': [
                        {
                            'periode': '2026-08',
                            'nilai_tagihan': 150000,
                            'admin': 2500,
                            'denda': 0,
                            'total': 152500
                        }
                    ]
                }
            }
        }, "Inquiry Sukses")

        res = self.client.post('/trx/inquiry_bill', json={
            'sku_code': 'post685486',
            'customer_no': '530000000001'
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['customer_name'], 'BUDI SANTOSO')
        self.assertEqual(data['tagihan_pokok'], 150000.0)
        self.assertEqual(data['admin_fee'], 4200.0)
        self.assertEqual(data['total_bayar'], 154200.0)
        self.assertTrue(data['ref_id'].startswith('GT-PASCA-'))

    @patch('app.services.digiflazz.is_pln_cutoff_time', return_value=False)
    @patch('app.services.digiflazz.inquiry_pasca')
    def test_05_inquiry_bill_digiflazz_rejection(self, mock_inq, mock_cutoff):
        self.login_client()
        mock_inq.return_value = (False, {'rc': '48'}, "RC 48: Tagihan sudah lunas")

        res = self.client.post('/trx/inquiry_bill', json={
            'sku_code': 'post685486',
            'customer_no': '530000000001'
        })
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data['status'], 'error')
        self.assertIn('Tagihan sudah lunas', data['message'])

    def test_06_checkout_blocks_pasca_without_inquiry(self):
        self.login_client()
        res = self.client.post('/trx/checkout', json={
            'sku_code': 'post685486',
            'target_number': '530000000001',
            'payment_method': 'saldo'
        })
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertIn('Harap lakukan Cek Tagihan terlebih dahulu', data['message'])

    @patch('app.services.digiflazz.is_pln_cutoff_time', return_value=False)
    @patch('app.services.digiflazz.pay_pasca')
    def test_07_checkout_pasca_saldo_success(self, mock_pay, mock_cutoff):
        self.login_client()
        mock_pay.return_value = (True, {
            'rc': '00',
            'status': 'Sukses',
            'sn': 'PLN999888777666'
        }, "Pembayaran Sukses")

        test_ref = "GT-PASCA-TEST001"
        initial_balance = self.test_user.balance
        bill_amount = 154200.0

        res = self.client.post('/trx/checkout', json={
            'sku_code': 'post685486',
            'target_number': '530000000001',
            'payment_method': 'saldo',
            'inquiry_ref_id': test_ref,
            'amount': bill_amount
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'success')

        user_after = User.query.get(self.test_user.id)
        self.assertEqual(user_after.balance, initial_balance - bill_amount)

        trx = Transaction.query.filter_by(ref_id=test_ref).first()
        self.assertIsNotNone(trx)
        self.assertEqual(trx.status, 'SUCCESS')
        self.assertEqual(trx.sn, 'PLN999888777666')
        self.assertFalse(trx.is_prepaid)

    @patch('app.services.digiflazz.is_pln_cutoff_time', return_value=False)
    @patch('app.services.digiflazz.pay_pasca')
    def test_08_checkout_pasca_saldo_refund_on_failure(self, mock_pay, mock_cutoff):
        self.login_client()
        mock_pay.return_value = (False, {
            'rc': '52',
            'status': 'Gagal'
        }, "RC 52: Saldo Buyer tidak mencukupi untuk bayar tagihan")

        test_ref = "GT-PASCA-TEST002"
        initial_balance = self.test_user.balance
        bill_amount = 154200.0

        res = self.client.post('/trx/checkout', json={
            'sku_code': 'post685486',
            'target_number': '530000000001',
            'payment_method': 'saldo',
            'inquiry_ref_id': test_ref,
            'amount': bill_amount
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'error')

        user_after = User.query.get(self.test_user.id)
        self.assertEqual(user_after.balance, initial_balance)

        trx = Transaction.query.filter_by(ref_id=test_ref).first()
        self.assertIsNotNone(trx)
        self.assertEqual(trx.status, 'FAILED')

    @patch('app.services.digiflazz.is_pln_cutoff_time', return_value=False)
    def test_09_checkout_pasca_qris_creation(self, mock_cutoff):
        self.login_client()
        test_ref = "GT-PASCA-TEST003"
        bill_amount = 154200.0

        res = self.client.post('/trx/checkout', json={
            'sku_code': 'post685486',
            'target_number': '530000000001',
            'payment_method': 'qris',
            'inquiry_ref_id': test_ref,
            'amount': bill_amount
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['ref_id'], test_ref)

        trx = Transaction.query.filter_by(ref_id=test_ref).first()
        self.assertIsNotNone(trx)
        self.assertEqual(trx.payment_method, 'QRIS')
        self.assertEqual(trx.payment_status, 'UNPAID')
        self.assertFalse(trx.is_prepaid)

    @patch('app.services.digiflazz.is_pln_cutoff_time', return_value=True)
    def test_10_pln_cutoff_blocks_inquiry_and_checkout(self, mock_cutoff):
        self.login_client()

        # 1. Halaman PLN menampilkan banner cut off
        res_page = self.client.get('/kategori/pln')
        self.assertEqual(res_page.status_code, 200)
        html = res_page.get_data(as_text=True)
        self.assertIn('cutoff-alert-banner', html)
        self.assertIn('JADWAL CUT OFF & MAINTENANCE PLN', html)

        # 2. Inquiry tagihan ditolak dengan 400 is_cutoff=True
        res_inq = self.client.post('/trx/inquiry_bill', json={
            'sku_code': 'post685486',
            'customer_no': '530000000001'
        })
        self.assertEqual(res_inq.status_code, 400)
        data_inq = res_inq.get_json()
        self.assertTrue(data_inq.get('is_cutoff'))
        self.assertIn('Cut Off & Maintenance Harian PLN', data_inq.get('message', ''))

        # 3. Checkout token/tagihan ditolak dengan 400 is_cutoff=True
        res_checkout = self.client.post('/trx/checkout', json={
            'sku_code': 'post685486',
            'target_number': '530000000001',
            'payment_method': 'saldo',
            'inquiry_ref_id': 'GT-PASCA-TESTCUTOFF',
            'amount': 50000.0
        })
        self.assertEqual(res_checkout.status_code, 400)
        data_checkout = res_checkout.get_json()
        self.assertTrue(data_checkout.get('is_cutoff'))
        self.assertIn('Cut Off & Maintenance Harian PLN', data_checkout.get('message', ''))

    def test_11_pln_cutoff_time_logic(self):
        from datetime import datetime
        from app.services.digiflazz import is_pln_cutoff_time

        # 23:29 -> Normal (Bukan Cut Off)
        t1 = datetime(2026, 9, 6, 23, 29)
        self.assertFalse(is_pln_cutoff_time(t1))

        # 23:30 -> Cut Off Dimulai
        t2 = datetime(2026, 9, 6, 23, 30)
        self.assertTrue(is_pln_cutoff_time(t2))

        # 23:59 -> Masih Cut Off
        t3 = datetime(2026, 9, 6, 23, 59)
        self.assertTrue(is_pln_cutoff_time(t3))

        # 00:00 -> Masih Cut Off
        t4 = datetime(2026, 9, 6, 0, 0)
        self.assertTrue(is_pln_cutoff_time(t4))

        # 00:45 -> Masih Cut Off
        t5 = datetime(2026, 9, 6, 0, 45)
        self.assertTrue(is_pln_cutoff_time(t5))

        # 01:00 -> Kembali Normal
        t6 = datetime(2026, 9, 6, 1, 0)
        self.assertFalse(is_pln_cutoff_time(t6))

        # 14:00 Siang -> Normal
        t7 = datetime(2026, 9, 6, 14, 0)
        self.assertFalse(is_pln_cutoff_time(t7))

if __name__ == '__main__':
    unittest.main()
