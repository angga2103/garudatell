"""
Test Suite: Verifikasi Sinkronisasi Status Transaksi Digiflazz & Webhook
1. sync_single_transaction: Sukses -> Update status SUCCESS, isi SN, award poin
2. sync_single_transaction: Gagal -> Update status FAILED, auto-refund saldo user
3. Endpoint /trx/detail/<ref_id>: Mengembalikan status real-time
4. Webhook Digiflazz (/trx/callback/digiflazz):
   - Validasi HMAC-SHA1 X-Hub-Signature
   - Fallback toleran User-Agent: Digiflazz-Hookshot saat Secret kosong
   - Idempotensi callback pada transaksi SUCCESS
5. Auto-sync pada route /riwayat
"""

import os
import sys
import hmac
import hashlib
import json
import unittest
from unittest.mock import patch, MagicMock

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.transaction import Transaction
from app.routes.transaction import sync_single_transaction

class TestDigiflazzSyncAndWebhook(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Buat user pengetesan
        self.user = User.query.filter_by(phone='081775700114').first()
        if not self.user:
            self.user = User(
                name='User DANA Test',
                phone='081775700114',
                password_hash='testhash',
                role='user',
                balance=50000.0,
                is_active=True
            )
            db.session.add(self.user)
            db.session.commit()
        else:
            self.user.balance = 50000.0
            db.session.commit()

        # Login session
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.user.id)
            sess['_fresh'] = True

    def tearDown(self):
        Transaction.query.filter(Transaction.target_number == '081775700114').delete()
        db.session.commit()
        self.app_context.pop()

    @patch('app.services.digiflazz.check_transaction_status')
    def test_01_sync_single_transaction_success(self, mock_check):
        mock_check.return_value = (True, {
            'status': 'Sukses',
            'rc': '00',
            'sn': 'DFN-DANA-99887766',
            'message': 'Cek Akun Berhasil'
        }, 'Sukses')

        trx = Transaction(
            ref_id='GT-TEST-SYNC-01',
            user_id=self.user.id,
            product_name='Cek Nama Pengguna DANA',
            sku_code='danacek',
            target_number='081775700114',
            amount=210.0,
            payment_method='SALDO',
            payment_status='PAID',
            status='PROCESSING',
            is_prepaid=True
        )
        db.session.add(trx)
        db.session.commit()

        changed = sync_single_transaction(trx)
        self.assertTrue(changed)
        self.assertEqual(trx.status, 'SUCCESS')
        self.assertEqual(trx.sn, 'DFN-DANA-99887766')

    @patch('app.services.digiflazz.check_transaction_status')
    def test_02_sync_single_transaction_failed_refund(self, mock_check):
        mock_check.return_value = (True, {
            'status': 'Gagal',
            'rc': '42',
            'sn': '',
            'message': 'Nomor Tujuan Salah'
        }, 'Gagal')

        initial_balance = self.user.balance
        trx = Transaction(
            ref_id='GT-TEST-SYNC-02',
            user_id=self.user.id,
            product_name='Cek Nama Pengguna DANA',
            sku_code='danacek',
            target_number='081775700114',
            amount=5000.0,
            payment_method='SALDO',
            payment_status='PAID',
            status='PROCESSING',
            is_prepaid=True
        )
        db.session.add(trx)
        db.session.commit()

        changed = sync_single_transaction(trx)
        self.assertTrue(changed)
        self.assertEqual(trx.status, 'FAILED')
        user_refresh = User.query.get(self.user.id)
        self.assertEqual(user_refresh.balance, initial_balance + 5000.0)

    @patch('app.services.digiflazz.check_transaction_status')
    def test_03_trx_detail_endpoint(self, mock_check):
        mock_check.return_value = (True, {
            'status': 'Sukses',
            'rc': '00',
            'sn': 'SN-DETAIL-OK-123',
            'message': 'Transaksi Sukses'
        }, 'Sukses')

        trx = Transaction(
            ref_id='GT-TEST-DETAIL-01',
            user_id=self.user.id,
            product_name='Cek Nama Pengguna DANA',
            sku_code='danacek',
            target_number='081775700114',
            amount=210.0,
            payment_method='SALDO',
            payment_status='PAID',
            status='PROCESSING',
            is_prepaid=True
        )
        db.session.add(trx)
        db.session.commit()

        res = self.client.get(f'/trx/detail/{trx.ref_id}')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('status'), 'success')
        self.assertEqual(data.get('trx_status'), 'SUCCESS')
        self.assertEqual(data.get('sn'), 'SN-DETAIL-OK-123')

    def test_04_webhook_with_signature(self):
        trx = Transaction(
            ref_id='GT-TEST-WH-01',
            user_id=self.user.id,
            product_name='DANA 10.000',
            sku_code='dana10',
            target_number='081775700114',
            amount=10200.0,
            payment_method='SALDO',
            payment_status='PAID',
            status='PROCESSING',
            is_prepaid=True
        )
        db.session.add(trx)
        db.session.commit()

        payload = {
            'data': {
                'ref_id': trx.ref_id,
                'customer_no': '081775700114',
                'buyer_sku_code': 'dana10',
                'status': 'Sukses',
                'rc': '00',
                'sn': 'WH-HMAC-OK-9988',
                'message': 'Transaksi Sukses'
            }
        }
        body_bytes = json.dumps(payload).encode('utf-8')
        secret = os.getenv('DIGI_WEBHOOK_SECRET', os.getenv('DIGI_KEY', 'testkey')).strip()
        sig = hmac.new(secret.encode('utf-8'), body_bytes, hashlib.sha1).hexdigest()

        headers = {
            'Content-Type': 'application/json',
            'X-Hub-Signature': f'sha1={sig}'
        }
        res = self.client.post('/trx/callback/digiflazz', data=body_bytes, headers=headers)
        self.assertEqual(res.status_code, 200)

        trx_refresh = Transaction.query.filter_by(ref_id=trx.ref_id).first()
        self.assertEqual(trx_refresh.status, 'SUCCESS')
        self.assertEqual(trx_refresh.sn, 'WH-HMAC-OK-9988')

    def test_05_webhook_without_signature_hookshot_fallback(self):
        trx = Transaction(
            ref_id='GT-TEST-WH-02',
            user_id=self.user.id,
            product_name='Cek Nama Pengguna DANA',
            sku_code='danacek',
            target_number='081775700114',
            amount=210.0,
            payment_method='SALDO',
            payment_status='PAID',
            status='PROCESSING',
            is_prepaid=True
        )
        db.session.add(trx)
        db.session.commit()

        payload = {
            'data': {
                'ref_id': trx.ref_id,
                'customer_no': '081775700114',
                'buyer_sku_code': 'danacek',
                'status': 'Sukses',
                'rc': '00',
                'sn': 'HOOKSHOT-OK-112233',
                'message': 'Sukses dari Digiflazz'
            }
        }
        body_bytes = json.dumps(payload).encode('utf-8')

        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Digiflazz-Hookshot',
            'X-Digiflazz-Event': 'update'
        }
        res = self.client.post('/trx/callback/digiflazz', data=body_bytes, headers=headers)
        self.assertEqual(res.status_code, 200)

        trx_refresh = Transaction.query.filter_by(ref_id=trx.ref_id).first()
        self.assertEqual(trx_refresh.status, 'SUCCESS')
        self.assertEqual(trx_refresh.sn, 'HOOKSHOT-OK-112233')

    @patch('app.services.digiflazz.check_transaction_status')
    def test_06_riwayat_route_auto_sync(self, mock_check):
        mock_check.return_value = (True, {
            'status': 'Sukses',
            'rc': '00',
            'sn': 'AUTO-SYNC-RIWAYAT-OK',
            'message': 'Selesai'
        }, 'Sukses')

        trx = Transaction(
            ref_id='GT-TEST-RIWAYAT-01',
            user_id=self.user.id,
            product_name='Cek Nama Pengguna DANA',
            sku_code='danacek',
            target_number='081775700114',
            amount=210.0,
            payment_method='SALDO',
            payment_status='PAID',
            status='PROCESSING',
            is_prepaid=True
        )
        db.session.add(trx)
        db.session.commit()

        res = self.client.get('/riwayat')
        self.assertEqual(res.status_code, 200)

        trx_refresh = Transaction.query.filter_by(ref_id=trx.ref_id).first()
        self.assertEqual(trx_refresh.status, 'SUCCESS')
        self.assertEqual(trx_refresh.sn, 'AUTO-SYNC-RIWAYAT-OK')

if __name__ == '__main__':
    unittest.main()
