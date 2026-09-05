"""
Test Suite: Verifikasi Fitur Bebas Nominal Digiflazz E-Money
- Parameter 'amount' pada inquiry_pasca sesuai dokumentasi Digiflazz
- Validasi input nominal minimum Rp 10.000
- Perhitungan Total Bayar = Nominal Topup + Biaya Admin
- Alur Checkout via Saldo dan QRIS
- Proteksi agar produk prabayar reguler tidak terganggu
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.product import Product
from app.models.transaction import Transaction
from app.services.digiflazz import inquiry_pasca, pay_pasca

class TestBebasNominalSuite(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Buat user pengetesan jika belum ada
        self.test_user = User.query.filter_by(phone='081199998888').first()
        if not self.test_user:
            self.test_user = User(
                name='TestBebasUser',
                phone='081199998888',
                password_hash='testhash',
                role='user',
                balance=100000.0,
                is_active=True
            )
            db.session.add(self.test_user)
            db.session.commit()
        else:
            self.test_user.balance = 100000.0
            db.session.commit()

        # Login session
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.test_user.id)
            sess['_fresh'] = True

    def tearDown(self):
        # Bersihkan transaksi pengujian
        Transaction.query.filter(Transaction.target_number == '081199998888').delete()
        db.session.commit()
        self.app_context.pop()

    def test_01_inquiry_pasca_amount_payload(self):
        """Memastikan inquiry_pasca menyertakan 'amount' dalam payload ke Digiflazz."""
        with patch('requests.post') as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                'data': {
                    'rc': '00',
                    'status': 'Sukses',
                    'customer_name': 'Test Pelanggan',
                    'selling_price': 51700
                }
            }

            ok, data, msg = inquiry_pasca(
                sku='post685481',
                customer_no='081234567890',
                ref_id='TEST-INQ-01',
                amount=50000
            )
            self.assertTrue(ok)
            self.assertEqual(mock_post.call_count, 1)
            sent_payload = mock_post.call_args[1].get('json', {})
            self.assertEqual(sent_payload.get('commands'), 'inq-pasca')
            self.assertEqual(sent_payload.get('buyer_sku_code'), 'post685481')
            self.assertEqual(sent_payload.get('amount'), 50000, "Parameter amount harus dikirim sebagai integer!")
            print("  [OK] Test 1: inquiry_pasca mengirimkan parameter 'amount': 50000 sesuai dokumen resmi Digiflazz.")

    def test_02_validation_nominal_bebas(self):
        """Memastikan sistem menolak checkout jika nominal kosong atau kurang dari Rp 10.000."""
        # 1. Nominal 0
        res_zero = self.client.post('/trx/checkout', json={
            'sku_code': 'post685481',
            'target_number': '081199998888',
            'payment_method': 'saldo',
            'amount': 0
        })
        d_zero = res_zero.get_json()
        self.assertEqual(d_zero.get('status'), 'error')
        self.assertIn('10.000', d_zero.get('message', ''))

        # 2. Nominal < 10.000 (misal Rp 5.000)
        res_small = self.client.post('/trx/checkout', json={
            'sku_code': 'post685481',
            'target_number': '081199998888',
            'payment_method': 'saldo',
            'amount': 5000
        })
        d_small = res_small.get_json()
        self.assertEqual(d_small.get('status'), 'error')
        self.assertIn('10.000', d_small.get('message', ''))
        print("  [OK] Test 2: Validasi minimum nominal Rp 10.000 bekerja dengan tepat.")

    def test_03_checkout_qris_bebas_nominal(self):
        """Memastikan checkout QRIS bebas nominal menghitung total harga (nominal + biaya admin)."""
        prod = Product.query.filter_by(sku_code='post685481').first()
        admin_fee = float(prod.sell_price) if prod else 1700.0

        topup_nominal = 50000.0
        expected_total = topup_nominal + admin_fee

        res = self.client.post('/trx/checkout', json={
            'sku_code': 'post685481',
            'target_number': '081199998888',
            'payment_method': 'qris',
            'nominal': topup_nominal,
            'amount': topup_nominal
        })
        d = res.get_json()
        self.assertEqual(d.get('status'), 'success')
        ref_id = d.get('ref_id')

        trx = Transaction.query.filter_by(ref_id=ref_id).first()
        self.assertIsNotNone(trx)
        self.assertEqual(trx.amount, expected_total, f"Amount harus {expected_total}, dapat {trx.amount}")
        self.assertFalse(trx.is_prepaid, "Transaksi bebas nominal harus bertipe pascabayar (is_prepaid=False)")
        print(f"  [OK] Test 3: Checkout QRIS Bebas Nominal menghasilkan invoice Rp {trx.amount:,.0f} (Nominal {topup_nominal:,.0f} + Admin {admin_fee:,.0f}).")

    @patch('app.services.digiflazz.inquiry_pasca')
    @patch('app.services.digiflazz.pay_pasca')
    def test_04_checkout_saldo_bebas_nominal_sukses(self, mock_pay, mock_inq):
        """Memastikan checkout saldo bebas nominal memotong saldo sesuai total dan memicu inq + pay Digiflazz."""
        mock_inq.return_value = (True, {'rc': '00', 'status': 'Sukses'}, 'Inquiry berhasil')
        mock_pay.return_value = (True, {'rc': '00', 'status': 'Sukses', 'sn': 'DIGI987654321'}, 'Pembayaran sukses')

        prod = Product.query.filter_by(sku_code='post685481').first()
        admin_fee = float(prod.sell_price) if prod else 1700.0
        topup_nominal = 25000.0
        expected_total = topup_nominal + admin_fee

        saldo_awal = self.test_user.balance

        res = self.client.post('/trx/checkout', json={
            'sku_code': 'post685481',
            'target_number': '081199998888',
            'payment_method': 'saldo',
            'nominal': topup_nominal,
            'amount': topup_nominal
        })
        d = res.get_json()
        self.assertEqual(d.get('status'), 'success')

        # Cek inquiry_pasca dipanggil dengan amount=nominal
        mock_inq.assert_called_once()
        call_kwargs = mock_inq.call_args[1]
        self.assertEqual(call_kwargs.get('amount'), topup_nominal)

        # Cek pemotongan saldo user
        db.session.refresh(self.test_user)
        self.assertEqual(self.test_user.balance, saldo_awal - expected_total)
        print(f"  [OK] Test 4: Checkout Saldo Bebas Nominal sukses memotong saldo Rp {expected_total:,.0f} dan memanggil Digiflazz inq-pasca + pay-pasca.")

    def test_05_regular_prepaid_not_affected(self):
        """Memastikan produk reguler (fixed price) tidak salah terdeteksi sebagai bebas nominal."""
        reg_prod = Product.query.filter(
            Product.category.ilike('%e-money%') & ~Product.name.ilike('%bebas%') & (Product.is_active == True)
        ).first()

        if reg_prod:
            res = self.client.post('/trx/checkout', json={
                'sku_code': reg_prod.sku_code,
                'target_number': '081199998888',
                'payment_method': 'qris'
            })
            d = res.get_json()
            self.assertEqual(d.get('status'), 'success')
            trx = Transaction.query.filter_by(ref_id=d.get('ref_id')).first()
            self.assertEqual(trx.amount, float(reg_prod.sell_price))
            print(f"  [OK] Test 5: Produk reguler ({reg_prod.name}) berjalan normal dengan harga tetap Rp {trx.amount:,.0f} tanpa memerlukan nominal bebas.")

if __name__ == '__main__':
    print("=" * 70)
    print("  PENGUJIAN UNIT FITUR BEBAS NOMINAL DIGIFLAZZ (E-MONEY)")
    print("=" * 70)
    unittest.main(verbosity=1)
